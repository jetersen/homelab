# Sonarr backups

Use Sonarr's native backup to preserve its database and configuration together.
Logs, caches, artwork, downloads, and media are excluded. Scheduling and retention
are configured in the manifests.
The workflow backs up to the NAS and replicates its encrypted repository to S3.
Both destinations share the same retention policy.

## Setup

Configure the credentials described in the [backup infrastructure guide](/infrastructure/backup/README.md),
then prepare Sonarr's SOPS-encrypted connections using the existing backup Secret
manifests as the schema. Preserve both NAS and S3 connections.

Keep recovery credentials outside the cluster and repository. Backup archives
contain credentials and must remain private.

## Backup

Schedules are defined in `automation.yaml`. To run a backup manually:

```bash
kubectl --context homelab -n media create job sonarr-backup-UNIQUE_TRIGGER \
  --from=cronjob/sonarr-backup
kubectl --context homelab -n media wait --for=condition=complete \
  job/sonarr-backup-UNIQUE_TRIGGER --timeout=3600s
```

Pause schedules through GitOps by setting the workflow CronJob's `spec.suspend`
to `true`. Maintenance schedules and backup alerts are managed separately.

## Restore

Follow the [isolated restore procedure](/kubernetes/cluster/volsync/README.md#isolated-restores)
with application `sonarr` in namespace `media`. Restore from the `sonarr-kopia`
S3 connection into a new PVC after verifying completed replication.

Verify the restored archive, then follow [Sonarr's restore instructions](https://wiki.servarr.com/sonarr/faq#how-do-i-backuprestore-my-sonarr).
Block outbound traffic before starting a recovery test so it cannot contact live
indexers or download clients. Keep the test instance away from managed media.
