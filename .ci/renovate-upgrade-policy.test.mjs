import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { runInNewContext } from "node:vm";
import {
  arrStableRule,
  cachedMatrices,
  completeCiliumPatchMatrix,
  fluxUpgradePolicy,
  liveVersions,
  policy,
  version,
} from "./renovate-upgrade-policy.mjs";

const badges = () => ({
  node: {
    id: "node",
    result: 1000,
    labels: { os_image: "Talos (v1.14.2)", kubelet_version: "v1.36.5" },
  },
  cilium: {
    id: "cilium",
    result: 1000,
    labels: { image_spec: `quay.io/cilium/cilium:v1.20.2@sha256:${"a".repeat(64)}` },
  },
  flux: { id: "flux", result: 1000, labels: { revision: `v2.9.6@sha256:${"a".repeat(64)}` } },
  "flux-operator": {
    id: "flux-operator",
    result: 1000,
    labels: { image_spec: "ghcr.io/controlplaneio-fluxcd/flux-operator:v0.61.0" },
  },
  "cert-manager": {
    id: "cert-manager",
    result: 1000,
    labels: { image_spec: "quay.io/jetstack/cert-manager-controller:v1.21.2" },
  },
  envoy: {
    id: "envoy",
    result: 1000,
    labels: { image_spec: "mirror.gcr.io/envoyproxy/gateway:v1.9.2" },
  },
});
test("reads live version labels, including digest-pinned Cilium images", () => {
  assert.equal(liveVersions(badges(), 1050).cilium.text, "1.20.2");
  assert.equal(liveVersions(badges(), 1050).talos.text, "1.14.2");
});
test("fails closed on stale, missing, future, ambiguous, or malformed observations", () => {
  for (const result of [undefined, null, 800, 1100, NaN]) {
    const input = badges();
    input.node.result = result;
    assert.throws(() => liveVersions(input, 1050));
  }
  const input = badges();
  input.cilium.labels.image_spec = "quay.io/cilium/cilium:latest";
  assert.throws(() => liveVersions(input, 1050));
  assert.throws(() => version("1.37.0-rc.1"));
});
test("intersection blocks unsupported minors and only live-minor patches auto-merge", () => {
  const result = policy(liveVersions(badges(), 1050), [
    ["1.35", "1.36", "1.37"],
    ["1.35", "1.36"],
  ]);
  assert.deepEqual(result.supported, ["1.35", "1.36"]);
  assert.equal(result.packageRules[2].allowedVersions, ">=1.36.5 <1.37.0");
  assert.equal(result.packageRules[2].automerge, false);
  assert.equal(result.packageRules[3].matchCurrentVersion, ">=1.36.0 <1.37.0");
  assert.deepEqual(result.packageRules[3].matchUpdateTypes, ["patch"]);
});
test("permits only one reviewed minor step and rejects an unsupported running cluster", () => {
  const live = liveVersions(badges(), 1050);
  const result = policy(
    live,
    [
      ["1.36", "1.37", "1.38"],
      ["1.36", "1.37", "1.38"],
    ],
    ["1.14", "1.15"],
  );
  assert.equal(result.packageRules[2].allowedVersions, ">=1.36.5 <1.38.0");
  assert.equal(result.packageRules[0].allowedVersions, ">=1.14.2 <1.16.0");
  assert.throws(() => policy(live, [["1.36"], ["1.35"]]));
});

