import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const components = ["backup-helper", "runner-job"];
const day = 24 * 60 * 60 * 1000;
const digestPattern = /^sha256:[a-f0-9]{64}$/;
const releasePattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;

function releaseOrder(a, b) {
  const left = a.split(".").map(Number),
    right = b.split(".").map(Number);
  for (let i = 0; i < 3; i++) {
    if (left[i] !== right[i]) {
      return right[i] - left[i];
    }
  }
  return 0;
}

export function imagePins(text, registry, repository) {
  const result = Object.fromEntries(components.map((name) => [name, new Set()]));
  const prefix = `${registry}/${repository}/`;
  for (const part of text.split(prefix).slice(1)) {
    const match =
      /^(backup-helper|runner-job)(?::([A-Za-z0-9_.-]+))?(?:@(sha256:[a-f0-9]{64}))?/.exec(part);
    if (match && (match[2] || match[3])) {
      for (const value of match.slice(2).filter(Boolean)) {
        result[match[1]].add(value);
      }
    }
  }
  return result;
}

export function retentionPlan(packages, pins, now = Date.now()) {
  if (!Number.isFinite(now)) {
    throw new Error("Invalid retention time");
  }
  const result = {};
  for (const component of components) {
    const rows = packages.filter((p) => p.component === component);
    const versions = new Set(rows.map((p) => p.version));
    if (!rows.length || versions.size !== rows.length || !pins[component]?.size) {
      throw new Error(`Missing package inventory or configuration pins: ${component}`);
    }
    const latest = new Set(
      [...versions]
        .filter((v) => releasePattern.test(v))
        .sort(releaseOrder)
        .slice(0, 3),
    );
    if (!latest.size || !versions.has("main")) {
      throw new Error(`Missing release versions or main tag: ${component}`);
    }
    const keep = [],
      remove = [];
    for (const row of rows) {
      const created = Date.parse(row.created_at);
      if (
        row.type !== "container" ||
        !Number.isSafeInteger(row.id) ||
        !Number.isFinite(created) ||
        created > now + 300_000
      ) {
        throw new Error(`Invalid package metadata: ${component}/${row.version}`);
      }
      const reason =
        (["main", "latest"].includes(row.version) && "moving tag") ||
        (row.version.startsWith("keep-") && "explicit keep tag") ||
        (latest.has(row.version) && "latest three releases") ||
        (pins[component].has(row.version) && "configuration pin") ||
        (now - created < 30 * day && "30-day grace period");
      if (reason) {
        keep.push({ ...row, reason });
      } else {
        remove.push(row);
      }
    }
    result[component] = { keep, remove };
  }
  return result;
}

// A retained OCI index can reference digest-only package versions. Preserve its
// complete manifest graph before deleting any old tags or digest entries.
export async function protectManifests(plan, pins, manifest) {
  for (const component of components) {
    const protectedDigests = new Set();
    const visited = new Set();
    async function visit(version, depth = 0) {
      if (visited.has(version)) {
        return;
      }
      if (depth > 10 || visited.size > 1000) {
        throw new Error("OCI manifest graph exceeded expected size");
      }
      visited.add(version);
      const data = await manifest(component, version);
      if (!digestPattern.test(data.digest) || data.schemaVersion !== 2) {
        throw new Error(`Invalid OCI manifest: ${component}/${version}`);
      }
      protectedDigests.add(data.digest);
      if (data.manifests !== undefined) {
        if (!Array.isArray(data.manifests)) {
          throw new Error("Invalid OCI manifest index");
        }
        for (const child of data.manifests) {
          if (!digestPattern.test(child.digest)) {
            throw new Error("Invalid OCI child digest");
          }
          await visit(child.digest, depth + 1);
        }
      }
    }
    if (plan[component].remove.length) {
      for (const version of new Set([
        ...plan[component].keep.map((p) => p.version),
        ...pins[component],
      ])) {
        await visit(version);
      }
      plan[component].remove = plan[component].remove.filter((p) => {
        if (protectedDigests.has(p.version)) {
          plan[component].keep.push({ ...p, reason: "retained manifest reference" });
          return false;
        }
        return true;
      });
    }
  }
  return plan;
}

