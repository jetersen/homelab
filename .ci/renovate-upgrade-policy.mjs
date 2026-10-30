import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const packages = {
  talos: ["siderolabs/talos", "ghcr.io/siderolabs/talos"],
  kubernetes: ["kubernetes/kubernetes", "ghcr.io/siderolabs/kubelet"],
  flux: ["controlplaneio-fluxcd/distribution"],
};

export function version(value) {
  const match = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(value);
  if (!match) {
    throw new Error(`Expected a stable release version: ${value}`);
  }
  const [, major, minor, patch] = match.map(Number);
  return { major, minor, patch, text: `${major}.${minor}.${patch}`, line: `${major}.${minor}` };
}

export function liveVersions(badges, now = Date.now() / 1000) {
  for (const id of ["node", "cilium", "envoy", "flux", "flux-operator", "cert-manager"]) {
    const badge = badges[id];
    if (
      badge?.id !== id ||
      typeof badge.result !== "number" ||
      !Number.isFinite(badge.result) ||
      now - badge.result > 120 ||
      now - badge.result < -30
    ) {
      throw new Error(`Missing, ambiguous, or stale live ${id} metrics`);
    }
  }
  const talos = /^Talos \((v\d+\.\d+\.\d+)\)$/.exec(badges.node.labels?.os_image)?.[1];
  const imageVersion = (id, repository) => {
    const image = badges[id].labels?.image_spec ?? "";
    const match = new RegExp(
      `^[^/]+/${repository}:v(\\d+\\.\\d+\\.\\d+)(?:@sha256:[a-f0-9]{64})?$`,
    ).exec(image);
    return version(match?.[1]);
  };
  return {
    talos: version(talos),
    kubernetes: version(badges.node.labels?.kubelet_version),
    cilium: imageVersion("cilium", "cilium/cilium"),
    envoy: imageVersion("envoy", "envoyproxy/gateway"),
    flux: version(/^(v\d+\.\d+\.\d+)@sha256:[a-f0-9]{64}$/.exec(badges.flux.labels?.revision)?.[1]),
    "flux-operator": imageVersion("flux-operator", "controlplaneio-fluxcd/flux-operator"),
    "cert-manager": imageVersion("cert-manager", "jetstack/cert-manager-controller"),
  };
}

export function cachedMatrices(catalog, live, now = Date.now()) {
  const refreshed = Date.parse(catalog?.refreshedAt);
  if (
    catalog?.schemaVersion !== 3 ||
    !Number.isFinite(refreshed) ||
    now - refreshed > 45 * 24 * 60 * 60 * 1000 ||
    refreshed - now > 300_000
  ) {
    throw new Error("Missing, unsupported, or stale compatibility cache");
  }
  const result = {};
  for (const [id, project, sourcePattern] of [
    [
      "cilium",
      "cilium",
      /^https:\/\/raw\.githubusercontent\.com\/cilium\/cilium\/v\d+\.\d+\.\d+\/Documentation\/network\/kubernetes\/compatibility\.rst$/,
    ],
    [
      "envoy",
      "envoy-gateway",
      /^https:\/\/raw\.githubusercontent\.com\/envoyproxy\/gateway\/v\d+\.\d+\.\d+\/site\/content\/en\/news\/releases\/matrix\.md$/,
    ],
    [
      "flux",
      "flux",
      /^https:\/\/api\.github\.com\/repos\/fluxcd\/flux2\/releases\/tags\/v\d+\.\d+\.0$/,
    ],
    [
      "cert-manager",
      "cert-manager",
      /^https:\/\/raw\.githubusercontent\.com\/cert-manager\/website\/master\/content\/docs\/releases\/README\.md$/,
    ],
    [
      "talos",
      "talos",
      /^https:\/\/raw\.githubusercontent\.com\/siderolabs\/docs\/main\/public\/talos\/v\d+\.\d+\/getting-started\/support-matrix\.mdx$/,
    ],
  ]) {
    const data = catalog.projects?.[project];
    const tag = ["talos", "cert-manager"].includes(id) ? `v${live[id].line}` : `v${live[id].text}`;
    const entry = data?.versions?.[tag];
    const versions = entry?.supportedKubernetes;
    if (
      entry?.unavailable ||
      !sourcePattern.test(data?.source ?? "") ||
      !/^[a-f0-9]{64}$/.test(entry?.sourceSha256 ?? "") ||
      !Array.isArray(versions) ||
      !versions.length ||
      versions.some((v) => typeof v !== "string" || !/^\d+\.\d+$/.test(v)) ||
      new Set(versions).size !== versions.length
    ) {
      throw new Error(`Missing or invalid released compatibility cache: ${project}/${tag}`);
    }
    if (id === "flux") {
      const expected = `https://api.github.com/repos/fluxcd/flux2/releases/tags/v${live.flux.line}.0`;
      if (entry.source !== expected) {
        throw new Error("Invalid upstream Flux release provenance");
      }
    }
    result[id] = { source: data.source, ...entry };
  }
  return result;
}

