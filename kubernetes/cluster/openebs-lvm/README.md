# LocalPV LVM

OpenEBS LocalPV LVM provisions XFS filesystems on the node's LVM volumes.
Talos allocates raw partitions and creates the volume groups through
[the storage patch](../../talos/patches/node/talos01/localpv-lvm.yaml). Select the exact
partition labels for LVM physical volumes; never initialize the system disk
as a physical volume.

| StorageClass | Allocation | Volume group |
| --- | --- | --- |
| `openebs-lvm` (default) | Thick, reserves the requested capacity | `localpv-thick` |
| `openebs-lvm-thin` | Thin, shares physical pool capacity | `localpv-thin` |
| `openebs-lvm-ephemeral` | Thin, deletes the volume with its PVC | `localpv-thin` |

The application classes use `WaitForFirstConsumer`, support expansion and retain
volumes after PVC deletion. Use `openebs-lvm-ephemeral` for temporary backup job
caches so completed jobs release their storage. Retained volumes require explicit
cleanup. These classes do not
provide disk redundancy. Keep application-consistent backups outside the node.
CSI snapshot components are disabled.

`shared: "yes"` permits multiple pods to mount a volume on the same node,
including backup readers and parallel CI workers. PV node affinity still pins
volumes to their owning node; this does not provide access across nodes.

XFS cannot share a filesystem between CSI mounts with different read-only states.
For custom backup pods, leave the PVC volume source writable and set
`volumeMount.readOnly: true` on the container. Kopiur Direct sources mounted
alongside an application require `readOnly: false` and
`acknowledgeLiveMutation: true`; inherit the application's security context so
its file ownership remains compatible.

Use thick volumes for application state and monitoring. Thin volumes suit
replaceable caches. The separate volume groups isolate their capacity budgets.
The first thin PVC creates `localpv-thin_thinpool`; its initial physical size
depends on that PVC's request, not the volume group's size. Provision a pool of
the intended size before putting applications on thin storage. OpenEBS does not
enable automatic pool extension; monitor and grow pool data and metadata
separately, retaining free volume-group capacity for expansion.

VictoriaMetrics scrapes the CSI node agent for volume-group capacity and thin-pool
data and metadata usage. Pool alerts warn at 75% and become critical at 90%.
Verify these metrics before using thin volumes.

Expand a PVC by increasing its storage request. Thick expansion requires free
volume-group space; thin expansion also requires enough physical pool capacity
for future writes. Shrinking volumes is not supported. Changing StorageClass
requires a new PVC and an explicit copy or restore.

Validate new storage with disposable volumes: provisioning, writes, enforced
capacity, metrics, expansion, reboot recovery and reclaim behavior. Preserve
original PVCs until application checks, backups and rollback are verified.