export function forgejoClient(base, owner, token, fetcher = fetch) {
  const url = new URL(base);
  if (url.protocol !== "https:" || url.username || url.password || !token) {
    throw new Error("Expected a trusted HTTPS Forgejo URL and package token");
  }
  const origin = url.origin;
  async function request(path, method = "GET", authorization = `token ${token}`, accept) {
    const response = await fetcher(`${origin}${path}`, {
      method,
      redirect: "error",
      signal: AbortSignal.timeout(30_000),
      headers: { Authorization: authorization, ...(accept && { Accept: accept }) },
    });
    if (!response.ok) {
      throw new Error(`Forgejo ${method} failed (${response.status}): ${path}`);
    }
    return response;
  }
  const packagePath = (p) =>
    `/api/v1/packages/${encodeURIComponent(owner)}/container/${encodeURIComponent(p.name)}/${encodeURIComponent(p.version)}`;
  const registryTokens = new Map();
  return {
    async inventory(repository) {
      const rows = [];
      for (let page = 1; page <= 100; page++) {
        const response = await request(
          `/api/v1/packages/${encodeURIComponent(owner)}?limit=50&page=${page}`,
        );
        const batch = await response.json();
        if (!Array.isArray(batch)) {
          throw new Error("Invalid Forgejo package inventory");
        }
        for (const p of batch) {
          for (const component of components) {
            if (p.name === `${repository}/${component}`) {
              rows.push({ ...p, component });
            }
          }
        }
        if (batch.length < 50) {
          return rows;
        }
      }
      throw new Error("Package pagination exceeded expected range");
    },
    async manifest(repository, component, version) {
      const name = `${owner}/${repository}/${component}`;
      if (!registryTokens.has(name)) {
        const basic = Buffer.from(`${owner}:${token}`).toString("base64");
        const response = await request(
          `/v2/token?service=container_registry&scope=${encodeURIComponent(`repository:${name}:pull`)}`,
          "GET",
          `Basic ${basic}`,
        );
        const result = await response.json();
        if (typeof result.token !== "string" || !result.token) {
          throw new Error("Registry authentication failed");
        }
        registryTokens.set(name, result.token);
      }
      const response = await request(
        `/v2/${name}/manifests/${encodeURIComponent(version)}`,
        "GET",
        `Bearer ${registryTokens.get(name)}`,
        "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json",
      );
      const body = await response.text(),
        digest = `sha256:${createHash("sha256").update(body).digest("hex")}`;
      if (
        digest !== response.headers.get("Docker-Content-Digest") ||
        (digestPattern.test(version) && version !== digest)
      ) {
        throw new Error("Registry manifest digest mismatch");
      }
      return { ...JSON.parse(body), digest };
    },
    async remove(p) {
      const current = await (await request(packagePath(p))).json();
      if (["id", "name", "type", "version", "created_at"].some((key) => current[key] !== p[key])) {
        throw new Error("Package version changed after retention planning");
      }
      const response = await request(packagePath(p), "DELETE");
      if (response.status !== 204) {
        throw new Error("Unexpected package deletion response");
      }
    },
  };
}

async function configuredPins(registry, repository) {
  const files = execFileSync(
    "git",
    ["ls-files", "-z", "kubernetes", "infrastructure/forgejo/runner"],
    {
      encoding: "utf8",
    },
  )
    .split("\0")
    .filter((file) => /\.ya?ml$/.test(file) && !file.includes(".sops."));
  const text = (await Promise.all(files.map((file) => readFile(file, "utf8")))).join("\n");
  const pins = imagePins(text, registry, repository);
  if (process.env.GITHUB_ACTIONS === "true" || process.env.FORGEJO_ACTIONS === "true") {
    const containers = execFileSync("docker", ["ps", "-q"], { encoding: "utf8" })
      .trim()
      .split("\n")
      .filter(Boolean);
    if (!containers.length) {
      throw new Error("Missing running CI container inventory");
    }
    const images = execFileSync(
      "docker",
      ["inspect", "--format", "{{.Config.Image}}", ...containers],
      {
        encoding: "utf8",
      },
    );
    const active = imagePins(images, registry, repository);
    for (const component of components) {
      for (const version of active[component]) {
        pins[component].add(version);
      }
    }
  }
  return pins;
}

function currentHead() {
  const head = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
  const remote = execFileSync("git", ["ls-remote", "origin", "refs/heads/main"], {
    encoding: "utf8",
  }).split(/\s/)[0];
  if (!/^[a-f0-9]{40}$/.test(head) || remote !== head) {
    throw new Error("Refusing retention from a checkout behind origin/main");
  }
}

export async function run({ client, repository, pins, apply = false, checkHead = () => {} }) {
  const inventory = await client.inventory(repository);
  const plan = await protectManifests(retentionPlan(inventory, pins), pins, (component, version) =>
    client.manifest(repository, component, version),
  );
  if (apply) {
    checkHead();
    const current = await client.inventory(repository);
    const key = (p) => JSON.stringify([p.id, p.component, p.version, p.created_at]);
    if (current.map(key).sort().join("\n") !== inventory.map(key).sort().join("\n")) {
      throw new Error("Package inventory changed after retention planning");
    }
    // Tags first: deleting a digest-only child while an old index references it
    // can fail, and shared children must survive every retained index.
    for (const component of components) {
      for (const p of plan[component].remove.toSorted(
        (a, b) => Number(digestPattern.test(a.version)) - Number(digestPattern.test(b.version)),
      )) {
        checkHead();
        await client.remove(p);
      }
    }
    const remaining = new Set((await client.inventory(repository)).map(key));
    for (const component of components) {
      if (
        plan[component].keep.some((p) => !remaining.has(key(p))) ||
        plan[component].remove.some((p) => remaining.has(key(p)))
      ) {
        throw new Error("Package inventory does not match the completed retention plan");
      }
    }
  }
  return Object.fromEntries(
    components.map((name) => [
      name,
      {
        keep: plan[name].keep.map((p) => ({ version: p.version, reason: p.reason })),
        remove: plan[name].remove.map((p) => p.version),
        applied: apply,
      },
    ]),
  );
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const apply = process.argv.slice(2).includes("--apply");
  if (process.argv.slice(2).some((arg) => arg !== "--apply")) {
    throw new Error("Usage: node .ci/image-retention.mjs [--apply]");
  }
  const base = process.env.FORGEJO_HOST ?? "https://forgejo.jetersen.dev",
    owner = process.env.FORGEJO_OWNER ?? "jetersen",
    repository = process.env.FORGEJO_REPOSITORY ?? "homelab";
  if (!/^[\w-]+$/.test(owner) || !/^[\w.-]+$/.test(repository)) {
    throw new Error("Invalid Forgejo owner or repository");
  }
  const pins = await configuredPins(new URL(base).host, `${owner}/${repository}`);
  const client = forgejoClient(base, owner, process.env.FORGEJO_TOKEN);
  console.log(
    JSON.stringify(await run({ client, repository, pins, apply, checkHead: currentHead }), null, 2),
  );
}
