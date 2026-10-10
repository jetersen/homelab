# DNSControl

DNSControl manages public Cloudflare records and separate internal views on
Technitium and UniFi. The NAS receives Technitium's zones through catalog
replication; UniFi provides an independent copy during NAS or Kubernetes outages.

Edit [settings.json](settings.json) for desired records. Internal wildcards cover
routes automatically; add public aliases alongside their routes. DNSControl does
not discover routes or wait for them to become ready. Both `jetersen.dev` and
`lan.jetersen.dev` need wildcards because Technitium serves them as separate zones.

Kubernetes apps use `*.jetersen.dev`. Former `*.lan.jetersen.dev` app URLs
permanently redirect to their canonical names, preserving paths and queries.
Physical LAN devices keep their existing names. Both Jellyfin IoT names point to
the dedicated IPv4 address so redirects stay reachable from the IoT network.

Validate both address families for explicit IPv4-only names. Technitium suppresses
the wildcard AAAA at an existing name, while UniFi can still return its wildcard
IPv6 address. Keep IPv4-only isolated endpoints on Technitium DNS; UniFi's fallback
view is not equivalent for those names.

## Validation

Run from the repository root with the Go version pinned in [compat/go.mod](compat/go.mod):

```sh
bash infrastructure/dns/install.sh /tmp/dnscontrol-tools
/tmp/dnscontrol-tools/dnscontrol check --config infrastructure/dns/dnsconfig.js
```

The configuration uses ES5 syntax for DNSControl's embedded Otto runtime.
The compatibility build treats private record type 65281 as opaque data to avoid
a collision between Technitium forwarders and AdGuard records. Preserve
forwarders and validate both internal zones when changing this build.
`install.sh` reuses the runner's bundled binary when its fingerprint matches.

## Deployment

Set the repository variable `DNSCONTROL_ENABLED=true` and configure these secrets:

- `DNSCONTROL_CF_API_TOKEN`
- `DNSCONTROL_UNIFI_API_KEY`
- `DNSCONTROL_TECHNITIUM_TSIG_SECRET`

Use the Kubernetes runner so source addresses match the provider ACLs. The
workflow requests both `linux-docker` and `runner-kubernetes`, keeping the Docker
executor while excluding Rocket. The KEDA query includes both labels because
Forgejo matches jobs only when all their `runs-on` labels appear in the query;
this retains ordinary `linux-docker` jobs too. Keep TLS verification enabled and
configure Technitium's AXFR and update keys. One job
validates the configuration, then reconciles all three providers in a single
DNSControl invocation. Only the reconciliation step receives provider credentials.

Changes on `main` run `push`, which prints and applies corrections. Manual dispatch
runs `preview` unless `apply=true`; there is no scheduled reconciliation. Pull
requests only run local validation. Runs are serialized. Provider initialization
must succeed before DNSControl can reconcile the views.

Keep LAN wildcard domains out of runner DNS search suffixes. Some resolvers
retry through search domains after an absolute AAAA query returns no data, even
when the A query succeeds.

`NO_PURGE` preserves records managed elsewhere, including ACME and DNSSEC records.
It also retains removed declarations: deleting an entry does not delete its DNS
record. Review explicit deletions with retention rules for externally managed
records. Technitium forwarders, replication ACLs, and TSIG keys remain server-managed.
