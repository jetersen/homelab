# Application backups

Flux manages the Kopia-enabled `perfectra1n/volsync` controller and pinned snapshot
API definitions. Chart and image versions are declared in `app/helmrelease.yaml`.
The controller runs in `volsync-system`; movers run in application namespaces.
Direct backups require the snapshot API definitions for controller startup, but
use no snapshot controller or storage driver.

`copyMethod: Direct` reads a PVC without making a point-in-time copy. Use completed
native exports or stopped writers for consistency. Snapshot actions in a mover
do not automatically stop another pod's application.

## Storage setup

Use [the Pulumi project](/infrastructure/backup/README.md) to manage the
private OVHcloud bucket and scoped S3 access. Region `de` and endpoint
`s3.de.io.cloud.ovh.net` provide Frankfurt Standard storage. Kopia takes a hostname
without a protocol or bucket prefix; its repository URL supplies the bucket and
repository prefix. Confirm connection values against the deployed bucket.

Keep credentials and a separate Kopia repository password in Proton Pass, resolve
them through Varlock, and generate SOPS-encrypted connection Secrets. Keep recovery
material outside the cluster. The active repository requires online storage;
review Kopia maintenance before adding object expiry, archive transitions,
versioning, Object Lock, or replication.

The NAS holds primary repositories. Kopia's `repository sync-to` replicates them
to S3 after backups and maintenance. Pruning requires matching repository identities
and a mounted NFS volume. Do not run backups or maintenance on S3 replicas.
Provision private NAS directories and use the existing `nas-storage.sops.yaml`
manifests as the schema for retained PVs and PVCs. Encrypt NFS locations using
the repository's SOPS rules. NAS connection Secrets use
`KOPIA_REPOSITORY=filesystem:///mnt/nas-repository` and the repository password
resolved through Varlock. Preserve the S3 connection Secrets for offsite recovery.
Before switching an existing S3 source, seed an empty NAS directory using
`repository sync-to filesystem`. New repositories need an initial S3 sync too.
Scheduled replication refuses uninitialized or unrelated destinations.

For NAS recovery, mount the application's NAS PVC read-only and connect a fresh
Kopia client with `repository connect filesystem --readonly --path MOUNT_PATH`.
Use the saved Kopia password, list snapshots, and restore into a separate directory.

## Backup and recovery

1. Choose a native export or stopped-writer consistency method for each application.
   Preserve required hidden configuration, database state, and external recovery keys.
2. Choose repository prefixes and source identities. Assign one maintenance owner
   per repository and define retention, selection policies, and failure/staleness alerts.
3. Review the rendered configuration and coordinate downtime before deploying.
   Use Kubernetes context `homelab` and account for Flux reconciliation.
4. Start with a manual backup and restore into a separate fresh PVC. Verify selected
   data, isolated application recovery, and access from a fresh client.
5. Verify maintenance, pruning, and alerts before scheduling jobs or expanding coverage.

See [Home Assistant and Zigbee backup procedures](/kubernetes/apps/home-assistant/backup/README.md).
See [Sonarr backup procedures](/kubernetes/apps/media/backup/README.md) for native database
and configuration exports without logs or media.
Application PVC backups do not recover Talos configuration, SOPS keys, NAS data,
Pulumi state, or runtime secrets outside those volumes. Give these separate
recovery procedures. Keep inventory, measurements, and test results private.

## Isolated restores

Before restoring from S3, verify that the requested manual backup completed:
the ReplicationSource's `status.lastManualSync` must match `spec.trigger.manual`,
`status.latestMoverStatus.result` must be `Successful`, and `status.lastSyncTime`
must be present. For a NAS source, also verify that the workflow CronJob's
`status.lastSuccessfulTime` is at or after that backup completion. Choose an
explicit RFC3339 recovery cutoff between backup completion and the current time.

Prepare a temporary PVC and a `volsync.backube/v1alpha1` ReplicationDestination
in the application's namespace, using names that do not already exist. The PVC
uses `local-path`, `ReadWriteOnce`, and enough capacity for the restored data.
Set `spec.trigger.manual` to a unique restore trigger. In `spec.kopia`, use the
S3 Secret named `APPLICATION-kopia`, `copyMethod: Direct`, the new `destinationPVC`,
`restoreAsOf` set to the cutoff, `username` set to the application, `hostname: homelab`,
and `enableFileDeletion: false`. Copy the cache, mover security context, and resource
settings from the application's ReplicationSource. Keep the temporary manifest
outside the repository and apply it with Kubernetes context `homelab` after
reviewing its target. Validate recovered files before starting an isolated test.

## Local validation

```bash
kustomize build kubernetes/flux/namespaces
kustomize build kubernetes/cluster
kustomize build kubernetes/cluster/volsync/app
```

For Helm validation, extract `values` from `app/helmrelease.yaml` and render the
version declared there with the target Kubernetes version:

```bash
helm template volsync volsync \
  --repo https://perfectra1n.github.io/volsync/charts \
  --version CHART_VERSION --namespace volsync-system --kube-version KUBERNETES_VERSION \
  --values /path/to/temporary-values.yaml
```

References:

- [Distribution source](https://github.com/perfectra1n/volsync)
- [Kopia backup configuration](https://perfectra1n.github.io/volsync/usage/kopia/backup-configuration.html)
- [Kopia restore configuration](https://perfectra1n.github.io/volsync/usage/kopia/restore-configuration.html)
- [Repository maintenance](https://perfectra1n.github.io/volsync/usage/kopia/kopiamaintenance.html)
