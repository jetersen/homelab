import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const context = vm.createContext({});
vm.runInContext(readFileSync(new URL('./route-adapter.js', import.meta.url), 'utf8'), context);
const settings = { domain: 'example.com', ttl: 300, publicTarget: 'public.example.com', gateway: { namespace: 'network', name: 'envoy' } };
const prefix = 'public.external-dns.kubernetes.io/';
const conditions = (...types) => types.map(type => ({ type, status: 'True', observedGeneration: 1 }));
function fixture() {
  const parentRef = { name: 'envoy', namespace: 'network', sectionName: 'https' };
  return { items: [
    { kind: 'Gateway', metadata: { name: 'envoy', namespace: 'network', generation: 1 }, status: { conditions: conditions('Programmed'), addresses: [{ type: 'IPAddress', value: '192.0.2.20' }] } },
    { kind: 'HTTPRoute', metadata: { name: 'app', namespace: 'apps', generation: 1, annotations: { [prefix + 'enabled']: 'true' } }, spec: { parentRefs: [parentRef], hostnames: ['app.example.com'] }, status: { parents: [{ parentRef, controllerName: 'gateway.envoyproxy.io/gatewayclass-controller', conditions: conditions('Accepted', 'ResolvedRefs') }] } },
  ] };
}
const adapt = input => JSON.parse(JSON.stringify(context.publicRouteRecords(input, settings)));

test('public opt-in uses the public target and never Gateway LAN addresses', () => {
  assert.deepEqual(adapt(fixture()), [{ name: 'app.example.com', target: 'public.example.com', ttl: 300, proxied: true }]);
  const data = fixture(); delete data.items[1].metadata.annotations[prefix + 'enabled'];
  assert.deepEqual(adapt(data), []);
});
test('stale Gateway and route status stop reconciliation', () => {
  const data = fixture(); data.items[0].metadata.generation++;
  assert.throws(() => adapt(data), /not programmed/);
  const route = fixture(); route.items[1].metadata.generation++;
  assert.throws(() => adapt(route), /not ready/);
});
test('incomplete snapshots and LAN public names fail', () => {
  assert.throws(() => adapt({ items: [] }), /missing/);
  const data = fixture(); data.items[1].spec.hostnames = ['app.lan.example.com'];
  assert.throws(() => adapt(data), /cannot be published/);
});
test('TCPRoute requires an explicit hostname and remains unproxied', () => {
  const data = fixture(); const route = data.items[1]; route.kind = 'TCPRoute'; delete route.spec.hostnames;
  assert.throws(() => adapt(data), /no DNS hostname/);
  route.metadata.annotations[prefix + 'hostname'] = 'mqtt.example.com';
  assert.equal(adapt(data)[0].proxied, false);
});
test('conflicting routes fail instead of selecting an arbitrary target', () => {
  const data = fixture(); const other = structuredClone(data.items[1]);
  other.metadata.name = 'other'; other.metadata.annotations[prefix + 'target'] = 'other.example.com'; data.items.push(other);
  assert.throws(() => adapt(data), /Conflicting/);
});
test('IP targets and invalid TTLs are rejected', () => {
  const data = fixture(); data.items[1].metadata.annotations[prefix + 'target'] = '192.168.1.20';
  assert.throws(() => adapt(data), /not an IP/);
  const ttl = fixture(); ttl.items[1].metadata.annotations[prefix + 'ttl'] = '-1';
  assert.throws(() => adapt(ttl), /Invalid DNS TTL/);
});
test('DNS labels are validated and self-referential CNAMEs fail', () => {
  for (const name of ['-app.example.com', 'app-.example.com', 'app..example.com', `${'a'.repeat(64)}.example.com`, 'app.other.com']) {
    const data = fixture(); data.items[1].spec.hostnames = [name];
    assert.throws(() => adapt(data), /Invalid DNS hostname|outside the managed domain/);
  }
  const data = fixture(); data.items[1].metadata.annotations[prefix + 'target'] = 'app.example.com';
  assert.throws(() => adapt(data), /cannot point to itself/);
});
test('readiness must belong to the referenced Gateway group, port and controller', () => {
  const group = fixture(); group.items[1].spec.parentRefs[0].group = '';
  assert.throws(() => adapt(group), /does not attach/);
  const port = fixture(); port.items[1].status.parents[0].parentRef = { ...port.items[1].spec.parentRefs[0], port: 443 };
  assert.throws(() => adapt(port), /not ready/);
  const controller = fixture(); controller.items[1].status.parents[0].controllerName = 'other.example.com/controller';
  assert.throws(() => adapt(controller), /not ready/);
  const generation = fixture(); delete generation.items[0].metadata.generation;
  assert.throws(() => adapt(generation), /not programmed/);
});
test('two TCP listeners sharing a hostname produce one DNS record', () => {
  const data = fixture(); const route = data.items[1]; route.kind = 'TCPRoute'; delete route.spec.hostnames;
  route.metadata.annotations[prefix + 'hostname'] = 'mqtt.example.com';
  const websocket = structuredClone(route); websocket.metadata.name = 'websocket'; data.items.push(websocket);
  assert.deepEqual(adapt(data), [{ name: 'mqtt.example.com', target: 'public.example.com', ttl: 300, proxied: false }]);
});
test('Gateway targets, numeric DNS labels and per-route TTLs are supported', () => {
  const data = fixture(); data.items[0].metadata.annotations = { [prefix + 'target']: '123.public.example.com.' };
  data.items[1].metadata.annotations[prefix + 'ttl'] = '600';
  data.items[1].spec.hostnames = ['*.EXAMPLE.COM.'];
  assert.deepEqual(adapt(data), [{ name: '*.example.com', target: '123.public.example.com', ttl: 600, proxied: true }]);
});
