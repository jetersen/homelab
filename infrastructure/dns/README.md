# DNSControl

DNSControl reconciles public Cloudflare DNS and independent internal copies on
Technitium and UniFi. The Forgejo workflow runs short jobs rather than maintaining
Kubernetes watches. Internal views use IPv4 and IPv6 wildcards for Envoy, with
explicit infrastructure overrides. Both `jetersen.dev` and `lan.jetersen.dev`
need wildcards because Technitium serves them as separate zones. NAS receives the
Technitium view through the existing catalog replication. UniFi remains an
independent copy for its clients and for DNS during NAS or Kubernetes outages.

The JavaScript route adapter reads a Kubernetes JSON snapshot. Public HTTPRoutes
must opt in with `public.external-dns.kubernetes.io/enabled: "true"`.
TCPRoutes also need a hostname annotation using that prefix and produce unproxied
records. Missing or stale Gateway/route status stops public reconciliation.
Internal wildcard updates do not require Kubernetes access.

Run `node --test infrastructure/dns/route-adapter.test.mjs` for adapter checks.
Install the pinned binary with `bash infrastructure/dns/install.sh /tmp/dnscontrol-tools`.
DNSControl is pinned to v4.46.0 because v5.3.0 cannot decode Technitium's
conditional-forwarder records during AXFR. Preserve those records and test both
internal zones before upgrading DNSControl.
Validate static views with:

```sh
/tmp/dnscontrol-tools/dnscontrol check --config infrastructure/dns/dnsconfig.js --variable DNS_VIEW=internal
```

To check public routes, capture `kubectl --context homelab get httproutes,tcproutes,gateways -A -o json`
in private local storage, then add `--variable DNS_VIEW=all --variable ROUTES_FILE=/absolute/path/routes.json`.

The workflow is gated by `DNSCONTROL_ENABLED=true`. It requires repository secrets
`DNSCONTROL_CF_API_TOKEN`, `DNSCONTROL_UNIFI_API_KEY`,
`DNSCONTROL_TECHNITIUM_TSIG_SECRET` and `DNSCONTROL_KUBECONFIG`. The kubeconfig
must use context `homelab` and only allow listing/getting Gateways, HTTPRoutes and
TCPRoutes. The `dnscontrol-rbac.yaml` manifest in the Forgejo runner directory
provides a dedicated service account with those permissions; include it in the
runner kustomization during activation. Use the Kubernetes runner so its source IP matches the Technitium TSIG
ACL and Cloudflare token restrictions. Keep TLS verification enabled and provide
both AXFR and update keys. Each job receives only its provider's credentials.

Initially the workflow previews changes; manual dispatch with `apply=true` pushes
them. Push and scheduled events also preview, so scheduled runs report drift but
do not yet repair it. Workflow runs are serialized, and an unavailable provider
does not prevent the other views from being checked.

`NO_PURGE` protects existing records during migration. It also retains records
removed from the configuration. Import or explicitly exclude records managed
elsewhere before enabling purging. Test wildcard answers and exceptions on all
resolvers before retiring ExternalDNS and its ownership TXT records. Preserve
Technitium catalog replication ACLs and TSIG keys throughout the transition.
