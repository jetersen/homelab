import assert from 'node:assert/strict';
import test from 'node:test';
import { ciliumMatrix, envoyMatrix, liveVersions, policy, version } from './renovate-upgrade-policy.mjs';

const badges = () => ({
  node: { id: 'node', result: 1000, labels: { os_image: 'Talos (v1.14.2)', kubelet_version: 'v1.36.5' } },
  cilium: { id: 'cilium', result: 1000, labels: { image_spec: `quay.io/cilium/cilium:v1.20.2@sha256:${'a'.repeat(64)}` } },
  envoy: { id: 'envoy', result: 1000, labels: { image_spec: 'mirror.gcr.io/envoyproxy/gateway:v1.9.2' } },
});
const matrix = `| Envoy Gateway version | Envoy Proxy version | Rate Limit version | Gateway API version | Kubernetes version | End of Life |
| latest | dev | main | v1.7 | v1.36, v1.37 | n/a |
| v1.9 | envoy | rate | v1.6 | v1.33, v1.34, v1.35, v1.36 | date |`;

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
test('uses the exact released Envoy row, never latest', () => {
  assert.deepEqual(envoyMatrix(matrix, '1.9'), ['1.33', '1.34', '1.35', '1.36']);
  assert.throws(() => envoyMatrix(matrix, '1.10'));
  assert.throws(() => envoyMatrix(matrix.replace('v1.33, v1.34, v1.35, v1.36', 'v1.33-v1.36'), '1.9'));
});
test('parses only the Cilium tested Kubernetes version list and rejects changed formats', () => {
  assert.deepEqual(ciliumMatrix('| k8s Version | API |\n| 1.34, 1.35, 1.36 | API |'), ['1.34', '1.35', '1.36']);
  assert.throws(() => ciliumMatrix('| 1.36 | API |'));
  assert.throws(() => ciliumMatrix('| k8s Version | API |\n| 1.36 | API |\n| 1.37 | API |'));
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
