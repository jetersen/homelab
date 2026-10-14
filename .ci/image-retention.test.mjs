import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import {
  forgejoClient,
  imagePins,
  protectManifests,
  retentionPlan,
  run,
} from "./image-retention.mjs";

const now = Date.now();
const date = (days) => new Date(now - days * 86_400_000).toISOString();
const digest = (letter) => `sha256:${letter.repeat(64)}`;
const pins = () => ({ "runner-job": new Set(["0.1.0"]), "backup-helper": new Set(["0.1.0"]) });
function inventory() {
  let id = 0;
  return ["runner-job", "backup-helper"].flatMap((component) =>
    ["0.1.0", "0.2.0", "0.9.0", "0.10.0", "1.0.0", "1.1.0", "main", "keep-recovery"].map(
      (version) => ({
        id: ++id,
        component,
        type: "container",
        name: `homelab/${component}`,
        version,
        created_at: date(60),
      }),
    ),
  );
}
const manifest = async (_component, version) => ({
  schemaVersion: 2,
  digest: digestPattern(version) ? version : digest("a"),
});
const digestPattern = (version) => /^sha256:[a-f0-9]{64}$/.test(version);

test("preserves three semantic releases, old configuration pins and moving/keep tags", () => {
  const plan = retentionPlan(inventory(), pins(), now);
  for (const component of ["runner-job", "backup-helper"]) {
    assert.deepEqual(
      plan[component].remove.map((p) => p.version),
      ["0.2.0", "0.9.0"],
    );
    assert.equal(
      plan[component].keep.find((p) => p.version === "0.10.0").reason,
      "latest three releases",
    );
    assert.equal(
      plan[component].keep.find((p) => p.version === "0.1.0").reason,
      "configuration pin",
    );
  }
});

test("30-day grace overrides pruning, including the cutoff boundary", () => {
  const data = inventory();
  const row = data.find((p) => p.component === "runner-job" && p.version === "0.2.0");
  row.created_at = date(29);
  assert.equal(retentionPlan(data, pins(), now)["runner-job"].remove.length, 1);
  row.created_at = date(30);
  assert.equal(retentionPlan(data, pins(), now)["runner-job"].remove.length, 2);
});

test("reads version and digest pins from Kubernetes and CI configuration", () => {
  const result = imagePins(
    `image: registry.invalid/owner/homelab/runner-job:0.1.0@${digest("b")}\n` +
      `docker://registry.invalid/owner/homelab/backup-helper:1.0.0\n` +
      `image: registry.invalid/owner/homelab/runner-job@${digest("c")}\n` +
      "image: registry.invalid/owner/homelab/flux:main\n" +
      "image: other.invalid/owner/homelab/runner-job:9.9.9\n",
    "registry.invalid",
    "owner/homelab",
  );
  assert.deepEqual([...result["runner-job"]], ["0.1.0", digest("b"), digest("c")]);
  assert.deepEqual([...result["backup-helper"]], ["1.0.0"]);
});

test("fails closed on missing pins, invalid dates, duplicate versions or absent main", () => {
  for (const mutate of [
    (data) => data.push({ ...data[0] }),
    (data) => {
      data[0].created_at = "invalid";
    },
    (data) => {
      data[0].created_at = new Date(now + 600_000).toISOString();
    },
    (data) => {
      data[0].type = "generic";
    },
    (data) => {
      data[0].id = undefined;
    },
  ]) {
    const data = inventory();
    mutate(data);
    assert.throws(() => retentionPlan(data, pins(), now));
  }
  assert.throws(() =>
    retentionPlan(
      inventory().filter((p) => p.version !== "main"),
      pins(),
      now,
    ),
  );
  assert.throws(() => retentionPlan(inventory(), {}, now));
});

