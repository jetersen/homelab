# Talos

## Dual-stack networking

Keep IPv4 first in the Pod and Service subnet lists to preserve the primary
address family. Kubelet selects its IPv6 address from the LAN ULA prefix,
excluding Tailscale and ISP-provided addresses. Services use a separate ULA
range. Pods use a dedicated public subnet from the ISP's fixed allocation.
Cilium uses Kubernetes IPAM and native routing with IPv6 masquerading disabled;
IPv4 masquerading remains enabled.

Before enabling public Pod addresses, configure the gateway's static IPv6 WAN
address and route the Pod subnet through the node's LAN ULA address. Keep the
LAN's public subnet separate from the Pod subnet and retain the IPv6 firewall.
Configure UniFi's WAN first, then reapply the LAN IPv6 settings: changing the
WAN mode can reset the LAN's IPv6 mode to None.
Netnørden's DHCPv6 delegation can change within the customer's fixed /48;
use the static WAN parameters from the customer portal rather than relying on
the requested DHCPv6 delegation size. See the
[ISP's IPv6 guide](https://netnoerden.dk/faq/22).

When migrating an existing IPv4-only cluster, configure Talos's dual-stack
ranges and give every Node an IPv6 Pod CIDR before enabling Cilium IPv6.
Kubernetes does not allow changing an allocated Node's Pod CIDRs; recreating
the Node requires a maintenance window and a recovery procedure that preserves
its hostname, IPv4 Pod CIDR, labels, and local-volume bindings. Use focused
Talos patches and keep recovery material outside this repository.

Recreate existing pods to obtain both address families. Existing Services keep
their current family until explicitly changed. Validate IPv4 and IPv6 Pod and
Service traffic, DNS over UDP and TCP, and Cilium's outbound source address
after restart. Add IPv6 load-balancer addresses and DNS records only after LAN
and tailnet routes are ready.

## Kubernetes upgrades

Renovate limits Kubernetes and kubelet updates in
[versioning.json5](../../.renovate/versioning.json5). Before raising the limit,
check the Kubernetes compatibility matrices for the Cilium and Envoy Gateway
release lines selected in their OCIRepository manifests. Use the supported
range common to both releases; development releases do not establish support
for the deployed versions.

## Native Tailscale

The Talos image includes `siderolabs/tailscale`.
[The service patch](patches/tailscale-service.yaml) enables kernel networking and
advertises individual host routes for the Kubernetes API, Envoy gateway, and
cluster DNS. Keep these routes narrow instead of advertising the LAN subnet.

Enrollment uses an interactive login. State persists under `/var/lib/tailscale`;
configure the extension before rebooting because an unconfigured service can
hold up boot. Keep enrollment URLs and recovery material outside the repository.
Apply service changes with `talosctl patch mc --mode=no-reboot`, capturing raw
configuration diffs privately as required by [AGENTS.md](../../AGENTS.md).

Keep kubelet and etcd addresses pinned to the LAN through `talconfig.yaml` and
[the etcd patch](patches/etcd-lan.yaml). Check Cilium still selects the physical
interface after changing native Tailscale networking.

## DNS and access

LAN and tailnet clients use the Gateway's LAN VIP; Technitium must not translate
it to an operator proxy address.

Tailnet global nameservers include TrueNAS's direct tailnet resolver and the
cluster DNS VIP. The NAS provides DNS independently of Kubernetes. Apply
Technitium configuration through the primary API so it replicates to the NAS.

Linux clients need `tailscale set --accept-routes=true` to reach advertised VIPs.
Talos management also works through the node's direct tailnet address. Use
`talosctl` endpoint/node overrides for that path; keep TLS verification enabled.

Verify that VIP routes select `tailscale0` and `tailscale ping VIP` identifies the
Talos node. Check LAN access separately with subnet-route acceptance temporarily
disabled on a LAN client.
