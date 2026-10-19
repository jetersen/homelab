const { createPrivateKey, sign } = require("node:crypto");

async function githubToken(env, request = fetch) {
  const now = Math.floor(Date.now() / 1000);
  const encode = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const payload = `${encode({ alg: "RS256", typ: "JWT" })}.${encode({ iat: now - 60, exp: now + 540, iss: env.GH_READ_APP_CLIENT_ID })}`;
  const jwt = `${payload}.${sign("RSA-SHA256", Buffer.from(payload), createPrivateKey(env.GH_READ_APP_PRIVATE_KEY)).toString("base64url")}`;
  async function api(path, options = {}) {
    const response = await request(`https://api.github.com${path}`, {
      ...options,
      signal: AbortSignal.timeout(30_000),
      headers: { Authorization: `Bearer ${jwt}`, Accept: "application/vnd.github+json" },
    });
    if (!response.ok) {
      throw new Error(`GitHub App request failed: HTTP ${response.status}`);
    }
    return response.json();
  }
  const installation = await api("/users/jetersen/installation");
  const result = await api(`/app/installations/${installation.id}/access_tokens`, {
    method: "POST",
    body: JSON.stringify({ permissions: { metadata: "read" } }),
  });
  if (!result.token) {
    throw new Error("GitHub App returned no installation token");
  }
  return result.token;
}

async function configure({ env = process.env, gate, token = githubToken } = {}) {
  for (const key of [
    "RENOVATE_TOKEN",
    "REGISTRY_TOKEN",
    "DHI_REGISTRY_TOKEN",
    "GH_READ_APP_CLIENT_ID",
    "GH_READ_APP_PRIVATE_KEY",
  ]) {
    if (!env[key]) {
      throw new Error(`Missing worker credential: ${key}`);
    }
  }
  const policy = gate ?? (await import("./renovate-upgrade-policy.mjs")).generate;
  // A rejected config is fatal with an explicit RENOVATE_CONFIG_FILE. Never fall back to ungated rules.
  const { packageRules } = await policy();
  const github = await token(env);
  console.log("Live upgrade compatibility gate passed");
  return {
    onboarding: false,
    configFileNames: [".forgejo/renovate.json"],
    gitAuthor: "renovate[bot] <29139614+renovate[bot]@users.noreply.github.com>",
    allowedCommands: [
      "^bash \\.ci/renovate-dotnet-locks\\.sh$",
      "^nixos/packages/update-(claude-code|t3code)[.]sh [0-9]+\\.[0-9]+\\.[0-9]+$",
      '^nix --extra-experimental-features "nix-command flakes" flake lock$',
    ],
    packageRules,
    hostRules: [
      { hostType: "github", matchHost: "github.com", token: github },
      {
        hostType: "docker",
        matchHost: "forgejo.jetersen.dev",
        username: "jetersen",
        password: env.REGISTRY_TOKEN,
      },
      {
        hostType: "docker",
        matchHost: "dhi.io",
        username: "jetersen",
        password: env.DHI_REGISTRY_TOKEN,
      },
    ],
    cacheDir: "/cache/renovate",
    // Export the metadata token for custom release-manifest commands as well.
    processEnv: { RENOVATE_GITHUB_COM_TOKEN: github },
  };
}

module.exports = process.env.RENOVATE_WORKER_TEST ? { configure, githubToken } : configure();
