# Talos upgrade and native Tailscale

Talos was upgraded on 2026-10-03 on the single control-plane/workload node
`talos01`, `192.168.1.10`, Kubernetes context `homelab`. Kubernetes was subsequently
upgraded to 1.36.5. No full regenerated machine configuration was applied.

| Component | Running | Prepared target |
| --- | --- | --- |
| Talos | 1.14.2 | 1.14.2, applied |
| Kubernetes | 1.36.5 | 1.36.5, applied |

Kubernetes 1.36.5 is the latest patch in the installed minor. Installed Cilium
1.20.2, Envoy Gateway 1.9.2, and Flux 2.9 published compatibility matrices stop
at Kubernetes 1.36. Talos 1.14 supports 1.37, but the add-on matrices should be
reviewed before selecting that minor. The 1.37.1 dry-run on the previous Talos
1.13.4 node rejected that version. The 1.36.5 dry-run passed on both Talos versions,
and the approved upgrade completed on Talos 1.14.2 without an OS reboot.

The Kubernetes upgrade updated the API server, controller-manager, scheduler,
and kubelet to 1.36.5 and CoreDNS to 1.14.7. All workloads, storage, and Flux
resources recovered, with 55/55 scrape targets and 18/18 availability probes
passing. One API 5xx was measured in the five-minute recovery window. NAS DNS
and Rocket's uncached public/local queries stayed available during the API restart.

## Configuration migration

`talconfig.yaml` uses `patches/control-plane-v1.14.yaml`. It moves scheduler and
controller-manager metrics bindings into `KubeSchedulerConfig` and
`KubeControllerManagerConfig`, and disables kube-proxy through `KubeProxyConfig`.
This avoids conflicts with Talos 1.14's generated component documents. Etcd's
metrics-only listener remains in the supported legacy etcd configuration.
`patches/control-plane-metrics.yaml` remains the original Talos 1.13 patch.

`patches/etcd-lan.yaml` pins etcd address selection to `192.168.1.0/24` and is
included in generated configurations. Without this selection, etcd chose the
new native Tailscale address after enrollment while Kubernetes kept its LAN IP.
The focused patch passed its no-reboot dry-run; live application requires approval
because etcd restarts and briefly interrupts the sole Kubernetes API.

Talhelper 3.1.17 still emits a Talos 1.14.2 compatibility warning. Generated
normal and Tailscale image configurations passed the actual Talos 1.14.2 CLI's
strict validation. Generate into a private directory with `umask 077`, using
the existing encrypted `talsecret.sops.yaml`. Never print a generated config or
use generator diff output in agent logs; it contains cluster credentials.

Do not apply a full regenerated configuration during the OS upgrade. It also
contains the desired Kubernetes version and other repository settings. Use the
explicit installer image, verify recovery, and upgrade Kubernetes separately.

## Reviewed images

The reviewed Intel-only alternative preserves the repository's kernel arguments
and requested microcode/i915 extensions:

```text
factory.talos.dev/metal-installer/dbe5c41cf2e93f426705e87651cba6c188429e0f30f28db79c41bd85549abc7a:v1.14.2
sha256:7ac138957fab853b0947b4bf8c0291e0a6a12337cdcc5945633f5395856f642d
```

The selected target adds `siderolabs/tailscale` to that schematic and is now
configured in `talconfig.yaml`. Both installer manifests were resolved through
Image Factory:

```text
factory.talos.dev/metal-installer/5245e77b57a2435517211aec267ba032349120adc66954d24c551d548e6196b2:v1.14.2
sha256:ca02fe5fac3f8ab47d3f3934f0df3b6358fd3eb12dbed55e574bc12bd4709a4e
```

The running node reports `intel-ucode:20260812`, `i915:20260916-v1.14.2`,
and `tailscale:1.102.3`. Before the upgrade it reported no installed extensions.
The node's installer annotation was stale (1.13.2); use live Talos version and
extension inventory for verification. Etcd upgraded to 3.7.1 with storage
version 3.7.0 and passed health, leadership, and raft consistency checks.

Recovery checks passed: 42 Deployments, four StatefulSets, three DaemonSets,
15 bound PVCs, 40 Flux Kustomizations, and 28 HelmReleases. Jellyfin's NAS NFS
mount was readable. Verified-TLS HTTP/2 and repeated HTTP/3 checks passed for
Homepage and Jellyfin through both the LAN VIP and operator's tailnet address.
Monitoring recovered to 55/55 healthy scrape targets and 18/18 successful probes;
VictoriaLogs was receiving fresh logs without dropped rows.

NAS DNS stayed available during the observed API outage, including UDP/TCP
queries over tailnet IPv4 and IPv6 and uncached public/local queries from Rocket.
An encrypted etcd snapshot was taken and checksum/round-trip verified before
the upgrade and again after the etcd data upgrade. These are not restore tests.

## Execution sequence

