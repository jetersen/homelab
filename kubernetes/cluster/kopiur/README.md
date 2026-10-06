# Application backups with Kopiur

Home Assistant, Zigbee2MQTT, Sonarr, and PhotoPrism write encrypted repositories to retained
NAS PVCs. `RepositoryReplication` mirrors each repository to S3 hourly, with
separate schedules from snapshots and maintenance. Offsite recovery depends on
a successful replication after the selected snapshot. The read-only
`APPLICATION-offsite` repositories support S3 discovery and recovery. Forgejo
stages both stores on the NAS and writes its Kopia repository directly to S3.

Kopiur owns snapshot retention and repository maintenance. Native application
archive retention is separate. The source-scoped keep-latest policy flag prevents
Kopia's pruning from competing with Kopiur's retention.

## Storage and credentials

Use [the Pulumi project](/infrastructure/backup/README.md) for S3 setup.

Resolve credentials and the Kopia repository password through Varlock, and
encrypt Secret payloads with SOPS. Keep recovery material outside the cluster. `create.enabled: false` requires an existing repository and
prevents silently initializing an empty replacement. For a new, reviewed backend,
use `create.enabled: true` for its first initialization.

See [Home Assistant and Zigbee backups](/kubernetes/apps/home-assistant/backup/README.md),
[Sonarr backups](/kubernetes/apps/media/backup/README.md), and
[Forgejo recovery](/kubernetes/apps/forgejo/README.md#backup-and-recovery), and
[PhotoPrism recovery](/kubernetes/apps/photoprism/README.md#backups-and-recovery).
PVC backups do not recover Talos configuration, SOPS keys, unrelated NAS data,
Pulumi state, or secrets outside those volumes.

## Manual backups

Create a `Snapshot` in the application's namespace. Use a new generated name
for each invocation; reapplying an existing object does not start another backup.
For example, save this manifest outside the repository:

```yaml
apiVersion: kopiur.home-operations.com/v1alpha1
kind: Snapshot
metadata:
  generateName: sonarr-manual-
  namespace: media
spec:
  policyRef:
    name: sonarr-backup
```

```bash
kubectl --context homelab create -f /protected/path/snapshot.yaml
kubectl --context homelab -n media wait --for=jsonpath='{.status.phase}'=Succeeded \
  snapshot/CREATED_NAME --timeout=30m
```

Pause snapshots through GitOps with `SnapshotSchedule.spec.schedule.suspend: true`.
Maintenance and repository replication have separate controls. To request an
immediate replication, annotate its resource with a fresh RFC3339
`kopiur.home-operations.com/run-requested` value, then verify that
`status.manualRun.phase` is `Succeeded` and `status.lastReplicated` follows the
snapshot completion.

## Isolated restores

Select a successful Snapshot from the catalog. A Restore can reference its
`source.snapshotRef`, or use `source.identity` with an explicit Kopia snapshot ID.
For an offsite restore, select the read-only `APPLICATION-offsite` repository and
verify replication completed after that snapshot before proceeding.

Use a new `target.pvc` with `local-path`, `ReadWriteOnce`, and enough capacity for
the recovered files. Set `policy.onMissingSnapshot: Fail` and leave
`options.enableFileDeletion: false`. Keep the temporary manifest outside the
repository and apply it with Kubernetes context `homelab`. Wait for
`status.phase: Completed`, then validate the recovered archive or application
state before starting an isolated recovery test.

An unprivileged restore can write a fresh PVC through `fsGroup`, but cannot change
its root directory metadata. Keep the default `ignorePermissionErrors: true` for
that case, then separately check restored file hashes, modes, and ownership.
Do not treat an ignored permission error as proof of successful recovery.

Deletion of a produced Snapshot defaults to deleting its Kopia snapshot too.
Use `deletionPolicy: Retain` for recovery points that must survive object cleanup.
Deleting a Repository does not erase its underlying storage. Before retiring a
backend, verify replacement recovery and review the exact repository and prefix.

References:

- [Installation](https://kopiur.home-operations.com/install/)
- [Backup hooks](https://kopiur.home-operations.com/reference/crds/snapshot-policy/#hooks)
- [Repository replication](https://kopiur.home-operations.com/replication/)
- [Restores](https://kopiur.home-operations.com/restores/)
