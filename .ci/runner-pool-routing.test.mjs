import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(path, "utf8");

const kubernetesRunner = read("kubernetes/apps/forgejo/ci/runner.yaml");
const rocketRunner = read("infrastructure/forgejo/runner/rocket.yaml");
const scaledJob = read("kubernetes/apps/forgejo/ci/scaledjob.yaml");
const networkPolicy = read("kubernetes/apps/forgejo/ci/networkpolicy.yaml");
const dnsWorkflow = read(".forgejo/workflows/dnscontrol.yaml");

function runnerLabel(config, label) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = config.match(new RegExp(`^\\s*-\\s*${escaped}:([^\\n]+)$`, "m"));
  assert.ok(match, `expected runner config to define ${label}`);
  return match[1].trim();
}

test("DNSControl requires the Kubernetes pool while preserving Docker execution", () => {
  const match = dnsWorkflow.match(/^\s+runs-on:\s*\[([^\]]+)\]\s*$/m);
  assert.ok(match, "expected DNSControl to request both runner labels");
  assert.deepEqual(
    match[1].split(",").map((label) => label.trim()),
    ["linux-docker", "runner-kubernetes"],
  );
});

test("only the Kubernetes pool advertises the DNS routing label", () => {
  const dockerImage = runnerLabel(kubernetesRunner, "linux-docker");
  assert.equal(runnerLabel(kubernetesRunner, "runner-kubernetes"), dockerImage);
  assert.doesNotMatch(rocketRunner, /^\s*-\s*runner-kubernetes:/m);
});

test("KEDA keeps scaling all linux-docker jobs, including DNSControl", () => {
  assert.match(scaledJob, /^\s+labels:\s*linux-docker\s*$/m);
  const dnsLabels = ["linux-docker", "runner-kubernetes"];
  assert.ok(["linux-docker"].every((label) => dnsLabels.includes(label)));
});

test("runner egress allows Technitium's post-Service-mapping DNS port", () => {
  const rule = networkPolicy
    .split("    # DNSControl uses authenticated DNS updates and zone transfers.\n")[1]
    ?.split("    # Public package registries")[0];
  assert.ok(rule, "expected the Technitium-specific egress rule");
  assert.match(rule, /kubernetes\.io\/metadata\.name: technitium/);
  assert.match(rule, /app\.kubernetes\.io\/name: technitium/);
  const ports = [...rule.matchAll(/- \{port: (\d+), protocol: (UDP|TCP)\}/g)].map((match) => [
    Number(match[1]),
    match[2],
  ]);
  assert.deepEqual(ports, [
    [1053, "UDP"],
    [1053, "TCP"],
  ]);
});
