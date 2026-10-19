const assert = require("node:assert/strict");
const { test } = require("node:test");
process.env.RENOVATE_WORKER_TEST = "true";
const { configure } = require("./config.cjs");
const env = Object.fromEntries(
  [
    "RENOVATE_TOKEN",
    "REGISTRY_TOKEN",
    "DHI_REGISTRY_TOKEN",
    "GH_READ_APP_CLIENT_ID",
    "GH_READ_APP_PRIVATE_KEY",
  ].map((key) => [key, "fixture"]),
);

test("runtime gate rejection aborts configuration before token exchange", async () => {
  let authenticated = false;
  await assert.rejects(
    configure({
      env,
      gate: async () => {
        throw new Error("stale live metrics");
      },
      token: async () => {
        authenticated = true;
      },
    }),
    /stale live metrics/,
  );
  assert.equal(authenticated, false);
});

test("every invocation recomputes live rules and preserves commands and credentials", async () => {
  let gates = 0;
  const gate = async () => ({ packageRules: [{ description: `live-${++gates}` }] });
  const token = async () => "installation-token";
  const first = await configure({ env, gate, token });
  const second = await configure({ env, gate, token });
  assert.notDeepEqual(first.packageRules, second.packageRules);
  assert.equal(first.gitAuthor, "renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>");
  for (const command of [
    "bash .ci/renovate-dotnet-locks.sh",
    "nixos/packages/update-claude-code.sh 1.2.3",
    "nixos/packages/update-t3code.sh 1.2.3",
    'nix --extra-experimental-features "nix-command flakes" flake lock',
  ]) {
    assert.ok(first.allowedCommands.some((pattern) => new RegExp(pattern).test(command)));
  }
  assert.ok(first.allowedCommands.every((pattern) => !new RegExp(pattern).test("rm -rf /")));
  assert.equal(
    first.hostRules.find((rule) => rule.matchHost === "forgejo.jetersen.dev").password,
    env.REGISTRY_TOKEN,
  );
  assert.equal(
    first.hostRules.find((rule) => rule.matchHost === "dhi.io").password,
    env.DHI_REGISTRY_TOKEN,
  );
  assert.deepEqual(first.configFileNames, [".forgejo/renovate.json"]);
});

test("missing credentials abort instead of silently skipping private dependencies", async () => {
  await assert.rejects(
    configure({ env: {}, gate: async () => ({ packageRules: [] }) }),
    /Missing worker credential/,
  );
});