export function policy(live, matrices, talosLines = [live.talos.line]) {
  if (!matrices.length) {
    throw new Error("Compatibility matrices are required");
  }
  const supported = matrices.reduce((common, list) => common.filter((v) => list.includes(v)));
  if (!supported.includes(live.kubernetes.line)) {
    throw new Error("Running Kubernetes is outside the deployed compatibility intersection");
  }
  const packageRules = [];
  for (const name of ["talos", "kubernetes"]) {
    const current = live[name];
    // Propose at most one minor step; only patches on the live minor may auto-merge.
    const next = `${current.major}.${current.minor + 1}`;
    const allowNext = name === "talos" ? talosLines.includes(next) : supported.includes(next);
    const upper = `${current.major}.${current.minor + (allowNext ? 2 : 1)}.0`;
    packageRules.push(
      {
        description: `Constrain ${name} to the live cluster and released compatibility matrices`,
        matchPackageNames: packages[name],
        allowedVersions: `>=${current.text} <${upper}`,
        automerge: false,
      },
      {
        description: `Allow ${name} patches only on the live minor`,
        matchPackageNames: packages[name],
        matchCurrentVersion: `>=${current.line}.0 <${current.major}.${current.minor + 1}.0`,
        matchUpdateTypes: ["patch"],
        automerge: true,
      },
    );
  }
  return { supported, packageRules };
}

function validOperatorEntry(entry, tag) {
  return (
    /^v\d+\.\d+\.\d+$/.test(tag) &&
    entry?.source ===
      `https://api.github.com/repos/controlplaneio-fluxcd/flux-operator/contents/config/data/flux?ref=${tag}` &&
    /^[a-f0-9]{64}$/.test(entry?.sourceSha256 ?? "") &&
    entry.unavailable === undefined &&
    Array.isArray(entry.supportedFlux) &&
    entry.supportedFlux.length > 0 &&
    entry.supportedFlux.every((line) => typeof line === "string" && /^\d+\.\d+$/.test(line)) &&
    new Set(entry.supportedFlux).size === entry.supportedFlux.length
  );
}

export function fluxUpgradePolicy(catalog, live) {
  const project = catalog.projects?.["flux-operator"];
  const tag = `v${live["flux-operator"].text}`;
  const entry = project?.versions?.[tag];
  if (!validOperatorEntry(entry, tag)) {
    throw new Error("Missing or invalid released Flux operator compatibility cache");
  }
  const current = live.flux;
  if (!entry.supportedFlux.includes(current.line)) {
    throw new Error("Running Flux minor is not supported by the deployed operator");
  }
  const operators = Object.entries(project.versions)
    .filter(
      ([tag, candidate]) =>
        validOperatorEntry(candidate, tag) && candidate.supportedFlux.includes(current.line),
    )
    .map(([tag]) => tag.slice(1).replaceAll(".", "\\."));
  const next = `${current.major}.${current.minor + 1}`;
  const nextEntries = Object.entries(catalog.projects?.flux?.versions ?? {}).filter(([tag]) =>
    new RegExp(`^v${current.major}[.]${current.minor + 1}[.]\\d+$`).test(tag),
  );
  // Missing candidate data blocks that minor without preventing operator updates.
  const allowNext =
    entry.supportedFlux.includes(next) &&
    nextEntries.some(
      ([, candidate]) =>
        candidate?.source ===
          `https://api.github.com/repos/fluxcd/flux2/releases/tags/v${next}.0` &&
        /^[a-f0-9]{64}$/.test(candidate.sourceSha256 ?? "") &&
        candidate.unavailable === undefined &&
        Array.isArray(candidate.supportedKubernetes) &&
        candidate.supportedKubernetes.every(
          (line) => typeof line === "string" && /^\d+\.\d+$/.test(line),
        ) &&
        candidate.supportedKubernetes.includes(live.kubernetes.line),
    );
  return {
    operatorSource: entry.source,
    packageRules: [
      {
        description:
          "Constrain Flux to deployed operator support and cached Kubernetes compatibility",
        matchPackageNames: packages.flux,
        allowedVersions: `>=${current.text} <${current.major}.${current.minor + (allowNext ? 2 : 1)}.0`,
        automerge: false,
      },
      {
        description: "Allow Flux patches only on the live minor",
        matchPackageNames: packages.flux,
        matchCurrentVersion: `>=${current.line}.0 <${current.major}.${current.minor + 1}.0`,
        matchUpdateTypes: ["patch"],
        automerge: true,
      },
      {
        description:
          "Only deploy operator releases whose bundled manifests support the running Flux minor",
        matchPackageNames: [
          "ghcr.io/controlplaneio-fluxcd/charts/flux-operator",
          "ghcr.io/controlplaneio-fluxcd/flux-operator",
        ],
        allowedVersions: `/^v?(${operators.join("|")})$/`,
      },
    ],
  };
}