test("keeps digest-only children and pinned digests referenced by retained OCI indexes", async () => {
  const data = inventory();
  for (const component of ["runner-job", "backup-helper"]) {
    for (const [i, version] of [digest("a"), digest("b"), digest("c"), digest("d")].entries()) {
      data.push({ ...data.find((p) => p.component === component), id: 100 + i, version });
    }
  }
  const references = pins();
  references["runner-job"].add(digest("c"));
  const plan = await protectManifests(
    retentionPlan(data, references, now),
    references,
    async (_, v) =>
      v === "main"
        ? { schemaVersion: 2, digest: digest("a"), manifests: [{ digest: digest("b") }] }
        : { schemaVersion: 2, digest: digestPattern(v) ? v : digest("a") },
  );
  assert.equal(
    plan["runner-job"].remove.some((p) => p.version === digest("b")),
    false,
  );
  assert.equal(
    plan["runner-job"].remove.some((p) => p.version === digest("c")),
    false,
  );
  assert.equal(
    plan["backup-helper"].remove.some((p) => p.version === digest("d")),
    true,
  );
  await assert.rejects(() =>
    protectManifests(retentionPlan(data, references, now), references, async () => ({
      digest: "invalid",
    })),
  );
});

test("dry runs never delete; changed inventories or stale checkouts abort application", async () => {
  const data = inventory();
  const removed = [];
  const client = {
    inventory: async () => data.filter((p) => !removed.includes(p)),
    manifest,
    remove: async (p) => removed.push(p),
  };
  await run({ client, repository: "homelab", pins: pins() });
  assert.equal(removed.length, 0);
  await assert.rejects(() =>
    run({
      client,
      repository: "homelab",
      pins: pins(),
      apply: true,
      checkHead: () => {
        throw new Error("stale checkout");
      },
    }),
  );
  let calls = 0;
  await assert.rejects(() =>
    run({
      client: { ...client, inventory: async () => (++calls === 1 ? data : data.slice(1)) },
      repository: "homelab",
      pins: pins(),
      apply: true,
    }),
  );
  assert.equal(removed.length, 0);
  await run({ client, repository: "homelab", pins: pins(), apply: true });
  assert.equal(removed.length, 4);
});

test("verifies that deletions completed and protected versions survived", async () => {
  const data = inventory();
  await assert.rejects(() =>
    run({
      client: { inventory: async () => data, manifest, remove: async () => {} },
      repository: "homelab",
      pins: pins(),
      apply: true,
    }),
  );
});

test("API pagination scopes deletion to two packages and ignores Flux and unrelated images", async () => {
  const pages = [
    Array.from({ length: 50 }, (_, i) => ({ name: "homelab/flux", version: `sha-${i}` })),
    [{ name: "homelab/runner-job", version: "1.0.0" }, { name: "another/runner-job" }],
  ];
  const requests = [];
  const client = forgejoClient("https://registry.invalid", "owner", "secret", async (url) => {
    requests.push(url);
    return new Response(JSON.stringify(pages.shift()));
  });
  const result = await client.inventory("homelab");
  assert.equal(result.length, 1);
  assert.equal(result[0].component, "runner-job");
  assert.match(requests[1], /page=2$/);
});

test("registry reads verify digests and deletion rechecks immutable package identity", async () => {
  const body = JSON.stringify({ schemaVersion: 2, layers: [] });
  const hash = `sha256:${createHash("sha256").update(body).digest("hex")}`;
  const requests = [];
  const client = forgejoClient(
    "https://registry.invalid",
    "owner",
    "secret",
    async (url, options) => {
      requests.push([url, options]);
      if (url.includes("/v2/token")) {
        return new Response(JSON.stringify({ token: "registry-token" }));
      }
      if (url.includes("/manifests/")) {
        return new Response(body, { headers: { "Docker-Content-Digest": hash } });
      }
      return new Response(JSON.stringify({ ...inventory()[0], id: 999 }));
    },
  );
  assert.equal((await client.manifest("homelab", "runner-job", "main")).digest, hash);
  assert.equal(requests[1][1].headers.Authorization, "Bearer registry-token");
  await assert.rejects(() => client.manifest("homelab", "runner-job", digest("a")));
  await assert.rejects(() => client.remove(inventory()[0]));
  assert.equal(
    requests.some(([, options]) => options.method === "DELETE"),
    false,
  );
  assert.throws(() => forgejoClient("http://registry.invalid", "owner", "secret"));
  assert.throws(() => forgejoClient("https://registry.invalid", "owner", undefined));
});
