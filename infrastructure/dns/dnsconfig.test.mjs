import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const settings = JSON.parse(readFileSync("infrastructure/dns/settings.json", "utf8"));
const source = readFileSync("infrastructure/dns/dnsconfig.js", "utf8");

function internalZones() {
  const zones = [];
  const context = {
    DNS_VIEW: "internal",
    require: () => settings,
    NewRegistrar: () => "none",
    NewDnsProvider: (name) => name,
    DnsProvider: (name) => name,
    DefaultTTL: () => null,
    NO_PURGE: null,
    A: (name, target) => ({ type: "A", name, target }),
    AAAA: (name, target) => ({ type: "AAAA", name, target }),
    D: (name, _registrar, provider, _ttl, _retain, records) => {
      zones.push({ name: name.split("!")[0], provider, records });
    },
  };
  vm.runInNewContext(source, context);
  return zones;
}

test("search-expanded names cannot match a LAN or UniFi wildcard", () => {
  for (const zone of internalZones()) {
    const wildcards = zone.records.filter((r) => r.name.includes("*"));
    if (zone.provider === "technitium" && zone.name === settings.domain) {
      assert.equal(wildcards.length, 2);
    } else {
      assert.equal(wildcards.length, 0, `${zone.provider}: ${zone.name}`);
    }
  }
});

test("explicit gateway names retain both address families in both providers", () => {
  for (const zone of internalZones()) {
    for (const name of settings.gatewayNames) {
      const isLan = name.endsWith(`.lan.${settings.domain}`);
      if (isLan !== (zone.name === `lan.${settings.domain}`)) {
        continue;
      }
      if (!isLan && zone.provider === "technitium") {
        continue;
      }
      const relative = name.slice(0, -(zone.name.length + 1));
      for (const [type, target] of [
        ["A", settings.envoyIPv4],
        ["AAAA", settings.envoyIPv6],
      ]) {
        assert.ok(
          zone.records.some((r) => r.name === relative && r.type === type && r.target === target),
          `${zone.provider}: ${name} ${type}`,
        );
      }
    }
    for (const record of settings.infrastructure) {
      if (
        record.name.endsWith(`.lan.${settings.domain}`) !==
        (zone.name === `lan.${settings.domain}`)
      ) {
        continue;
      }
      const relative = record.name.slice(0, -(zone.name.length + 1));
      assert.ok(!zone.records.some((r) => r.name === relative && r.type === "AAAA"), record.name);
    }
  }
});

test("every supported legacy redirect has an explicit DNS name", () => {
  const redirects = readFileSync(
    "kubernetes/cluster/envoy-gateway/config/legacy-hostname-redirects.yaml",
    "utf8",
  );
  const names = [...redirects.matchAll(/^ {2}- (\S+\.lan\.jetersen\.dev)$/gm)].map(
    (match) => match[1],
  );
  assert.ok(names.length > 0);
  for (const name of names) {
    assert.ok(settings.gatewayNames.includes(name), name);
  }
});
