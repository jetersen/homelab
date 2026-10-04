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
  for (const id of ['node', 'cilium', 'envoy']) {
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
  };
}

export function cachedMatrices(catalog, live, now = Date.now()) {
  const refreshed = Date.parse(catalog?.refreshedAt);
  if (catalog?.schemaVersion !== 1 || !Number.isFinite(refreshed) ||
      now - refreshed > 7 * 24 * 60 * 60 * 1000 || refreshed - now > 300_000) {
    throw new Error('Missing, unsupported, or stale compatibility cache');
  }
  const result = {};
  for (const [id, project, repository, path] of [
    ['cilium', 'cilium', 'cilium/cilium', 'Documentation/network/kubernetes/compatibility.rst'],
    ['envoy', 'envoy-gateway', 'envoyproxy/gateway', 'site/content/en/news/releases/matrix.md'],
  ]) {
    const tag = `v${live[id].text}`;
    const entry = catalog.projects?.[project]?.[tag];
    const expectedSource = `https://raw.githubusercontent.com/${repository}/${tag}/${path}`;
    const versions = entry?.supportedKubernetes;
    if (entry?.unavailable || entry?.source !== expectedSource ||
        !/^[a-f0-9]{64}$/.test(entry?.sourceSha256 ?? '') ||
        !Array.isArray(versions) || !versions.length ||
        versions.some(v => typeof v !== 'string' || !/^\d+\.\d+$/.test(v)) ||
        new Set(versions).size !== versions.length) {
      throw new Error(`Missing or invalid released compatibility cache: ${project}/${tag}`);
    }
    result[id] = entry;
  }
  return result;
}

export function policy(live, cilium, envoy) {
  const supported = cilium.filter(v => envoy.includes(v));
  if (!supported.includes(live.kubernetes.line)) {
    throw new Error('Running Kubernetes is outside the deployed Cilium/Envoy compatibility intersection');
  }
  const packageRules = [];
  for (const name of ['talos', 'kubernetes']) {
    const current = live[name];
    // Propose at most one minor step; only patches on the live minor may auto-merge.
    const next = `${current.major}.${current.minor + 1}`;
    const allowNext = name === 'talos' || supported.includes(next);
    const upper = `${current.major}.${current.minor + (allowNext ? 2 : 1)}.0`;
    packageRules.push({
      description: `Constrain ${name} to the live cluster and released compatibility matrices`,
      matchPackageNames: packages[name],
      allowedVersions: `>=${current.text} <${upper}`,
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
  const entries = await Promise.all(['node', 'cilium', 'envoy'].map(async id =>
    [id, JSON.parse(await fetchText(`${base}/badges/${id}?format=json`))]));
  const live = liveVersions(Object.fromEntries(entries));
  const cacheUrl = 'https://forgejo.jetersen.dev/api/v1/repos/jetersen/kubernetes-compatibility/raw/catalog.json?ref=main';
  // The repository is public, but this Forgejo instance requires sign-in.
  const token = process.env.RENOVATE_TOKEN || process.env.FORGEJO_TOKEN;
  const catalog = JSON.parse(await fetchText(cacheUrl, token ? { Authorization: `token ${token}` } : {}));
  const matrices = cachedMatrices(catalog, live);
  return {
    live, cacheUrl, cacheRefreshedAt: catalog.refreshedAt,
    urls: { cilium: matrices.cilium.source, envoy: matrices.envoy.source },
    ...policy(live, matrices.cilium.supportedKubernetes, matrices.envoy.supportedKubernetes),
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = await generate();
  console.log(JSON.stringify(result, null, 2));
  if (process.argv[2]) await writeFile(process.argv[2], JSON.stringify(result.packageRules));
}
