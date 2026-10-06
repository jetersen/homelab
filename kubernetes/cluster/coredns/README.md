# CoreDNS

Talos bootstraps CoreDNS's Deployment, Service, and RBAC. Flux manages its
Corefile; Talos leaves existing bootstrap resources intact during upgrades.

CoreDNS retries another upstream on connection failure, `SERVFAIL`, or `REFUSED`.
Negative answers remain authoritative and do not trigger fallback.

Technitium hosts `lan.jetersen.dev` as a Primary zone in the cluster catalog.
The NAS subscribes to the catalog and serves its replicated Secondary zone.
Keep both Technitium members on the same version so configuration sync remains
compatible. Create and edit zones through the primary API so changes replicate.
[DNSControl](../../../infrastructure/dns/README.md) manages service records.

Kubernetes masquerades outbound DNS notifications to the Talos node address.
Include that address as a single-host entry in Technitium's cluster-wide
`notifyAllowedNetworks` setting so the NAS accepts updates. Keep zone transfers
restricted by the catalog ACL and TSIG key.

Keep Talos's host resolvers independent of workloads on the same node: use NAS
Technitium and UniFi. The [Talos resolver patch](../../talos/patches/resolver-search-domains.yaml)
clears DHCP search domains and disables hostname-derived search domains. Pods
retain Kubernetes service search domains and the default `ndots:5`; LAN names
must be fully qualified so wildcard records cannot capture search-expanded names.
Recreate existing pods after changing the node resolver search configuration.