const catalog = () => ({
  schemaVersion: 3,
  refreshedAt: "2026-10-01T00:00:00Z",
  projects: {
    cilium: {
      source:
        "https://raw.githubusercontent.com/cilium/cilium/v1.20.2/Documentation/network/kubernetes/compatibility.rst",
      versions: {
        "v1.20.2": {
          sourceSha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          supportedKubernetes: ["1.35", "1.36"],
        },
      },
    },
    "envoy-gateway": {
      source:
        "https://raw.githubusercontent.com/envoyproxy/gateway/v1.9.2/site/content/en/news/releases/matrix.md",
      versions: {
        "v1.9.2": {
          sourceSha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          supportedKubernetes: ["1.35", "1.36"],
        },
      },
    },
    flux: {
      source: "https://api.github.com/repos/fluxcd/flux2/releases/tags/v2.9.0",
      versions: {
        "v2.9.6": {
          source: "https://api.github.com/repos/fluxcd/flux2/releases/tags/v2.9.0",
          sourceSha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          supportedKubernetes: ["1.35", "1.36"],
        },
      },
    },
    "cert-manager": {
      source:
        "https://raw.githubusercontent.com/cert-manager/website/master/content/docs/releases/README.md",
      versions: {
        "v1.21": {
          sourceSha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          supportedKubernetes: ["1.35", "1.36"],
        },
      },
    },
    talos: {
      source:
        "https://raw.githubusercontent.com/siderolabs/docs/main/public/talos/v1.14/getting-started/support-matrix.mdx",
      versions: {
        "v1.14": {
          sourceSha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          supportedKubernetes: ["1.35", "1.36"],
        },
      },
    },
  },
});
test("reads exact release entries from the cache through a short upstream outage", () => {
  const cached = cachedMatrices(catalog(), liveVersions(badges(), 1050), Date.parse("2026-10-04"));
  assert.deepEqual(cached.envoy.supportedKubernetes, ["1.35", "1.36"]);
});
test("allows a monthly refresh with outage tolerance but rejects caches older than 45 days", () => {
  const live = liveVersions(badges(), 1050),
    cached = catalog();
  const refreshed = Date.parse(cached.refreshedAt),
    day = 24 * 60 * 60 * 1000;
  for (const age of [31 * day, 45 * day]) {
    assert.deepEqual(cachedMatrices(cached, live, refreshed + age).envoy.supportedKubernetes, [
      "1.35",
      "1.36",
    ]);
  }
  assert.throws(() => cachedMatrices(cached, live, refreshed + 45 * day + 1));
});
test("rejects stale caches, missing releases, wrong provenance, and unavailable matrix rows", () => {
  const live = liveVersions(badges(), 1050),
    now = Date.parse("2026-10-04");
  assert.throws(() => cachedMatrices(catalog(), live, Date.parse("2026-11-16")));
  assert.throws(() => cachedMatrices(catalog(), live, Date.parse("2026-09-30")));
  for (const mutate of [
    (c) => {
      delete c.projects.cilium.versions["v1.20.2"];
    },
    (c) => {
      c.projects.cilium.source = "https://example.com/latest";
    },
    (c) => {
      c.projects.cilium.versions["v1.20.2"].supportedKubernetes = ["latest"];
    },
    (c) => {
      c.projects["envoy-gateway"].versions["v1.9.2"].unavailable = "Released row missing";
    },
  ]) {
    const value = catalog();
    mutate(value);
    assert.throws(() => cachedMatrices(value, live, now));
  }
});

test("Talos minor proposals require cached support for the running Kubernetes minor", () => {
  const live = liveVersions(badges(), 1050);
  assert.equal(policy(live, [["1.36"]]).packageRules[0].allowedVersions, ">=1.14.2 <1.15.0");
  assert.equal(
    policy(live, [["1.36"]], ["1.14", "1.15"]).packageRules[0].allowedVersions,
    ">=1.14.2 <1.16.0",
  );
});
test("all five deployed projects constrain the Kubernetes intersection", () => {
  const live = liveVersions(badges(), 1050);
  const matrices = Array.from({ length: 5 }, () => ["1.36", "1.37"]);
  for (let i = 0; i < matrices.length; i++) {
    const input = structuredClone(matrices);
    input[i] = ["1.36"];
    assert.equal(policy(live, input).packageRules[2].allowedVersions, ">=1.36.5 <1.37.0");
  }
});

