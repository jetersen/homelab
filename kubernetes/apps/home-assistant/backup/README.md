# Home Assistant and Zigbee backups

Backups use completed Home Assistant native archives and Zigbee2MQTT's native
export, including coordinator recovery data and Kubernetes-injected settings.

Keep Home Assistant's emergency kit outside the cluster. Its archive encryption
key is separate from the Kopia password.

## Backup

Configure Home Assistant's native automatic backup retention to three copies,
without an agent override that keeps extra copies. The staging job accepts one
to three native archives at least five minutes old and stages the newest, which
must be less than 30 hours old. Review manual backups if the count exceeds three;
Home Assistant's automatic retention does not remove them.

Zigbee's pre-backup job requests and validates a fresh native export. Follow the
[manual backup procedure](/kubernetes/cluster/kopiur/README.md#manual-backups)
with policy `home-assistant-backup` or `zigbee2mqtt-backup` in namespace
`home-assistant`.

## Restore

Follow the [isolated restore procedure](/kubernetes/cluster/kopiur/README.md#isolated-restores)
with application `home-assistant` or `zigbee2mqtt` in namespace `home-assistant`.
Use the application's read-only `APPLICATION-offsite` repository after verifying
completed replication. Verify the restored archives before following the
application's recovery procedure. Home Assistant needs the saved emergency key.
Keep Zigbee recovery tests disconnected from the live coordinator.

- [Home Assistant backups](https://www.home-assistant.io/integrations/backup/)
- [Zigbee2MQTT native backup](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html#zigbee2mqttbridgerequestbackup)
