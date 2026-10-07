import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

const secrets = {
  CF_API_TOKEN: "test-cloudflare",
  TECHNITIUM_TSIG_SECRET: "test-technitium",
  UNIFI_API_KEY: "test-unifi",
};

function credentials(env) {
  return spawnSync(process.execPath, ["infrastructure/dns/creds.mjs"], {
    env,
    encoding: "utf8",
  });
}

test("default and explicit all-provider credentials include all three providers", () => {
  for (const selection of [{}, { DNS_PROVIDER: "all" }]) {
    const result = credentials({ ...secrets, ...selection });
    assert.equal(result.status, 0, result.stderr);
    const parsed = JSON.parse(result.stdout);
    assert.deepEqual(Object.keys(parsed).sort(), ["cloudflare", "technitium", "unifi"]);
    assert.equal(parsed.cloudflare.apitoken, secrets.CF_API_TOKEN);
    assert.equal(parsed.unifi.api_key, secrets.UNIFI_API_KEY);
    assert.equal(parsed.unifi.skip_tls_verify, "false");
    assert.equal(
      parsed.technitium["transfer-key"],
      `hmac-sha256:external-dns-technitium:${secrets.TECHNITIUM_TSIG_SECRET}`,
    );
    assert.equal(parsed.technitium["update-key"], parsed.technitium["transfer-key"]);
    assert.equal(result.stderr, "");
  }
});

test("a selected provider requires only its own secret", () => {
  for (const [provider, name] of [
    ["cloudflare", "CF_API_TOKEN"],
    ["technitium", "TECHNITIUM_TSIG_SECRET"],
    ["unifi", "UNIFI_API_KEY"],
  ]) {
    const result = credentials({ DNS_PROVIDER: provider, [name]: secrets[name] });
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(Object.keys(JSON.parse(result.stdout)), [provider]);
  }
});

test("missing secrets fail without emitting partial credentials or secret values", () => {
  for (const name of Object.keys(secrets)) {
    const env = { ...secrets };
    delete env[name];
    const result = credentials(env);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, "");
    assert.ok(result.stderr.includes(`Missing ${name}`));
    for (const value of Object.values(secrets)) {
      assert.ok(!result.stderr.includes(value));
    }
  }
});

test("unknown providers fail without emitting credentials", () => {
  const result = credentials({ ...secrets, DNS_PROVIDER: "unknown" });
  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, "");
  assert.ok(result.stderr.includes("Unknown DNS_PROVIDER"));
});
