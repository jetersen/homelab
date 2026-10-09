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

The [network patch](patches/all/00-cluster.yaml),
[Cilium values](../cluster/cilium/app/helmrelease.yaml), and
[Gateway configuration](../cluster/envoy-gateway/config/) define address ranges,
routing, and ingress. See the [networking overview](../../NETWORKING.md) for
component responsibilities and access boundaries.

Keep IPv4 first in the Pod and Service subnet lists to preserve the primary
address family. Pin node addresses to the LAN and keep Pod, Service, and LAN
ranges separate. With IPv6 masquerading disabled, outbound requests retain their
Pod source addresses; upstream routing and access rules must account for them.

Direct Pod traffic needs symmetric return routes, including on the NAS.
Application clients use ingress and do not need direct Pod routes. Keep ingress
addresses outside dynamic address pools, and verify LAN and tailnet reachability
before publishing DNS records.

Keep Cilium's egress gateway disabled while no policies require it. Its tunnel
MTU overhead can reduce Pod routes below IPv6's minimum MTU when combined with
Tailscale. Recheck MTU and both address families when changing routing features.

Address-family changes on an existing cluster require a separate migration plan
that preserves local-volume bindings and management access. Keep machine-specific
routes, ISP settings, and recovery material outside the repository.

## Cluster upgrades

Tuppr reconciles the Talos and Kubernetes targets under
[cluster/tuppr/upgrades](../cluster/tuppr/upgrades). Renovate groups each target
with its matching version in `topf.yaml`. The
[upgrade configuration](../cluster/tuppr/upgrades/kustomization.yaml)
defines maintenance windows and health checks. A window does not stop an upgrade
already in progress. Single-node upgrades interrupt workloads during reboot.

The [API access patch](patches/control-plane/tuppr-api-access.yaml) grants `os:admin` to Talos
service accounts in `system-upgrade`. Apply it before installing Tuppr. Keep the
stored installer URL aligned with the running Factory schematic so Tuppr can
verify that upgrades preserve extensions and boot customization.

The [CI upgrade policy](../../.ci/README.md#live-upgrade-policy) checks proposed
versions against the deployed components' compatibility matrices and controls
Renovate approval and automerge behavior.

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

Keep tailnet DNS reachable independently of Kubernetes. See the
[DNS guidance](../../NETWORKING.md#dns-and-filtering) for resolver and replication
constraints.

Linux clients need `tailscale set --accept-routes=true` to reach advertised VIPs.
Talos management also works through the node's direct tailnet address. Use
`talosctl` endpoint/node overrides for that path; keep TLS verification enabled.

Verify that VIP routes select `tailscale0` and `tailscale ping VIP` identifies the
Talos node. Check LAN access separately with subnet-route acceptance temporarily
disabled on a LAN client.
