# Home Assistant and Zigbee backups

Use completed Home Assistant native archives and Zigbee2MQTT's native export.
The Zigbee export includes device and coordinator recovery data, configuration,
custom extensions, and Kubernetes-injected settings. Logs and firmware are excluded.
Scheduling, file selection, and Kopia retention are configured in the manifests.
Each workflow backs up to the NAS, verifies retained files locally, then replicates
the encrypted repository to S3. Repository replication mirrors the primary repository, including retention changes.
Its hourly schedule is separate from the snapshot schedule.

Keep Home Assistant's emergency kit outside the cluster. Its archive encryption
key is separate from the Kopia password. Backup archives and recovered settings
contain credentials and must remain private.

## Home Assistant retention

Set native automatic backup retention to three copies without an agent override
that keeps extra copies. Kopia retains the latest three snapshots. If more than
three native archives exist, review manual backups before running the source:
Home Assistant's automatic retention does not remove manual backups.

Kopia snapshot retention does not cap storage bytes. Run repository maintenance
to reclaim expired data; see [Kopia's maintenance guide](https://kopia.io/docs/advanced/maintenance/).

## Backup

Kopiur schedules are defined in `kopiur.yaml`. Home Assistant creates its native
backup first; the pre-backup Job validates and stages only the newest completed
archive on a dedicated export PVC. The source must contain one to three native
archives, none being written, and the newest must be less than 30 hours old.
Kopiur never reads the live recorder database.

Zigbee's pre-backup Job requests and validates a fresh native export before its
snapshot. Follow the [manual backup procedure](/kubernetes/cluster/kopiur/README.md#manual-backups)
with policy `home-assistant-backup` or `zigbee2mqtt-backup` in namespace
`home-assistant`. Pause snapshots through GitOps with
`SnapshotSchedule.spec.schedule.suspend: true`.

## Restore

Follow the [isolated restore procedure](/kubernetes/cluster/kopiur/README.md#isolated-restores)
with application `home-assistant` or `zigbee2mqtt` in namespace `home-assistant`.
Use the application's read-only `APPLICATION-offsite` repository and a new PVC after verifying completed
replication. Verify the restored archives before following the application's
recovery procedure. Home Assistant needs the saved
emergency key. Keep Zigbee recovery tests disconnected from the live coordinator.

References:

- [Home Assistant backups](https://www.home-assistant.io/integrations/backup/)
- [Zigbee2MQTT native backup](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html#zigbee2mqttbridgerequestbackup)
