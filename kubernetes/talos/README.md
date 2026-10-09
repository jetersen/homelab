# Talos

## Configuration generation

[TOPF](https://github.com/postfinance/topf) assembles [topf.yaml](topf.yaml)
with patches under `patches/all/`, `patches/control-plane/`, and
`patches/node/<hostname>/`, in that order. Use TOPF 0.6.1 or newer and a
`talosctl` matching the cluster version. [schematic.yaml](schematic.yaml)
defines extensions and kernel arguments; its ID is computed locally.

The existing `talsecret.sops.yaml` is the secrets bundle configured by
`secretsPath`. Keep it SOPS-encrypted and ensure it exists before running TOPF.
TOPF can generate a new bundle when one is missing and can fall back to
plaintext storage when encryption fails.

Run from this directory, with the SOPS age identity available:

```sh
umask 077
topf render --output clusterconfig
talosctl validate --config clusterconfig/talos01.yaml --mode metal
```

Rendered configs contain private keys and tokens and are ignored by Git.
Capture TOPF apply previews privately outside the repository, including with
`--dry-run`. A dry-run exits with status 2 when differences exist. Review the
complete preview before applying; generation alone does not authorize changes
to the node. Use focused `talosctl patch mc --mode=no-reboot` updates for narrow
changes. TOPF applies complete configs, including any pending repository edits.

`topf talosconfig` writes a client config to stdout. Redirect it privately or
to the ignored `clusterconfig/talosconfig`; never print it in agent output.

## Local application storage

[LocalPV LVM](../cluster/openebs-lvm/README.md) uses dedicated raw partitions
selected by disk WWID, with separate volume groups for thick and thin PVCs.
The [storage patch](patches/node/talos01/localpv-lvm.yaml) preserves Talos's existing
partitions and loads the thin-pool kernel module. Apply it as a focused patch;
validate changes with the matching `talosctl` version before applying them.

Keep free disk space available for future storage changes. Increasing a
partition's configured maximum does not make it grow across an adjacent
partition. EPHEMERAL holds container runtime data, kubelet data, logs and etcd;
moving application PVCs does not free its capacity.

Kubelet removes container images after seven days without use through
`imageMaximumGCAge: 168h`. Running containers keep their images; later rollbacks
can pull removed images from the registry. Kubelet restarts reset age tracking,
and disk usage thresholds can trigger cleanup sooner.

## Dual-stack networking

Keep IPv4 first in the Pod and Service subnet lists to preserve the primary
address family. Kubelet selects its IPv6 address from the LAN ULA prefix,
excluding Tailscale and ISP-provided addresses. Services use a separate ULA
range. Pods use a dedicated public subnet from the ISP's fixed allocation.
Cilium uses Kubernetes IPAM and native routing with IPv6 masquerading disabled;
IPv4 masquerading remains enabled.

For this single-node cluster, UniFi routes `172.22.0.0/16` through
`192.168.1.10` and `2a13:e747:b7be:2200::/56` through the node's LAN ULA.
The IPv4 route also permits direct LAN access to Pod addresses.

Keep Cilium's egress gateway disabled while no policies require it. It enables
tunnel MTU overhead even with native routing; subtracting that overhead from
Tailscale's 1280-byte MTU puts Pod routes below IPv6's minimum MTU.

Before enabling public Pod addresses, configure the gateway's static IPv6 WAN
address and route the Pod subnet through the node's LAN ULA address. Keep the
LAN's public subnet separate from the Pod subnet and retain the IPv6 firewall.
Configure UniFi's WAN first, then reapply the LAN IPv6 settings: changing the
WAN mode can reset the LAN's IPv6 mode to None.
Netnørden's DHCPv6 delegation can change within the customer's fixed /48;
use the static WAN parameters from the customer portal rather than relying on
the requested DHCPv6 delegation size. See the
[ISP's IPv6 guide](https://netnoerden.dk/faq/22).

TrueNAS also needs a persistent route for the public Pod subnet through the
node's LAN ULA address. This keeps Pod-to-NAS traffic symmetric instead of
sending replies through the gateway, which can break TCP DNS.
Direct IPv6 Pod access from other LAN clients requires symmetric routing.
Application clients use Envoy ingress instead, so they do not need Pod routes.

Envoy serves IPv4 at `192.168.1.20` and internal IPv6 at
`fde2:b84e:c4cd:1::1000`. Cilium allocates that ULA from an Envoy-only /128
pool and advertises it through NDP on the physical LAN interface. Keep this
address outside the DHCPv6 allocation range. Envoy uses dual-stack listeners
and Cluster external traffic policy, as required by Cilium L2 announcements.
Internal DNS publishes both addresses after LAN and tailnet validation; public
DNS continues to target the existing public entry point. The IPv6 ingress /128
is also advertised by Tailscale, with the same allowed service ports as IPv4.

Include the public Pod subnet in source-IP restrictions for outbound API
credentials, including the Cloudflare token shared by cert-manager and
DNSControl jobs. IPv6 requests retain the Pod's public source address.
Also add that subnet to Technitium's recursion ACL on the primary DNS server
and verify replication to the NAS.

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

## Cluster upgrades

Tuppr reconciles the Talos and Kubernetes targets under
[cluster/tuppr/upgrades](../cluster/tuppr/upgrades). Renovate groups each target
with its matching version in `topf.yaml`. Upgrades may start on Sundays
between 04:00 and 06:00 Europe/Copenhagen; the window does not stop an upgrade
already in progress. Single-node upgrades interrupt workloads during reboot.
Node readiness, Cilium rollout, and CoreDNS availability gate upgrades.

The [API access patch](patches/control-plane/tuppr-api-access.yaml) grants `os:admin` to Talos
service accounts in `system-upgrade`. Apply it before installing Tuppr. Keep the
stored installer URL aligned with the running Factory schematic so Tuppr can
verify that upgrades preserve extensions and boot customization.

Forgejo checks the live versions through Kromgo and the cached compatibility
matrices for the deployed Cilium, Envoy Gateway, Flux, cert-manager, and Talos
versions. Kubernetes must remain within their common supported range. Renovate can propose at most the next
minor; minor upgrades require dashboard approval and manual merge. Only patches
on the node's live minor can auto-merge, after a three-day release age. See the
[CI policy](../../.ci/README.md#live-upgrade-policy) for validation and failure
behavior.

Inspect `TalosUpgrade` and `KubernetesUpgrade` status with context `homelab`.
Tuppr dashboards and VictoriaMetrics rules cover unavailable, failed, stuck,
and overdue upgrades. Alert delivery depends on Alertmanager receivers.
Investigate terminal failures before resetting a plan using Tuppr's documented
reset annotation or changing its target; a maintenance window alone does not
retry a failed upgrade.

## Native Tailscale

The Talos image includes `siderolabs/tailscale`.
[The service patch](patches/node/talos01/tailscale-service.yaml) enables kernel networking and
advertises individual host routes for the Kubernetes API, Envoy gateway, and
cluster DNS. Keep these routes narrow instead of advertising the LAN subnet.

Enrollment uses an interactive login. State persists under `/var/lib/tailscale`;
configure the extension before rebooting because an unconfigured service can
hold up boot. Keep enrollment URLs and recovery material outside the repository.
Apply service changes with `talosctl patch mc --mode=no-reboot`, capturing raw
configuration diffs privately as required by [AGENTS.md](../../AGENTS.md).

Keep kubelet and etcd addresses pinned to the LAN through [the node configuration](patches/all/00-cluster.yaml) and
[the etcd patch](patches/control-plane/etcd-lan.yaml). Check Cilium still selects the physical
interface after changing native Tailscale networking.

## DNS and access

[Resolver configuration](patches/node/talos01/resolver-search-domains.yaml) explicitly clears
DHCP search domains and disables hostname-derived search domains. Kubernetes
adds its own service search domains; workloads use the default `ndots:5`.
Use fully qualified LAN names. After applying this patch without reboot,
recreate existing pods to refresh their resolver configuration.

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