// Arr applications publish numeric Docker tags for both stable and prerelease builds.
const arrProjects = {
  sonarr: "Sonarr/Sonarr",
  radarr: "Radarr/Radarr",
  prowlarr: "Prowlarr/Prowlarr",
};

export function arrStableRule(project, release) {
  if (!Object.hasOwn(arrProjects, project)) {
    throw new Error("Unknown Arr project");
  }
  if (
    release?.prerelease !== false ||
    release?.draft !== false ||
    !/^v\d+\.\d+\.\d+\.\d+$/.test(release?.tag_name ?? "")
  ) {
    throw new Error(`Missing or invalid stable ${project} release metadata`);
  }
  return {
    description: `Only propose ${project} images matching the latest upstream stable release`,
    matchPackageNames: [`ghcr.io/home-operations/${project}`],
    allowedVersions: `/^${release.tag_name.slice(1).replaceAll(".", "\\.")}$/`,
  };
}

export async function completeCiliumPatchMatrix(catalog, live, fetcher = fetchText) {
  const project = catalog?.projects?.cilium;
  const tag = `v${live.cilium.text}`;
  if (project?.versions?.[tag] !== undefined) {
    return catalog;
  }
  const source =
    /^https:\/\/raw\.githubusercontent\.com\/cilium\/cilium\/(v\d+\.\d+\.\d+)\/Documentation\/network\/kubernetes\/compatibility\.rst$/.exec(
      project?.source ?? "",
    );
  const base = source && project.versions?.[source[1]];
  if (!base || base.unavailable || version(source[1]).line !== live.cilium.line) {
    throw new Error("Missing released Cilium minor matrix; refresh the compatibility catalog");
  }
  const url = project.source.replace(source[1], tag);
  const text = await fetcher(url);
  // Reuse parsed data only when the exact released document is byte-identical.
  // New or changed support matrices still require a reviewed catalog refresh.
  if (createHash("sha256").update(text).digest("hex") !== base.sourceSha256) {
    throw new Error("Released Cilium matrix changed; refresh the compatibility catalog");
  }
  return {
    ...catalog,
    projects: {
      ...catalog.projects,
      cilium: { ...project, versions: { ...project.versions, [tag]: { ...base, source: url } } },
    },
  };
}

async function fetchText(url, headers = {}) {
  let response;
  try {
    response = await fetch(url, {
      signal: AbortSignal.timeout(30_000),
      cache: "no-store",
      headers,
      redirect: "error",
    });
  } catch (error) {
    throw new Error(`${error.cause?.message ?? error.message}: ${url}`, { cause: error });
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${url}`);
  }
  return response.text();
}

export async function generate(base = "https://upgrade-versions.jetersen.dev") {
  const entries = await Promise.all(
    ["node", "cilium", "envoy", "flux", "flux-operator", "cert-manager"].map(async (id) => [
      id,
      JSON.parse(await fetchText(`${base}/badges/${id}?format=json`)),
    ]),
  );
  const live = liveVersions(Object.fromEntries(entries));
  const cacheUrl =
    "https://forgejo.jetersen.dev/api/v1/repos/jetersen/kubernetes-compatibility/raw/catalog.json?ref=main";
  // The repository is public, but this Forgejo instance requires sign-in.
  const token = process.env.RENOVATE_TOKEN || process.env.FORGEJO_TOKEN;
  const catalog = await completeCiliumPatchMatrix(
    JSON.parse(await fetchText(cacheUrl, token ? { Authorization: `token ${token}` } : {})),
    live,
  );
  const matrices = cachedMatrices(catalog, live);
  const result = {
    live,
    cacheUrl,
    cacheRefreshedAt: catalog.refreshedAt,
    urls: Object.fromEntries(Object.entries(matrices).map(([name, entry]) => [name, entry.source])),
    ...policy(
      live,
      Object.values(matrices).map((entry) => entry.supportedKubernetes),
      Object.entries(catalog.projects.talos.versions)
        .filter(
          ([tag, entry]) =>
            /^v\d+\.\d+$/.test(tag) &&
            !entry.unavailable &&
            Array.isArray(entry.supportedKubernetes) &&
            entry.supportedKubernetes.includes(live.kubernetes.line),
        )
        .map(([tag]) => tag.slice(1)),
    ),
  };
  const fluxPolicy = fluxUpgradePolicy(catalog, live);
  result.urls["flux-operator"] = fluxPolicy.operatorSource;
  result.packageRules.push(
    ...fluxPolicy.packageRules,
    ...(await Promise.all(
      Object.entries(arrProjects).map(async ([project, repository]) =>
        arrStableRule(
          project,
          JSON.parse(await fetchText(`https://api.github.com/repos/${repository}/releases/latest`)),
        ),
      ),
    )),
  );
  return result;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = await generate();
  console.log(JSON.stringify(result, null, 2));
  if (process.argv[2]) {
    await writeFile(process.argv[2], JSON.stringify(result.packageRules));
  }
}
