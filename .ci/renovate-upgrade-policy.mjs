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

function minorList(cell) {
  if (!/^v?\d+\.\d+(?:\s*,\s*v?\d+\.\d+)*$/.test(cell)) {
    throw new Error('Unrecognized Kubernetes compatibility list');
  }
  return cell.split(',').map(v => v.trim().replace(/^v/, ''));
}

export function ciliumMatrix(text) {
  if (!text.includes('| k8s Version')) throw new Error('Cilium compatibility table missing');
  const rows = text.split('\n').filter(row => /^\|\s*\d+\.\d+[ ,]*.*\|/.test(row));
  if (rows.length !== 1) throw new Error('Ambiguous Cilium compatibility table');
  return minorList(rows[0].split('|')[1].trim());
}

export function envoyMatrix(text, line) {
  const rows = text.split('\n').map(row => row.split('|').map(cell => cell.trim()));
  const header = rows.find(row => row[1] === 'Envoy Gateway version');
  const column = header?.indexOf('Kubernetes version');
  const matches = rows.filter(row => row[1] === `v${line}`);
  if (!column || column < 0 || matches.length !== 1) throw new Error('Released Envoy compatibility row missing');
  return minorList(matches[0][column]);
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

async function fetchText(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(30_000), cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
  return response.text();
}

export async function generate(base = 'https://upgrade-versions.lan.jetersen.dev') {
  const entries = await Promise.all(['node', 'cilium', 'envoy'].map(async id =>
    [id, JSON.parse(await fetchText(`${base}/badges/${id}?format=json`))]));
  const live = liveVersions(Object.fromEntries(entries));
  const urls = {
    cilium: `https://raw.githubusercontent.com/cilium/cilium/v${live.cilium.text}/Documentation/network/kubernetes/compatibility.rst`,
    envoy: `https://raw.githubusercontent.com/envoyproxy/gateway/v${live.envoy.text}/site/content/en/news/releases/matrix.md`,
  };
  const [cilium, envoy] = await Promise.all([fetchText(urls.cilium), fetchText(urls.envoy)]);
  return { live, urls, ...policy(live, ciliumMatrix(cilium), envoyMatrix(envoy, live.envoy.line)) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = await generate();
  console.log(JSON.stringify(result, null, 2));
  if (process.argv[2]) await writeFile(process.argv[2], JSON.stringify(result.packageRules));
}
