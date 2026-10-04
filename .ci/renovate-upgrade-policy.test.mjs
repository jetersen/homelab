import assert from 'node:assert/strict';
import test from 'node:test';
import { cachedMatrices, liveVersions, policy, version } from './renovate-upgrade-policy.mjs';

const badges = () => ({
  node: { id: 'node', result: 1000, labels: { os_image: 'Talos (v1.14.2)', kubelet_version: 'v1.36.5' } },
  cilium: { id: 'cilium', result: 1000, labels: { image_spec: `quay.io/cilium/cilium:v1.20.2@sha256:${'a'.repeat(64)}` } },
  flux: { id: 'flux', result: 1000, labels: { revision: `v2.9.6@sha256:${'a'.repeat(64)}` } },
  'cert-manager': { id: 'cert-manager', result: 1000, labels: { image_spec: 'quay.io/jetstack/cert-manager-controller:v1.21.2' } },
  envoy: { id: 'envoy', result: 1000, labels: { image_spec: 'mirror.gcr.io/envoyproxy/gateway:v1.9.2' } },
});
test('reads live version labels, including digest-pinned Cilium images', () => {
  assert.equal(liveVersions(badges(), 1050).cilium.text, '1.20.2');
  assert.equal(liveVersions(badges(), 1050).talos.text, '1.14.2');
});
test('fails closed on stale, missing, future, ambiguous, or malformed observations', () => {
  for (const result of [undefined, null, 800, 1100, NaN]) {
    const input = badges(); input.node.result = result;
    assert.throws(() => liveVersions(input, 1050));
  }
  const input = badges(); input.cilium.labels.image_spec = 'quay.io/cilium/cilium:latest';
  assert.throws(() => liveVersions(input, 1050));
  assert.throws(() => version('1.37.0-rc.1'));
});
test('intersection blocks unsupported minors and only live-minor patches auto-merge', () => {
  const result = policy(liveVersions(badges(), 1050), [['1.35', '1.36', '1.37'], ['1.35', '1.36']]);
  assert.deepEqual(result.supported, ['1.35', '1.36']);
  assert.equal(result.packageRules[2].allowedVersions, '>=1.36.5 <1.37.0');
  assert.equal(result.packageRules[2].automerge, false);
  assert.equal(result.packageRules[3].matchCurrentVersion, '>=1.36.0 <1.37.0');
  assert.deepEqual(result.packageRules[3].matchUpdateTypes, ['patch']);
});
test('permits only one reviewed minor step and rejects an unsupported running cluster', () => {
  const live = liveVersions(badges(), 1050);
  const result = policy(live, [['1.36', '1.37', '1.38'], ['1.36', '1.37', '1.38']], ['1.14', '1.15']);
  assert.equal(result.packageRules[2].allowedVersions, '>=1.36.5 <1.38.0');
  assert.equal(result.packageRules[0].allowedVersions, '>=1.14.2 <1.16.0');
  assert.throws(() => policy(live, [['1.36'], ['1.35']]));
});