test("rejects Enterprise Flux provenance and wrong release lines", () => {
  for (const mutate of [
    (c) => {
      c.schemaVersion = 2;
    },
    (c) => {
      c.projects.flux.source =
        "https://raw.githubusercontent.com/controlplaneio-fluxcd/distribution/v2.9.6/releases/release-v2.9.md";
    },
    (c) => {
      c.projects.flux.versions["v2.9.6"].source =
        "https://api.github.com/repos/fluxcd/flux2/releases/tags/v2.10.0";
    },
  ]) {
    const value = catalog();
    mutate(value);
    assert.throws(() =>
      cachedMatrices(value, liveVersions(badges(), 1050), Date.parse("2026-10-04")),
    );
  }
});
test("uses minor compatibility without patch floors for current and next-minor versions", () => {
  const value = catalog(),
    live = liveVersions(badges(), 1050),
    now = Date.parse("2026-10-04");
  live.kubernetes = version("1.35.0");
  const matrices = cachedMatrices(value, live, now);
  const result = policy(
    live,
    Object.values(matrices).map((entry) => entry.supportedKubernetes),
  );
  assert.equal(result.packageRules[2].allowedVersions, ">=1.35.0 <1.37.0");
});

for (const project of ["sonarr", "radarr", "prowlarr"]) {
  test(`${project} allows only the latest stable upstream release despite numeric beta image tags`, () => {
    const rule = arrStableRule(project, {
      tag_name: "v4.0.20.3014",
      prerelease: false,
      draft: false,
    });
    assert.deepEqual(rule.matchPackageNames, [`ghcr.io/home-operations/${project}`]);
    const pattern = new RegExp(rule.allowedVersions.slice(1, -1));
    assert.ok(pattern.test("4.0.20.3014"));
    for (const tag of ["5.0.0.2635", "4.0.21.1", "4x0x20x3014", "4.0.20.3014-beta"]) {
      assert.equal(pattern.test(tag), false);
    }
    // A future stable major is allowed automatically, while migration review remains separate.
    assert.match(
      arrStableRule(project, { tag_name: "v5.0.1.3000", prerelease: false, draft: false })
        .allowedVersions,
      /5/,
    );
    for (const release of [
      null,
      {},
      { tag_name: "v5.0.0.2635", prerelease: true, draft: false },
      { tag_name: "v4.0.20.3014", prerelease: false, draft: true },
      { tag_name: "v4.0.20.3014-beta", prerelease: false, draft: false },
    ]) {
      assert.throws(() => arrStableRule(project, release));
    }
  });
}

test("missing Cilium patches require the exact released matrix to match the cached document", async () => {
  const text = "released compatibility document";
  const cache = {
    projects: {
      cilium: {
        source:
          "https://raw.githubusercontent.com/cilium/cilium/v1.20.2/Documentation/network/kubernetes/compatibility.rst",
        versions: {
          "v1.20.2": {
            sourceSha256: createHash("sha256").update(text).digest("hex"),
            supportedKubernetes: ["1.35", "1.36"],
          },
        },
      },
    },
  };
  const live = { cilium: version("1.20.3") };
  const result = await completeCiliumPatchMatrix(cache, live, async (url) => {
    assert.equal(
      url,
      "https://raw.githubusercontent.com/cilium/cilium/v1.20.3/Documentation/network/kubernetes/compatibility.rst",
    );
    return text;
  });
  assert.deepEqual(result.projects.cilium.versions["v1.20.3"].supportedKubernetes, [
    "1.35",
    "1.36",
  ]);
  assert.equal(cache.projects.cilium.versions["v1.20.3"], undefined);
  await assert.rejects(completeCiliumPatchMatrix(cache, live, async () => "changed matrix"));
  await assert.rejects(
    completeCiliumPatchMatrix(cache, live, async () => {
      throw new Error("unavailable");
    }),
  );
  await assert.rejects(
    completeCiliumPatchMatrix(cache, { cilium: version("1.21.0") }, async () => {
      assert.fail("must not fetch an unreviewed minor");
    }),
  );
  assert.equal(
    await completeCiliumPatchMatrix(result, live, async () => {
      assert.fail("existing entries must still use normal cache validation");
    }),
    result,
  );
});

