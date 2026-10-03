# Sonarr backups

The pre-backup job creates and validates a fresh native Sonarr archive to preserve
its database and configuration together.

Follow the [manual backup procedure](/kubernetes/cluster/kopiur/README.md#manual-backups)
with policy `sonarr-backup` in namespace `media`.

## Restore

Follow the [isolated restore procedure](/kubernetes/cluster/kopiur/README.md#isolated-restores)
with application `sonarr` in namespace `media`. Restore from the `sonarr-offsite`
repository into a new PVC after verifying completed replication.

Verify the restored archive, then follow [Sonarr's restore instructions](https://wiki.servarr.com/sonarr/faq#how-do-i-backuprestore-my-sonarr).
Block outbound traffic before starting a recovery test so it cannot contact live
indexers or download clients. Keep the test instance away from managed media.
