# Home Assistant and Zigbee recovery pilots

Prepared locally on 2026-10-03. Nothing in this directory has been deployed.
Both ReplicationSources are paused and the export CronJob is suspended. Deployment,
manual backups and restores need the user's separate approval. No nightly backup
or maintenance schedule is active.

## What is preserved

| Application | Backup input | Excluded |
| --- | --- | --- |
| Home Assistant | Completed `/config/backups/*.tar` native archives, at least five minutes old | Everything outside those archives, temporary files and nested directories |
| Zigbee2MQTT | A validated native export in a separate staging PVC | `log/`, `ota/`, migration logs and temporary files |

Home Assistant 2026.9.4 already produces encrypted daily archives. Read-only
inspection found three complete archives totaling approximately 168 MiB. Its
installed native backup code excludes logs, `.cache`, Python caches, TTS cache,
and nested backup archives. It preserves application configuration, including
hidden `.storage`; recorder history follows the native backup settings. The user
confirmed the Home Assistant emergency kit/encryption key is saved outside the
cluster. That key is separate from the Kopia repository password. Kopia cannot
change the contents of an already encrypted Home Assistant archive.

Read-only inspection of Zigbee2MQTT 2.14.2 found five recovery files totaling
39,038 bytes, versus 82,522,688 bytes of logs. The native MQTT backup request
refreshes the coordinator backup before creating the ZIP. The exporter verifies
`configuration.yaml`, `database.db`, `coordinator_backup.json`, and `state.json`,
preserves configuration backups and custom converters/extensions, and removes
logs, downloaded firmware and temporary files. It adds `deployment-environment.json`
with the Kubernetes-injected network and MQTT settings needed for recovery.
Keep that file private; it contains secrets. The exporter uses the same pinned
image digest as the inspected workload and the existing `zigbee2mqtt` Secret.
It has no Kubernetes API access and no direct connection to the coordinator.

Exports replace the staging ZIP atomically only after validation. The mover
rejects a Zigbee export older than one hour. Staging data remains plaintext on
the node, like the original Zigbee data. Kopia encrypts it before uploading.
Do not run a new export while a mover is copying the previous ZIP. The manual
pilot explicitly waits for the exporter to complete before triggering Kopia.

## Repository and file selection

Separate repositories use `pilot/home-assistant/` and `pilot/zigbee2mqtt/` within
`jetersen-homelab-kopia`. Identities are `home-assistant@homelab:/data` and
`zigbee2mqtt@homelab:/data`. Each future repository will need its own maintenance
owner. Both use the external Proton Pass Kopia password and scoped S3 credential.
Connection manifests are SOPS-encrypted with the existing Flux age recipient.

The pinned VolSync CRD has no `sourcePath` selector. `sourcePathOverride` changes
snapshot identity, not the files read. The mover mounts the whole source PVC at
`/data`; `copyMethod: Direct` provides no filesystem snapshot. The mount is not
forced read-only by the controller. The reviewed action only reads source files
and imports a policy into the remote repository.

Kopia's `policy set --add-ignore` sorts rules and breaks these inclusion rules.
`check-source.sh` imports the ordered policy and checks it before uploading.
Local `.kopiaignore` files at the backup root or archive directory cause failure.
Policies retain 14 daily, eight weekly and six monthly snapshots, plus the latest
snapshot; hourly and annual retention are zero. Read errors cause failure.
Local tests run the pinned mover twice and restore its snapshot into a separate
directory, verifying byte-for-byte archive recovery and exclusion of unrelated files.
These tests do not prove an encrypted Home Assistant archive can be decrypted or
that a replacement coordinator can restore the Zigbee network.

## Deployment and manual pilot

After approval, commit and push the reviewed GitOps changes. Wait for `volsync`
and `home-assistant-backup` Flux Kustomizations to become Ready. Run all cluster
commands with context `homelab`.

Temporarily suspend only the backup Kustomization so Flux cannot overwrite manual
pilot patches. Always restore it afterward, including when a job fails:

```bash
kubectl --context homelab -n flux-system patch kustomization home-assistant-backup \
  --type merge -p '{"spec":{"suspend":true}}'
kubectl --context homelab -n home-assistant create job zigbee-backup-export-pilot-1 \
  --from=cronjob/zigbee-backup-export
kubectl --context homelab -n home-assistant wait --for=condition=complete \
  job/zigbee-backup-export-pilot-1 --timeout=240s
kubectl --context homelab -n home-assistant patch replicationsource zigbee2mqtt-backup \
  --type merge -p '{"spec":{"paused":false}}'
kubectl --context homelab -n home-assistant patch replicationsource home-assistant-backup \
  --type merge -p '{"spec":{"paused":false}}'
```

Do not proceed on export failure. Wait for each source's `status.lastManualSync`
to equal `pilot-1`, confirm its mover succeeded, and inspect repository inventory.
Do not print decrypted secrets, archive contents, MQTT responses or configuration.
Record snapshot IDs, completion timestamps, file inventory and archive hashes
without recording credentials or device/network identifiers.

Pause both sources after the pilot and resume the backup Kustomization:

```bash
kubectl --context homelab -n home-assistant patch replicationsource zigbee2mqtt-backup \
  --type merge -p '{"spec":{"paused":true}}'
kubectl --context homelab -n home-assistant patch replicationsource home-assistant-backup \
  --type merge -p '{"spec":{"paused":true}}'
kubectl --context homelab -n flux-system patch kustomization home-assistant-backup \
  --type merge -p '{"spec":{"suspend":false}}'
```

## Isolated restore

The helper performs read-only cluster checks. It refuses an incomplete manual
backup or an existing destination PVC/ReplicationDestination. It requires an
explicit RFC3339 cutoff between pilot completion and now. The pinned mover
restores the newest snapshot at or before that cutoff, not a specified snapshot
ID. Confirm the selected ID in mover output matches the pilot before acceptance.

```bash
python infrastructure/backup/prepare-pilot-restore.py home-assistant \
  --as-of EXPLICIT_RFC3339_TIMESTAMP > /tmp/home-assistant-pilot-restore.yaml
kubectl --context homelab apply -f /tmp/home-assistant-pilot-restore.yaml
```

Repeat for `zigbee2mqtt`. Each creates a fresh 1 GiB local-path PVC named
`APPLICATION-kopia-pilot-restore`. Neither points at a live application PVC.
Validate recovered archives from a temporary pod with a read-only mount, compare
their hashes with the source/export, and parse only selected metadata. Do not
start Zigbee2MQTT or connect a restored workload to the live coordinator. Verify
the Zigbee archive contains valid device/coordinator data and deployment overrides,
with no logs or firmware. A complete Home Assistant application recovery still
requires its saved emergency key and an isolated application restore test.

The export staging PVC has Flux pruning disabled to avoid deleting its contents
when manifests are reorganized. Test PVC/pod cleanup and repository deletion need
exact-target checks; restoring these pilots does not authorize production restores.

## Before enabling automation or expanding

Prove fresh-client repository access, application recovery, pruning/maintenance,
and failed/stale backup alerts. Couple successful Zigbee export completion to its
Kopia trigger; simply enabling two independent cron schedules could upload old data.
Check each additional application's native export or stopped-writer consistency
method and distinguish recoverable state from logs, caches and downloaded assets.

References:

- [Zigbee2MQTT native backup request](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html#zigbee2mqttbridgerequestbackup)
- [Home Assistant backups](https://www.home-assistant.io/integrations/backup/)
- [Kopia ignore rules](https://kopia.io/docs/advanced/kopiaignore/)
- [Kopia rule ordering issue](https://github.com/kopia/kopia/issues/3814)
