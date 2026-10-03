# Sonarr backups

Use Sonarr's native backup to preserve its database and configuration together.
Logs, caches, artwork, downloads, and media are excluded. Scheduling and retention
are configured in the manifests.
The workflow backs up to the NAS and replicates its encrypted repository to S3.
Repository replication mirrors the primary repository, including retention changes.
Its hourly schedule is separate from the snapshot schedule.

## Setup

Configure the credentials described in the [backup infrastructure guide](/infrastructure/backup/README.md),
then prepare Sonarr's SOPS-encrypted connections using the existing backup Secret
manifests as the schema. Preserve both NAS and S3 connections.

Keep recovery credentials outside the cluster and repository. Backup archives
contain credentials and must remain private.

## Backup

Kopiur schedules are defined in `kopiur.yaml`. The pre-backup Job creates and
validates a fresh native Sonarr archive before Kopiur snapshots the export PVC.
Follow the [manual backup procedure](/kubernetes/cluster/kopiur/README.md#manual-backups)
with policy `sonarr-backup` in namespace `media`.

Pause snapshots through GitOps by setting the SnapshotSchedule's
`spec.schedule.suspend` to `true`. Maintenance and offsite replication are separate.

## Restore

Follow the [isolated restore procedure](/kubernetes/cluster/kopiur/README.md#isolated-restores)
with application `sonarr` in namespace `media`. Restore from the `sonarr-offsite`
repository into a new PVC after verifying completed replication.

Verify the restored archive, then follow [Sonarr's restore instructions](https://wiki.servarr.com/sonarr/faq#how-do-i-backuprestore-my-sonarr).
Block outbound traffic before starting a recovery test so it cannot contact live
indexers or download clients. Keep the test instance away from managed media.
