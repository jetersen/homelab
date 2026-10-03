# DNS

Talos bootstraps CoreDNS's Deployment, Service, and RBAC. Flux manages its
Corefile; Talos leaves existing bootstrap resources intact during upgrades.

CoreDNS resolves Kubernetes service names locally, then forwards other queries
to cluster Technitium, NAS Technitium, and UniFi in that order. It retries another
upstream on connection failure, `SERVFAIL`, or `REFUSED`. Negative answers remain
authoritative and do not trigger fallback.

Technitium hosts `lan.jetersen.dev` as a Primary zone in the cluster catalog.
The NAS subscribes to the catalog and serves its replicated Secondary zone.
Keep both Technitium members on the same version so configuration sync remains
compatible. Create and edit zones through the primary API so changes replicate.
ExternalDNS manages service addresses and their ownership records.

Kubernetes masquerades outbound DNS notifications to the Talos node address.
Include that address as a single-host entry in Technitium's cluster-wide
`notifyAllowedNetworks` setting so the NAS accepts updates. Keep zone transfers
restricted by the catalog ACL and TSIG key.

Keep Talos's host resolvers independent of workloads on the same node: use NAS
Technitium and UniFi. Dotted names in application pods use `ndots:1`, which tries
the requested name before search suffixes while retaining short service lookup.
Media pods with explicit DNS settings use both Technitium instances. DNS probes
check the cluster service, NAS, and UniFi independently.