function fluxCatalog(operator = "0.61.0", supportedFlux = ["2.9"]) {
  const value = catalog();
  value.projects["flux-operator"] = {
    versions: {
      [`v${operator}`]: {
        source: `https://api.github.com/repos/controlplaneio-fluxcd/flux-operator/contents/config/data/flux?ref=v${operator}`,
        sourceSha256: "a".repeat(64),
        supportedFlux,
      },
    },
  };
  value.projects.flux.versions["v2.10.0"] = {
    source: "https://api.github.com/repos/fluxcd/flux2/releases/tags/v2.10.0",
    sourceSha256: "b".repeat(64),
    supportedKubernetes: ["1.35", "1.36", "1.37"],
  };
  return value;
}

test("Flux 2.10 stays blocked on operator 0.61 even when operator 0.62 is published", () => {
  const value = fluxCatalog();
  value.projects["flux-operator"].versions["v0.62.0"] = fluxCatalog("0.62.0", [
    "2.9",
    "2.10",
  ]).projects["flux-operator"].versions["v0.62.0"];
  const result = fluxUpgradePolicy(value, liveVersions(badges(), 1050));
  assert.equal(result.packageRules[0].allowedVersions, ">=2.9.6 <2.10.0");
  assert.equal(result.packageRules[0].automerge, false);
  assert.equal(result.packageRules[1].automerge, true);
  assert.deepEqual(result.packageRules[1].matchUpdateTypes, ["patch"]);
  assert.equal(result.packageRules[1].matchCurrentVersion, ">=2.9.0 <2.10.0");
});

test("deployed operator 0.62 enables one compatible Flux minor step", () => {
  const live = liveVersions(badges(), 1050);
  live["flux-operator"] = version("0.62.0");
  const value = fluxCatalog("0.62.0", ["2.9", "2.10", "2.11"]);
  const rules = fluxUpgradePolicy(value, live).packageRules;
  assert.equal(rules[0].allowedVersions, ">=2.9.6 <2.11.0");
  assert.equal(rules[0].automerge, false);
  live.kubernetes = version("1.34.9");
  assert.equal(fluxUpgradePolicy(value, live).packageRules[0].allowedVersions, ">=2.9.6 <2.10.0");
});

test("missing or invalid future Flux matrices block the candidate without blocking operator upgrades", () => {
  const live = liveVersions(badges(), 1050);
  live["flux-operator"] = version("0.62.0");
  for (const mutate of [
    (c) => {
      delete c.projects.flux.versions["v2.10.0"];
    },
    (c) => {
      c.projects.flux.versions["v2.10.0"].source = "https://example.com/matrix";
    },
    (c) => {
      c.projects.flux.versions["v2.10.0"].sourceSha256 = "invalid";
    },
    (c) => {
      c.projects.flux.versions["v2.10.0"].unavailable = "No released table";
    },
    (c) => {
      c.projects.flux.versions["v2.10.0"].supportedKubernetes = ["latest"];
    },
  ]) {
    const value = fluxCatalog("0.62.0", ["2.9", "2.10"]);
    mutate(value);
    assert.equal(fluxUpgradePolicy(value, live).packageRules[0].allowedVersions, ">=2.9.6 <2.10.0");
  }
});