const catalog = () => ({
  "schemaVersion": 3,
  "refreshedAt": "2026-10-01T00:00:00Z",
  "projects": {
    "cilium": {
      "source": "https://raw.githubusercontent.com/cilium/cilium/v1.20.2/Documentation/network/kubernetes/compatibility.rst",
      "versions": {
        "v1.20.2": {
          "sourceSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "supportedKubernetes": [
            "1.35",
            "1.36"
          ]
        }
      }
    },
    "envoy-gateway": {
      "source": "https://raw.githubusercontent.com/envoyproxy/gateway/v1.9.2/site/content/en/news/releases/matrix.md",
      "versions": {
        "v1.9.2": {
          "sourceSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "supportedKubernetes": [
            "1.35",
            "1.36"
          ]
        }
      }
    },
    "flux": {
      "source": "https://api.github.com/repos/fluxcd/flux2/releases/tags/v2.9.0",
      "versions": {
        "v2.9.6": {
          "source": "https://api.github.com/repos/fluxcd/flux2/releases/tags/v2.9.0",
          "sourceSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "supportedKubernetes": [
            "1.35",
            "1.36"
          ]
        }
      }
    },
    "cert-manager": {
      "source": "https://raw.githubusercontent.com/cert-manager/website/master/content/docs/releases/README.md",
      "versions": {
        "v1.21": {
          "sourceSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "supportedKubernetes": [
            "1.35",
            "1.36"
          ]
        }
      }
    },
    "talos": {
      "source": "https://raw.githubusercontent.com/siderolabs/docs/main/public/talos/v1.14/getting-started/support-matrix.mdx",
      "versions": {
        "v1.14": {
          "sourceSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "supportedKubernetes": [
            "1.35",
            "1.36"
          ]
        }
      }
    }
  }
});
test('reads exact release entries from the cache through a short upstream outage', () => {
  const cached = cachedMatrices(catalog(), liveVersions(badges(), 1050), Date.parse('2026-10-04'));
  assert.deepEqual(cached.envoy.supportedKubernetes, ['1.35', '1.36']);
});
test('allows a monthly refresh with outage tolerance but rejects caches older than 45 days', () => {
  const live = liveVersions(badges(), 1050), cached = catalog();
  const refreshed = Date.parse(cached.refreshedAt), day = 24 * 60 * 60 * 1000;
  for (const age of [31 * day, 45 * day]) {
    assert.deepEqual(cachedMatrices(cached, live, refreshed + age).envoy.supportedKubernetes, ['1.35', '1.36']);
  }
  assert.throws(() => cachedMatrices(cached, live, refreshed + 45 * day + 1));
});
test('rejects stale caches, missing releases, wrong provenance, and unavailable matrix rows', () => {
  const live = liveVersions(badges(), 1050), now = Date.parse('2026-10-04');
  assert.throws(() => cachedMatrices(catalog(), live, Date.parse('2026-11-16')));
  assert.throws(() => cachedMatrices(catalog(), live, Date.parse('2026-09-30')));
  for (const mutate of [
    c => { delete c.projects.cilium.versions['v1.20.2']; },
    c => { c.projects.cilium.source = 'https://example.com/latest'; },
    c => { c.projects.cilium.versions['v1.20.2'].supportedKubernetes = ['latest']; },
    c => { c.projects['envoy-gateway'].versions['v1.9.2'].unavailable = 'Released row missing'; },
  ]) {
    const value = catalog(); mutate(value);
    assert.throws(() => cachedMatrices(value, live, now));
  }
});

test('Talos minor proposals require cached support for the running Kubernetes minor', () => {
  const live = liveVersions(badges(), 1050);
  assert.equal(policy(live, [['1.36']]).packageRules[0].allowedVersions, '>=1.14.2 <1.15.0');
  assert.equal(policy(live, [['1.36']], ['1.14', '1.15']).packageRules[0].allowedVersions, '>=1.14.2 <1.16.0');
});
test('all five deployed projects constrain the Kubernetes intersection', () => {
  const live = liveVersions(badges(), 1050);
  const matrices = Array.from({ length: 5 }, () => ['1.36', '1.37']);
  for (let i = 0; i < matrices.length; i++) {
    const input = structuredClone(matrices); input[i] = ['1.36'];
    assert.equal(policy(live, input).packageRules[2].allowedVersions, '>=1.36.5 <1.37.0');
  }
});

test('rejects Enterprise Flux provenance and wrong release lines', () => {
  for (const mutate of [
    c => { c.schemaVersion = 2; },
    c => { c.projects.flux.source = 'https://raw.githubusercontent.com/controlplaneio-fluxcd/distribution/v2.9.6/releases/release-v2.9.md'; },
    c => { c.projects.flux.versions['v2.9.6'].source = 'https://api.github.com/repos/fluxcd/flux2/releases/tags/v2.10.0'; },
  ]) {
    const value = catalog(); mutate(value);
    assert.throws(() => cachedMatrices(value, liveVersions(badges(), 1050), Date.parse('2026-10-04')));
  }
});
test('uses minor compatibility without patch floors for current and next-minor versions', () => {
  const value = catalog(), live = liveVersions(badges(), 1050), now = Date.parse('2026-10-04');
  live.kubernetes = version('1.35.0');
  const matrices = cachedMatrices(value, live, now);
  const result = policy(live, Object.values(matrices).map(entry => entry.supportedKubernetes));
  assert.equal(result.packageRules[2].allowedVersions, '>=1.35.0 <1.37.0');
});
