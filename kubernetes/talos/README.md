# Upgrade preparation

Prepared on 2026-10-03 for the single control-plane/workload node `talos01`,
`192.168.1.10`, Kubernetes context `homelab`. Preparation does not apply machine
configuration or initiate upgrades.

| Component | Running | Prepared target |
| --- | --- | --- |
| Talos | 1.13.4 | 1.14.2 |
| Kubernetes | 1.36.1 | 1.36.5 |

Kubernetes 1.36.5 is the latest patch in the installed minor. Installed Cilium
1.20.2, Envoy Gateway 1.9.2, and Flux 2.9 published compatibility matrices stop
at Kubernetes 1.36. Talos 1.14 supports 1.37, but the add-on matrices should be
reviewed before selecting that minor. The 1.37.1 dry-run on the current Talos
node rejects the version; the 1.36.5 dry-run passes without applying updates.

## Configuration migration

`talconfig.yaml` uses `patches/control-plane-v1.14.yaml`. It moves scheduler and
controller-manager metrics bindings into `KubeSchedulerConfig` and
`KubeControllerManagerConfig`, and disables kube-proxy through `KubeProxyConfig`.
This avoids conflicts with Talos 1.14's generated component documents. Etcd's
metrics-only listener remains in the supported legacy etcd configuration.
`patches/control-plane-metrics.yaml` remains the original Talos 1.13 patch.

Talhelper 3.1.17 still emits a Talos 1.14.2 compatibility warning. Generated
normal and Tailscale image configurations passed the actual Talos 1.14.2 CLI's
strict validation. Generate into a private directory with `umask 077`, using
the existing encrypted `talsecret.sops.yaml`. Never print a generated config or
use generator diff output in agent logs; it contains cluster credentials.

Do not apply a full regenerated configuration during the OS upgrade. It also
contains the desired Kubernetes version and other repository settings. Use the
explicit installer image, verify recovery, and upgrade Kubernetes separately.

## Reviewed images

The normal target preserves the repository's kernel arguments and requested
Intel microcode/i915 extensions:

```text
factory.talos.dev/metal-installer/dbe5c41cf2e93f426705e87651cba6c188429e0f30f28db79c41bd85549abc7a:v1.14.2
sha256:7ac138957fab853b0947b4bf8c0291e0a6a12337cdcc5945633f5395856f642d
```

The separate Tailscale candidate adds only `siderolabs/tailscale` to that
schematic. Both installer manifests were resolved through Image Factory:

```text
factory.talos.dev/metal-installer/5245e77b57a2435517211aec267ba032349120adc66954d24c551d548e6196b2:v1.14.2
sha256:ca02fe5fac3f8ab47d3f3934f0df3b6358fd3eb12dbed55e574bc12bd4709a4e
```

Factory's matching extensions are `intel-ucode:20260812`,
`i915:20260916-v1.14.2`, and `tailscale:1.102.3`. The running node reports no
installed extensions, so the requested Intel extensions would also be added
by either target image. The node's installer annotation is stale (1.13.2);
use live Talos version and extension inventory for verification.

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
     --image factory.talos.dev/metal-installer/dbe5c41cf2e93f426705e87651cba6c188429e0f30f28db79c41bd85549abc7a:v1.14.2@sha256:7ac138957fab853b0947b4bf8c0291e0a6a12337cdcc5945633f5395856f642d \
     --wait --timeout 30m
   ```

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

## Later native Tailscale evaluation

The Tailscale image and `patches/tailscale-service.example.yaml` are candidates,
not enabled by `talconfig.yaml`. Installing the image separately isolates OS
upgrade validation from host routing changes. Including it in the first reboot
could avoid a second reboot, but that decision belongs in the reviewed action.

The extension uses kernel TUN and persistent `/var/lib/tailscale` state. Keep
node DNS independent of Tailscale with `TS_ACCEPT_DNS=false`, retain the LAN
node-IP restriction, and verify Cilium device/MTU selection after `tailscale0`
appears. Keep the UDP GRO workaround for QUIC until repeated tests pass.

Advertise only the Envoy VIP `192.168.1.20/32` and node/API address
`192.168.1.10/32`. Enrollment, tag authorization, route approval/client route
acceptance, and administrator TCP 6443/50000 grants still need verification.
UDP 443 to the Envoy VIP was added separately in the ACL repository.

Keep the existing operator and subnet router until the native paths pass
management, DNS, HTTPS, and HTTP/3 checks. After validation, remove Envoy's
split-horizon address translation so ExternalDNS's existing VIP answers work
for LAN and routed tailnet clients. Then remove the superseded operator
resources and broad route. NAS remains the direct tailnet DNS resolver.