1. Recheck node/API/etcd readiness, storage, all Flux HelmReleases, monitoring,
   and NAS tailnet DNS. Obtain an encrypted etcd snapshot and verify its
   checksum and encrypted round trip. This does not test a restore and does
   not back up application PVC contents.
2. Obtain approval for the single-node Talos upgrade/reboot. Cluster services
   will be unavailable during the reboot; direct NAS DNS and GLKVM remain
   outside this failure domain. Normal Talos upgrades preserve node data.
3. Upgrade with the reviewed image and wait for the node to recover:

   ```sh
   talosctl --talosconfig kubernetes/talos/clusterconfig/talosconfig \
     --endpoints 192.168.1.10 --nodes 192.168.1.10 upgrade \
     --image factory.talos.dev/metal-installer/5245e77b57a2435517211aec267ba032349120adc66954d24c551d548e6196b2@sha256:ca02fe5fac3f8ab47d3f3934f0df3b6358fd3eb12dbed55e574bc12bd4709a4e \
     --wait --timeout 30m
   ```

   Use the digest-only reference above. Talos 1.13 pulls a tag-plus-digest
   reference under its digest-only name, then fails to find the original name
   in containerd's store when starting the installer.

4. Verify Talos 1.14.2, etcd health, Kubernetes remains 1.36.1, node Ready,
   mounted/PVC-backed storage, workloads, DNS, metrics, and HTTP/2/HTTP/3.
   Do not assume an OS downgrade reverses an etcd data upgrade. Recovery must
   account for the etcd version and verified snapshot.
5. Repeat the Kubernetes 1.36.5 dry-run, then obtain approval for its component
   restarts and brief API interruptions before running the same command
   without `--dry-run`:

   ```sh
   talosctl --talosconfig kubernetes/talos/clusterconfig/talosconfig \
     --endpoints 192.168.1.10 --nodes 192.168.1.10 upgrade-k8s \
     --from 1.36.1 --to 1.36.5 --dry-run
   ```

6. Repeat cluster/service/monitoring checks and verify each component's actual
   image version. A dry-run logs image pre-pull planning and skipped updates;
   it is not an upgrade.

## Native Tailscale

`patches/tailscale-service.yaml` is applied without reboot and included by
`talconfig.yaml`. The node was enrolled interactively in `jetersen.github`:

- IPv4: `100.99.149.66`
- IPv6: `fd7a:115c:a1e0::a237:d228`
- DNS: `talos01.rockhopper-bleak.ts.net`
- Tag: `tag:k8s-subnet-router`
- Approved routes: `192.168.1.10/32` and `192.168.1.20/32`

Restarting only `ext-tailscale` retained its identity and reconnected without
another login. Talos management and Kubernetes API readiness passed over both
tailnet address families. Talos uses its normal client configuration; Kubernetes
uses the existing cluster CA and `--tls-server-name=talos01.lan.jetersen.dev` when
connecting to a tailnet IP. Do not bypass TLS verification.

An extension without service configuration blocks Talos's `startAllServices`
boot task. During this upgrade, `ext-tailscale` was stopped through the supported
service API, allowing boot to finish and the node to uncordon:

```sh
talosctl --talosconfig kubernetes/talos/clusterconfig/talosconfig \
  --endpoints 192.168.1.10 --nodes 192.168.1.10 service ext-tailscale stop
```

The temporary stop was not persistent across reboot. Service configuration and
enrollment are now complete, resolving that boot wait. There is no `enabled`
flag in `ExtensionServiceConfig`; leaving the extension installed without its
service configuration would recreate the wait on a future boot.

The extension uses kernel TUN and persistent `/var/lib/tailscale` state. Node DNS
stays independent with `TS_ACCEPT_DNS=false`, and the LAN node-IP restriction is
retained. `tailscale0` uses MTU 1280; Cilium still selects physical `enp1s0` for
kube-proxy replacement and masquerading, with no degraded modules or controllers.
The UDP GRO workaround is retained for QUIC.

Only the Envoy VIP and node/API address are advertised. Enrollment, the tag,
and automatic route approval are verified. UDP 443 to the VIP and TCP 6443 to
the node are present in the ACL repository. Routed TCP 50000 and off-LAN client
route acceptance still need review before replacing the management route.

Native Envoy routing remains unverified: Rocket has `RouteAll=false`, so normal
VIP requests use Ethernet. Forced `curl --interface tailscale0` requests timed
out because disabling route acceptance also excludes subnet prefixes from the
Tailscale data plane; interface binding does not override it. Use a client that
accepts subnet routes to validate the native VIP path before removing the proxy.

Keep the existing operator and subnet router until the native paths pass
management, DNS, HTTPS, and HTTP/3 checks. After validation, remove Envoy's
split-horizon address translation so ExternalDNS's existing VIP answers work
for LAN and routed tailnet clients. Then remove the superseded operator
resources and broad route. NAS remains the direct tailnet DNS resolver.
