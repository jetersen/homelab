# Talos

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
