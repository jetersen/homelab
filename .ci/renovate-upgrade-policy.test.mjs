import assert from 'node:assert/strict';
import test from 'node:test';
import { cachedMatrices, liveVersions, policy, version } from './renovate-upgrade-policy.mjs';

const badges = () => ({
  node: { id: 'node', result: 1000, labels: { os_image: 'Talos (v1.14.2)', kubelet_version: 'v1.36.5' } },
  cilium: { id: 'cilium', result: 1000, labels: { image_spec: `quay.io/cilium/cilium:v1.20.2@sha256:${'a'.repeat(64)}` } },
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
  const result = policy(liveVersions(badges(), 1050), ['1.35', '1.36', '1.37'], ['1.35', '1.36']);
  assert.deepEqual(result.supported, ['1.35', '1.36']);
  assert.equal(result.packageRules[2].allowedVersions, '>=1.36.5 <1.37.0');
  assert.equal(result.packageRules[2].automerge, false);
  assert.equal(result.packageRules[3].matchCurrentVersion, '>=1.36.0 <1.37.0');
  assert.deepEqual(result.packageRules[3].matchUpdateTypes, ['patch']);
});
test('permits only one reviewed minor step and rejects an unsupported running cluster', () => {
  const live = liveVersions(badges(), 1050);
  const result = policy(live, ['1.36', '1.37', '1.38'], ['1.36', '1.37', '1.38']);
  assert.equal(result.packageRules[2].allowedVersions, '>=1.36.5 <1.38.0');
  assert.equal(result.packageRules[0].allowedVersions, '>=1.14.2 <1.16.0');
  assert.throws(() => policy(live, ['1.36'], ['1.35']));
});

const catalog = () => ({
  schemaVersion: 1,
  refreshedAt: '2026-10-01T00:00:00Z',
  projects: {
    cilium: { 'v1.20.2': {
      source: 'https://raw.githubusercontent.com/cilium/cilium/v1.20.2/Documentation/network/kubernetes/compatibility.rst',
      sourceSha256: 'a'.repeat(64), supportedKubernetes: ['1.35', '1.36'],
    } },
    'envoy-gateway': { 'v1.9.2': {
      source: 'https://raw.githubusercontent.com/envoyproxy/gateway/v1.9.2/site/content/en/news/releases/matrix.md',
      sourceSha256: 'b'.repeat(64), supportedKubernetes: ['1.35', '1.36'],
    } },
  },
});
test('reads exact release entries from the cache through a short upstream outage', () => {
  const cached = cachedMatrices(catalog(), liveVersions(badges(), 1050), Date.parse('2026-10-04'));
  assert.deepEqual(cached.envoy.supportedKubernetes, ['1.35', '1.36']);
});
test('rejects stale caches, missing releases, wrong provenance, and unavailable matrix rows', () => {
  const live = liveVersions(badges(), 1050), now = Date.parse('2026-10-04');
  assert.throws(() => cachedMatrices(catalog(), live, Date.parse('2026-10-09')));
  assert.throws(() => cachedMatrices(catalog(), live, Date.parse('2026-09-30')));
  for (const mutate of [
    c => { delete c.projects.cilium['v1.20.2']; },
    c => { c.projects.cilium['v1.20.2'].source = 'https://example.com/latest'; },
    c => { c.projects.cilium['v1.20.2'].supportedKubernetes = ['latest']; },
    c => { c.projects['envoy-gateway']['v1.9.2'].unavailable = 'Released row missing'; },
  ]) {
    const value = catalog(); mutate(value);
    assert.throws(() => cachedMatrices(value, live, now));
  }
});
