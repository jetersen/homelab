# Home Assistant and Zigbee backup procedures

Flux manages manual Kopia sources for completed Home Assistant native archives
and validated Zigbee2MQTT exports. Source pause flags, export scheduling, retention,
repository connections, and image versions are declared in the manifests.

## Backup inputs

Home Assistant selection includes completed `/config/backups/*.tar` archives at
least five minutes old, excluding temporary files and nested directories. Preserve
the native emergency kit/encryption key outside the cluster. That key is separate
from the Kopia password; transporting an encrypted archive does not prove it can
be decrypted or booted.

The Zigbee exporter requests a native MQTT backup to refresh coordinator state.
It validates configuration, device database, coordinator backup, and state,
preserves custom converters/extensions, and excludes logs, firmware, and temporary
files. `deployment-environment.json` captures Kubernetes-injected MQTT/network
settings and contains secrets. Keep exports and recovered contents private.

The staging ZIP is replaced atomically after validation. Movers reject exports
older than one hour. Staging remains plaintext on the node; Kopia encrypts uploads.
Wait for export completion before triggering a mover, and avoid overlapping exports
and copies.

## File selection

The mover mounts the whole PVC at `/data`; `copyMethod: Direct` does not create
a filesystem snapshot or force a read-only mount. `sourcePathOverride` changes
snapshot identity, not file selection. `check-source.sh` imports an ordered policy
and verifies effective selection and retention, including inherited overrides.

Do not use `policy set --add-ignore` for these inclusion rules: it sorts rules.
Unexpected `.kopiaignore` files cause the guard to fail. Offline mover tests cover
selection, retention, and file restoration, but do not prove native application
or replacement-coordinator recovery.

## Manual backup

Keep manual source activation in Git so parent Flux reconciliation cannot undo
an imperative child suspend patch. For Zigbee, keep the export CronJob suspended,
create a uniquely named manual Job, and wait for completion:

```bash
kubectl --context homelab -n home-assistant create job zigbee-backup-export-UNIQUE_TRIGGER \
  --from=cronjob/zigbee-backup-export
kubectl --context homelab -n home-assistant wait --for=condition=complete \
  job/zigbee-backup-export-UNIQUE_TRIGGER --timeout=240s
```

Do not proceed on export failure. Commit `paused: false` and a new manual trigger
for the selected ReplicationSource. Require `status.lastManualSync` to match that
trigger and `latestMoverStatus.result: Successful`, then inspect repository
inventory. Timestamps alone do not prove a mover ran. Commit `paused: true` again
when the manual run finishes. Do not print decrypted secrets, archive contents,
MQTT responses, or configuration. Keep snapshot IDs, timestamps, inventory,
and hashes in protected private records.

## Isolated restore

The helper checks the cluster read-only, requires a successful manual backup,
and refuses an existing destination PVC or ReplicationDestination. Supply an
explicit RFC3339 cutoff between backup completion and now. The pinned mover
selects the newest snapshot at or before the cutoff; it does not select by
snapshot ID. Confirm the chosen recovery point independently because mover log
tails may omit its ID.

```bash
python infrastructure/backup/prepare-pilot-restore.py home-assistant \
  --as-of EXPLICIT_RFC3339_TIMESTAMP > /tmp/home-assistant-pilot-restore.yaml
kubectl --context homelab apply -f /tmp/home-assistant-pilot-restore.yaml
```

Repeat for `zigbee2mqtt` only after authorizing that restore. Each target is a
separate 1 GiB PVC, never the live application PVC. If a target exists, review
its exact contents and cleanup separately; the helper will not overwrite it.

Validate restored archives from a temporary pod with a read-only mount. Compare
hashes and selected metadata privately, then test native application recovery in
isolation. Home Assistant needs its saved emergency key. Do not start Zigbee2MQTT
against the live coordinator; replacement-coordinator recovery is a separate test.
The export staging PVC has Flux pruning disabled. Test-resource cleanup and
repository deletion require exact-target checks.

Before automation, verify fresh-client access, application recovery, maintenance,
pruning, and failed/stale alerts. Couple export success to the Kopia trigger;
independent schedules can upload stale data.

References:

- [Zigbee2MQTT native backup request](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html#zigbee2mqttbridgerequestbackup)
- [Home Assistant backups](https://www.home-assistant.io/integrations/backup/)
- [Kopia ignore rules](https://kopia.io/docs/advanced/kopiaignore/)
- [Kopia rule ordering issue](https://github.com/kopia/kopia/issues/3814)
