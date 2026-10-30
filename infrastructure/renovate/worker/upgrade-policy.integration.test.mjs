import assert from "node:assert/strict";
import { resolve } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

// Publication runs this inside the built worker against its exact Renovate source.
test("compatibility gates preserve repository automerge policy in Renovate", {
  skip: !process.env.RENOVATE_SOURCE_PATH,
}, async (t) => {
  const source = pathToFileURL(`${resolve(process.env.RENOVATE_SOURCE_PATH)}/`);
  const { init } = await import(new URL("lib/logger/index.ts", source));
  await init();
  const { mergeChildConfig } = await import(new URL("lib/config/utils.ts", source));
  const { applyPackageRules } = await import(new URL("lib/util/package-rules/index.ts", source));
  const { policy, fluxUpgradePolicy, version } = await import(
    process.env.RENOVATE_POLICY_PATH
      ? pathToFileURL(resolve(process.env.RENOVATE_POLICY_PATH))
      : new URL("../../../.ci/renovate-upgrade-policy.mjs", import.meta.url)
  );
  const live = {
    talos: version("1.14.2"),
    kubernetes: version("1.36.5"),
    flux: version("2.10.0"),
    "flux-operator": version("0.62.1"),
  };
  const catalog = {
    projects: {
      "flux-operator": {
        versions: {
          "v0.62.1": {
            source:
              "https://api.github.com/repos/controlplaneio-fluxcd/flux-operator/contents/config/data/flux?ref=v0.62.1",
            sourceSha256: "a".repeat(64),
            supportedFlux: ["2.10", "2.11"],
          },
        },
      },
      flux: {
        versions: {
          "v2.11.0": {
            source: "https://api.github.com/repos/fluxcd/flux2/releases/tags/v2.11.0",
            sourceSha256: "b".repeat(64),
            supportedKubernetes: ["1.36"],
          },
        },
      },
    },
  };
  const packageRules = [
    ...policy(live, [["1.36", "1.37"]], ["1.14", "1.15"]).packageRules,
    ...fluxUpgradePolicy(catalog, live).packageRules,
  ];
  for (const [name, depName] of [
    ["talos", "siderolabs/talos"],
    ["kubernetes", "kubernetes/kubernetes"],
    ["flux", "controlplaneio-fluxcd/distribution"],
  ]) {
    const current = live[name];
    const dependency = {
      depName,
      packageName: depName,
      datasource: "github-releases",
      versioning: "semver",
      currentValue: current.text,
      currentVersion: current.text,
      newValue: `${current.line}.${current.patch + 1}`,
      updateType: "patch",
    };
    async function apply(repository, overrides = {}) {
      const config = mergeChildConfig({ automerge: false, packageRules }, repository);
      // Match at dependency extraction, then again after a candidate is selected.
      const { updateType, newValue, ...extracted } = { ...dependency, ...overrides };
      const beforeLookup = await applyPackageRules({ ...config, ...extracted });
      return applyPackageRules({ ...beforeLookup, updateType, newValue });
    }
    await t.test(`${name}: top-level opt-out survives a same-minor patch`, async () => {
      assert.equal((await apply({ automerge: false })).automerge, false);
    });
    await t.test(`${name}: matching package-rule opt-out survives a same-minor patch`, async () => {
      assert.equal(
        (
          await apply({
            automerge: true,
            packageRules: [{ matchPackageNames: [depName], automerge: false }],
          })
        ).automerge,
        false,
      );
    });
    await t.test(`${name}: repository opt-in permits a patch on the live minor`, async () => {
      assert.equal((await apply({ automerge: true })).automerge, true);
    });
    for (const updateType of ["minor", "major", "digest"]) {
      await t.test(`${name}: ${updateType} cannot inherit patch automerge`, async () => {
        assert.equal((await apply({ automerge: true }, { updateType })).automerge, false);
      });
    }
    await t.test(`${name}: a patch on a not-yet-deployed minor requires review`, async () => {
      const future = `${current.major}.${current.minor + 1}.0`;
      assert.equal(
        (
          await apply(
            { automerge: true },
            {
              currentValue: future,
              currentVersion: future,
              newValue: `${current.major}.${current.minor + 1}.1`,
            },
          )
        ).automerge,
        false,
      );
    });
  }
});
