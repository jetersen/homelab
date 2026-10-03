# Native Tailscale

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

Internal ExternalDNS providers publish the Gateway's LAN VIP. Both LAN and
tailnet clients use that address; Technitium must not translate it to an
operator proxy address. Public DNS continues to use the separate Towonel target.

Tailnet global nameservers include TrueNAS's direct tailnet resolver and the
cluster DNS VIP. The NAS provides DNS independently of Kubernetes. Apply
Technitium configuration through the primary API so it replicates to the NAS.

Linux clients need `tailscale set --accept-routes=true` to reach advertised VIPs.
The tailnet policy permits TCP 80/443 and UDP 443 to Envoy, TCP/UDP 53 to cluster
DNS, and authenticated Kubernetes and Talos management to the node route.
Talos management also works through the node's direct tailnet address. Use
`talosctl` endpoint/node overrides for that path; keep TLS verification enabled.

## Verification

Use Kubernetes context `homelab`. Confirm the VIP routes select `tailscale0` and
`tailscale ping VIP` identifies the Talos node, then check UDP/TCP DNS, HTTPS, and
repeated HTTP/3 requests with certificate verification. Test Kubernetes `/readyz`
and authenticated Talos access. Check LAN access separately with subnet-route
acceptance temporarily disabled on a LAN client.

Before removing an operator, remove its Service exposure annotations and
Connectors while it is still running. Wait for its finalizers to remove proxy
workloads, state Secrets, and tailnet devices, then uninstall the Helm release.
Remove unused CRDs only after checking every instance is gone.