test("missing or untrusted deployed operator matrices fail closed", () => {
  const live = liveVersions(badges(), 1050);
  for (const mutate of [
    (c) => {
      delete c.projects["flux-operator"];
    },
    (c) => {
      c.projects["flux-operator"].versions["v0.61.0"].source = "https://example.com/latest";
    },
    (c) => {
      c.projects["flux-operator"].versions["v0.61.0"].sourceSha256 = "invalid";
    },
    (c) => {
      c.projects["flux-operator"].versions["v0.61.0"].supportedFlux = ["2.10"];
    },
    (c) => {
      c.projects["flux-operator"].versions["v0.61.0"].supportedFlux = ["latest"];
    },
    (c) => {
      c.projects["flux-operator"].versions["v0.61.0"].supportedFlux = ["2.9", "2.9"];
    },
  ]) {
    const value = fluxCatalog();
    mutate(value);
    assert.throws(() => fluxUpgradePolicy(value, live));
  }
});

test("live operator observations require freshness, readiness, and a stable image version", () => {
  for (const mutate of [
    (b) => {
      delete b["flux-operator"];
    },
    (b) => {
      b["flux-operator"].result = 800;
    },
    (b) => {
      b["flux-operator"].labels.image_spec = "ghcr.io/controlplaneio-fluxcd/flux-operator:latest";
    },
  ]) {
    const input = badges();
    mutate(input);
    assert.throws(() => liveVersions(input, 1050));
  }
});

test("operator proposals retain the running Flux minor and reject unverified releases", () => {
  const value = fluxCatalog();
  Object.assign(value.projects["flux-operator"].versions, {
    ...fluxCatalog("0.62.0", ["2.9", "2.10"]).projects["flux-operator"].versions,
    ...fluxCatalog("0.63.0", ["2.10", "2.11"]).projects["flux-operator"].versions,
  });
  value.projects["flux-operator"].versions["v0.62.1"] = {
    ...value.projects["flux-operator"].versions["v0.62.0"],
  };
  const rule = fluxUpgradePolicy(value, liveVersions(badges(), 1050)).packageRules[2];
  const pattern = new RegExp(rule.allowedVersions.slice(1, -1));
  for (const tag of ["0.61.0", "0.62.0", "v0.62.0"]) {
    assert.ok(pattern.test(tag));
  }
  for (const tag of ["0.62.1", "0.63.0", "0.64.0", "0.62.0-rc.1", "0x62x0"]) {
    assert.equal(pattern.test(tag), false);
  }
});

test("Flux grouping covers charts and distribution while minor distribution updates require review", async () => {
  const preset = async (name) =>
    runInNewContext(
      `(${await readFile(new URL(`../.renovate/${name}.json5`, import.meta.url), "utf8")})`,
    );
  const groups = await preset("groups");
  const group = groups.packageRules.find((rule) => rule.groupName === "Flux");
  for (const packageName of [
    "ghcr.io/controlplaneio-fluxcd/charts/flux-operator",
    "ghcr.io/controlplaneio-fluxcd/charts/flux-instance",
    "ghcr.io/controlplaneio-fluxcd/charts/flux-operator-mcp",
    "controlplaneio-fluxcd/distribution",
  ]) {
    assert.ok(
      group.matchPackageNames.some((match) =>
        match.startsWith("/")
          ? new RegExp(match.slice(1, -1)).test(packageName)
          : match === packageName,
      ),
    );
  }
  assert.ok(group.matchDatasources.includes("docker"));
  assert.ok(group.matchDatasources.includes("github-releases"));
  const autoMerge = await preset("autoMerge");
  const minor = autoMerge.packageRules.find((rule) => rule.matchUpdateTypes?.includes("minor"));
  assert.ok(minor.matchPackageNames.includes("controlplaneio-fluxcd/distribution"));
  assert.equal(minor.automerge, false);
  assert.equal(minor.dependencyDashboardApproval, true);
  assert.ok(
    autoMerge.packageRules.some(
      (rule) =>
        rule.matchPackageNames.includes("controlplaneio-fluxcd/distribution") &&
        rule.separateMinorPatch === true,
    ),
  );
});
