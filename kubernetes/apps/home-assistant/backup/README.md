# Home Assistant and Zigbee backups

Use completed Home Assistant native archives and Zigbee2MQTT's native export.
The Zigbee export includes device and coordinator recovery data, configuration,
custom extensions, and Kubernetes-injected settings. Logs and firmware are excluded.
Scheduling, file selection, and Kopia retention are configured in the manifests.
Each workflow backs up to the NAS, verifies retained files locally, then replicates
the encrypted repository to S3. Both destinations share the same retention policy.

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

Schedules are defined in `automation.yaml`. Home Assistant creates its native
backup first; the offsite workflow requires a recent completed archive. To run
an offsite backup manually:

```bash
kubectl --context homelab -n home-assistant create job home-assistant-backup-UNIQUE_TRIGGER \
  --from=cronjob/home-assistant-backup
kubectl --context homelab -n home-assistant wait --for=condition=complete \
  job/home-assistant-backup-UNIQUE_TRIGGER --timeout=3600s
```

Use `zigbee2mqtt-backup` for Zigbee, which exports before uploading. Pause schedules
through GitOps by setting the workflow CronJob's `spec.suspend` to `true`.

## Restore

Restore into a new volume using a cutoff between backup completion and now:

```bash
python infrastructure/backup/prepare-pilot-restore.py home-assistant \
  --as-of EXPLICIT_RFC3339_TIMESTAMP > /tmp/home-assistant-pilot-restore.yaml
kubectl --context homelab apply -f /tmp/home-assistant-pilot-restore.yaml
```

Use `zigbee2mqtt` instead for a Zigbee restore. Verify the restored archives before
following the application's recovery procedure. Home Assistant needs the saved
emergency key. Keep Zigbee recovery tests disconnected from the live coordinator.

References:

- [Home Assistant backups](https://www.home-assistant.io/integrations/backup/)
- [Zigbee2MQTT native backup](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html#zigbee2mqttbridgerequestbackup)
