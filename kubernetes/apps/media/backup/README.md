# Sonarr backups

Use Sonarr's native backup to preserve its database and configuration together.
Logs, caches, artwork, downloads, and media are excluded. Scheduling and retention
are configured in the manifests.

## Setup

Configure the credentials described in the [backup infrastructure guide](/infrastructure/backup/README.md),
then generate Sonarr's encrypted connection:

```bash
BACKUP_S3_CONFIGURED=true npm exec -- varlock run -- \
  python infrastructure/backup/prepare-kubernetes-secrets.py --application sonarr
```

Keep recovery credentials outside the cluster and repository. Backup archives
contain credentials and must remain private.

## Backup

Create a native export and wait for it to finish:

```bash
kubectl --context homelab -n media create job sonarr-backup-export-UNIQUE_TRIGGER \
  --from=cronjob/sonarr-backup-export
kubectl --context homelab -n media wait --for=condition=complete \
  job/sonarr-backup-export-UNIQUE_TRIGGER --timeout=240s
```

After a successful export, set `paused: false` and a new manual trigger in
`sonarr-source.yaml` through GitOps. Check that `status.lastManualSync` matches the
trigger and `latestMoverStatus.result` is `Successful`, then pause the source again.

Keep exports and uploads sequential. Before enabling a schedule, configure cleanup
of Sonarr's manual native backups, repository maintenance, and failure alerts.
Sonarr's automatic retention does not remove manual backups.

## Restore

Restore into a new volume using a cutoff between backup completion and now:

```bash
python infrastructure/backup/prepare-pilot-restore.py sonarr \
  --as-of EXPLICIT_RFC3339_TIMESTAMP > /tmp/sonarr-pilot-restore.yaml
kubectl --context homelab apply -f /tmp/sonarr-pilot-restore.yaml
```

Verify the restored archive, then follow [Sonarr's restore instructions](https://wiki.servarr.com/sonarr/faq#how-do-i-backuprestore-my-sonarr).
Block outbound traffic before starting a recovery test so it cannot contact live
indexers or download clients. Keep the test instance away from managed media.
