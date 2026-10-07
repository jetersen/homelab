import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import http from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { promisify } from 'node:util';

const run = promisify(execFile);
const spec = {
  openapi: '3.1.0',
  info: { title: 'UniFi Network API', version: '10.6.106' },
  paths: { '/v1/info': { get: { description: 'x'.repeat(150_000) } } },
};

test('controller OpenAPI discovery', async (t) => {
  const root = await mkdtemp(join(tmpdir(), 'unifi-request-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await copyFile(new URL('./request.mjs', import.meta.url), join(root, 'request.mjs'));
  const stub = join(root, 'node_modules/varlock');
  await mkdir(stub, { recursive: true });
  await writeFile(join(stub, 'package.json'), JSON.stringify({
    type: 'module', exports: { './auto-load': './load.mjs', './env': './env.mjs' },
  }));
  await writeFile(join(stub, 'load.mjs'), '');
  await writeFile(join(stub, 'env.mjs'),
    "export const ENV = { UNIFI_HOST: process.env.UNIFI_TEST_ORIGIN, UNIFI_TOKEN: 'fixture-token' };");

  const cases = [
    { name: 'proxied document, including large output', base: '/proxy/network/integration', body: spec },
    { name: 'direct application document', base: '/integration', body: spec },
    { name: 'version mismatch', body: { ...spec, info: { ...spec.info, version: '10.6.101' } }, fail: true },
    { name: 'wrong application', body: { ...spec, info: { ...spec.info, title: 'UniFi Protect API' } }, fail: true },
    { name: 'empty paths', body: { ...spec, paths: {} }, fail: true },
    { name: 'invalid OpenAPI', body: { ...spec, openapi: undefined }, fail: true },
    { name: 'HTML login response', body: '<html>Login</html>', fail: true },
    { name: 'null JSON', body: null, fail: true },
    { name: 'unavailable documentation', status: 404, body: {}, fail: true },
    { name: 'write guard retained', args: ['POST', '/v1/example'], fail: true, noRequests: true },
  ];

  for (const scenario of cases) {
    await t.test(scenario.name, async (t) => {
      const requests = [];
      const base = scenario.base ?? '/proxy/network/integration';
      const docs = base.replace(/\/integration$/, '/api-docs/integration.json');
      const server = http.createServer((req, res) => {
        requests.push({ method: req.method, path: req.url, key: req.headers['x-api-key'] });
        if (req.url === `${base}/v1/info`) {
          res.end(JSON.stringify({ applicationVersion: spec.info.version }));
        } else if (req.url === docs) {
          res.writeHead(scenario.status ?? 200);
          res.end(typeof scenario.body === 'string' ? scenario.body : JSON.stringify(scenario.body));
        } else {
          res.writeHead(404).end('{}');
        }
      });
      await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
      t.after(() => new Promise((resolve) => server.close(resolve)));
      const options = { env: { UNIFI_TEST_ORIGIN: `http://127.0.0.1:${server.address().port}` } };
      const args = [join(root, 'request.mjs'), ...(scenario.args ?? ['--openapi'])];
      if (scenario.fail) {
        await assert.rejects(run(process.execPath, args, options), (error) => {
          assert.equal(error.stdout, '');
          assert.ok(error.code > 0);
          return true;
        });
      } else {
        const { stdout } = await run(process.execPath, args, options);
        assert.deepEqual(JSON.parse(stdout), spec);
        assert.equal(requests.at(-1).path, docs);
      }
      assert.ok(requests.every((req) => req.method === 'GET' && req.key === 'fixture-token'));
      if (scenario.noRequests) assert.equal(requests.length, 0);
    });
  }
});
