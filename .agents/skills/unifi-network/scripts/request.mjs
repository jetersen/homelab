#!/usr/bin/env node
import http from 'node:http';
import https from 'node:https';

function usage(message) {
  if (message) process.stderr.write(`${message}\n\n`);
  process.stderr.write(`Usage:
  node request.mjs METHOD /v1/path
  node request.mjs --write METHOD /v1/path < body.json

GET and HEAD are read-only. POST, PATCH, PUT, and DELETE require --write.
Send JSON request bodies on stdin; never pass secrets as arguments.
`);
  process.exit(2);
}

const args = process.argv.slice(2);
const allowWrite = args[0] === '--write';
if (allowWrite) args.shift();
if (args.length !== 2) usage();

const [rawMethod, path] = args;
const method = rawMethod.toUpperCase();
const readMethods = new Set(['GET', 'HEAD']);
const writeMethods = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);

if (!readMethods.has(method) && !writeMethods.has(method)) {
  usage(`Unsupported HTTP method: ${method}`);
}
if (writeMethods.has(method) && !allowWrite) {
  usage(`Refusing ${method} without --write.`);
}
if (path !== '/v1' && !path.startsWith('/v1/')) {
  usage('Path must begin with /v1.');
}

await import('varlock/auto-load');
const { ENV } = await import('varlock/env');

const host = String(ENV.UNIFI_HOST).replace(/\/$/, '');
const token = ENV.UNIFI_TOKEN;
if (!host || host === 'undefined' || !token) {
  throw new Error('UNIFI_HOST and UNIFI_TOKEN must resolve through Varlock.');
}

function send({ url, method = 'GET', tls = {}, body }) {
  return new Promise((resolve, reject) => {
    const parsedUrl = new URL(url);
    const client = parsedUrl.protocol === 'https:' ? https : http;
    const headers = { 'X-API-Key': token };

    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = String(body.length);
    }

    const request = client.request(parsedUrl, {
      method,
      headers,
      ...tls,
    }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => resolve({
        status: response.statusCode ?? 0,
        body: Buffer.concat(chunks),
      }));
    });

    request.setTimeout(30_000, () => request.destroy(new Error('UniFi API request timed out.')));
    request.on('error', reject);
    if (body !== undefined) request.write(body);
    request.end();
  });
}

async function discoverApi() {
  const bases = ['/proxy/network/integration', '/integration'];
  const tlsModes = new URL(host).protocol === 'https:'
    ? [{ name: 'verified', options: { rejectUnauthorized: true } }]
    : [{ name: 'not-applicable', options: {} }];

  for (const base of bases) {
    for (const tls of tlsModes) {
      try {
        const response = await send({
          url: `${host}${base}/v1/info`,
          tls: tls.options,
        });
        if (response.status < 200 || response.status >= 300) continue;

        const info = JSON.parse(response.body.toString('utf8'));
        if (typeof info.applicationVersion === 'string' && info.applicationVersion.length > 0) {
          return { base, version: info.applicationVersion, tls };
        }
      } catch {
        // Try the next TLS mode or supported API base.
      }
    }
  }

  throw new Error('Unable to discover an authenticated UniFi integration API.');
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks);
}

const api = await discoverApi();
process.stderr.write(`unifi-api: version=${api.version} base=${api.base} tls=${api.tls.name}\n`);

const sendsBody = ['POST', 'PATCH', 'PUT'].includes(method);
const body = sendsBody ? await readStdin() : undefined;
if (sendsBody && body.length === 0) usage(`${method} requires a JSON body on stdin.`);

const response = await send({
  url: `${host}${api.base}${path}`,
  method,
  tls: api.tls.options,
  body,
});

process.stdout.write(response.body);
if (response.body.length > 0 && response.body.at(-1) !== 10) process.stdout.write('\n');
if (response.status < 200 || response.status >= 300) {
  process.stderr.write(`unifi-api: HTTP ${response.status}\n`);
  process.exitCode = 1;
}
