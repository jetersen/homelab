import { writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const packages = {
  talos: ['siderolabs/talos', 'ghcr.io/siderolabs/talos'],
  kubernetes: ['kubernetes/kubernetes', 'ghcr.io/siderolabs/kubelet'],
};

export function version(value) {
  const match = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(value);
  if (!match) throw new Error(`Expected a stable release version: ${value}`);
  const [, major, minor, patch] = match.map(Number);
  return { major, minor, patch, text: `${major}.${minor}.${patch}`, line: `${major}.${minor}` };
}

export function liveVersions(badges, now = Date.now() / 1000) {
  for (const id of ['node', 'cilium', 'envoy', 'flux', 'cert-manager']) {
    const badge = badges[id];
    if (badge?.id !== id || typeof badge.result !== 'number' ||
        !Number.isFinite(badge.result) || now - badge.result > 120 || now - badge.result < -30) {
      throw new Error(`Missing, ambiguous, or stale live ${id} metrics`);
    }
  }
  const talos = /^Talos \((v\d+\.\d+\.\d+)\)$/.exec(badges.node.labels?.os_image)?.[1];
  const imageVersion = (id, repository) => {
    const image = badges[id].labels?.image_spec ?? '';
    const match = new RegExp(`^[^/]+/${repository}:v(\\d+\\.\\d+\\.\\d+)(?:@sha256:[a-f0-9]{64})?$`).exec(image);
    return version(match?.[1]);
  };
  return {
    talos: version(talos),
    kubernetes: version(badges.node.labels?.kubelet_version),
    cilium: imageVersion('cilium', 'cilium/cilium'),
    envoy: imageVersion('envoy', 'envoyproxy/gateway'),
    flux: version(/^(v\d+\.\d+\.\d+)@sha256:[a-f0-9]{64}$/.exec(badges.flux.labels?.revision)?.[1]),
    'cert-manager': imageVersion('cert-manager', 'jetstack/cert-manager-controller'),
  };
}

export function cachedMatrices(catalog, live, now = Date.now()) {
  const refreshed = Date.parse(catalog?.refreshedAt);
  if (catalog?.schemaVersion !== 3 || !Number.isFinite(refreshed) ||
      now - refreshed > 45 * 24 * 60 * 60 * 1000 || refreshed - now > 300_000) {
    throw new Error('Missing, unsupported, or stale compatibility cache');
  }
  const result = {};
  for (const [id, project, sourcePattern] of [
    ['cilium', 'cilium', /^https:\/\/raw\.githubusercontent\.com\/cilium\/cilium\/v\d+\.\d+\.\d+\/Documentation\/network\/kubernetes\/compatibility\.rst$/],
    ['envoy', 'envoy-gateway', /^https:\/\/raw\.githubusercontent\.com\/envoyproxy\/gateway\/v\d+\.\d+\.\d+\/site\/content\/en\/news\/releases\/matrix\.md$/],
    ['flux', 'flux', /^https:\/\/api\.github\.com\/repos\/fluxcd\/flux2\/releases\/tags\/v\d+\.\d+\.0$/],
    ['cert-manager', 'cert-manager', /^https:\/\/raw\.githubusercontent\.com\/cert-manager\/website\/master\/content\/docs\/releases\/README\.md$/],
    ['talos', 'talos', /^https:\/\/raw\.githubusercontent\.com\/siderolabs\/docs\/main\/public\/talos\/v\d+\.\d+\/getting-started\/support-matrix\.mdx$/],
  ]) {
    const data = catalog.projects?.[project];
    const tag = ['talos', 'cert-manager'].includes(id) ? `v${live[id].line}` : `v${live[id].text}`;
    const entry = data?.versions?.[tag];
    const versions = entry?.supportedKubernetes;
    if (entry?.unavailable || !sourcePattern.test(data?.source ?? '') ||
        !/^[a-f0-9]{64}$/.test(entry?.sourceSha256 ?? '') ||
        !Array.isArray(versions) || !versions.length ||
        versions.some(v => typeof v !== 'string' || !/^\d+\.\d+$/.test(v)) ||
        new Set(versions).size !== versions.length) {
      throw new Error(`Missing or invalid released compatibility cache: ${project}/${tag}`);
    }
    if (id === 'flux') {
      const expected = `https://api.github.com/repos/fluxcd/flux2/releases/tags/v${live.flux.line}.0`;
      const minimums = entry.minimumKubernetes;
      if (entry.source !== expected || !minimums || Object.keys(minimums).length !== versions.length ||
          versions.some(line => version(minimums[line]).line !== line)) {
        throw new Error('Invalid upstream Flux release provenance or minimum patch versions');
      }
      const minimum = minimums[live.kubernetes.line];
      if (minimum && live.kubernetes.patch < version(minimum).patch) {
        throw new Error('Running Kubernetes is below the Flux minimum patch version');
      }
    }
    result[id] = { source: data.source, ...entry };
  }
  return result;
}

export function policy(live, matrices, talosLines = [live.talos.line], kubernetesMinimums = {}) {
  if (!matrices.length) throw new Error('Compatibility matrices are required');
  const supported = matrices.reduce((common, list) => common.filter(v => list.includes(v)));
  if (!supported.includes(live.kubernetes.line)) {
    throw new Error('Running Kubernetes is outside the deployed compatibility intersection');
  }
  const packageRules = [];
  for (const name of ['talos', 'kubernetes']) {
    const current = live[name];
    // Propose at most one minor step; only patches on the live minor may auto-merge.
    const next = `${current.major}.${current.minor + 1}`;
    const allowNext = name === 'talos' ? talosLines.includes(next) : supported.includes(next);
    const upper = `${current.major}.${current.minor + (allowNext ? 2 : 1)}.0`;
    let allowedVersions = `>=${current.text} <${upper}`;
    if (name === 'kubernetes' && allowNext && kubernetesMinimums[next]) {
      allowedVersions = `>=${current.text} <${next}.0 || >=${kubernetesMinimums[next]} <${upper}`;
    }
    packageRules.push({
      description: `Constrain ${name} to the live cluster and released compatibility matrices`,
      matchPackageNames: packages[name],
      allowedVersions,
      automerge: false,
    }, {
      description: `Allow ${name} patches only on the live minor`,
      matchPackageNames: packages[name],
      matchCurrentVersion: `>=${current.line}.0 <${current.major}.${current.minor + 1}.0`,
      matchUpdateTypes: ['patch'],
      automerge: true,
    });
  }
  return { supported, packageRules };
}

async function fetchText(url, headers = {}) {
  const response = await fetch(url, { signal: AbortSignal.timeout(30_000), cache: 'no-store', headers, redirect: 'error' });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
  return response.text();
}

export async function generate(base = 'https://upgrade-versions.lan.jetersen.dev') {
  const entries = await Promise.all(['node', 'cilium', 'envoy', 'flux', 'cert-manager'].map(async id =>
    [id, JSON.parse(await fetchText(`${base}/badges/${id}?format=json`))]));
  const live = liveVersions(Object.fromEntries(entries));
  const cacheUrl = 'https://forgejo.jetersen.dev/api/v1/repos/jetersen/kubernetes-compatibility/raw/catalog.json?ref=main';
  // The repository is public, but this Forgejo instance requires sign-in.
  const token = process.env.RENOVATE_TOKEN || process.env.FORGEJO_TOKEN;
  const catalog = JSON.parse(await fetchText(cacheUrl, token ? { Authorization: `token ${token}` } : {}));
  const matrices = cachedMatrices(catalog, live);
  return {
    live, cacheUrl, cacheRefreshedAt: catalog.refreshedAt,
    urls: Object.fromEntries(Object.entries(matrices).map(([name, entry]) => [name, entry.source])),
    ...policy(live, Object.values(matrices).map(entry => entry.supportedKubernetes),
      Object.entries(catalog.projects.talos.versions)
        .filter(([tag, entry]) => /^v\d+\.\d+$/.test(tag) && !entry.unavailable &&
          Array.isArray(entry.supportedKubernetes) && entry.supportedKubernetes.includes(live.kubernetes.line))
        .map(([tag]) => tag.slice(1)), matrices.flux.minimumKubernetes),
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = await generate();
  console.log(JSON.stringify(result, null, 2));
  if (process.argv[2]) await writeFile(process.argv[2], JSON.stringify(result.packageRules));
}
