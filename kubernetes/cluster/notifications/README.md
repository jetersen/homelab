# Notifications

VMAlertmanager sends infrastructure alerts through Chaski to Home Assistant and
Gotify. Home Assistant delivers Android push and desktop notifications; Gotify
keeps the message inbox. Flux uses Chaski for successful installs, upgrades, and
rollbacks. Monitoring rules handle deployment failures to avoid duplicate messages.

## Delivery and history

Configure sounds and Do Not Disturb behavior in Android's warning, critical, and
activity/recovery channels. Repeated messages update the same phone and desktop
notification; Gotify keeps each received message separately.

Open `https://gotify.jetersen.dev` for the inbox and Grafana's Homelab alerts
dashboard for alert state history. Both require LAN or Tailscale access. Android
push delivery does not require the phone to connect to the cluster.

A resolved alert means its expression stopped firing; deleting a failed Job can
also resolve its alert. Select pending states in Grafana to investigate conditions
that cleared before notification. Grafana history follows VictoriaMetrics
retention; Gotify messages remain until deleted and need backups if their history
must survive loss of the PVC.

## Home Assistant setup

Add this to persistent `configuration.yaml`, merging any existing `homeassistant`
mapping:

```yaml
homeassistant:
  packages: !include_dir_named gitops-packages
```

Reload scripts or restart Home Assistant after changing the package. Update its
`notify.mobile_app_*` action when replacing the destination phone.

## Configuration

- [Alert routing and intervals](../victoria-metrics/app/helmrelease.yaml)
- [Chaski formatting, destinations, and activity filters](app/chaski.yaml)
- [Flux event sources and authentication](events/)
- [Gotify persistence](app/gotify.yaml)
- [Home Assistant delivery](../../apps/home-assistant/home-assistant/notifications.yaml)
- [Grafana dashboards](../grafana/app/)

Chaski has bounded retries and no durable queue. Retries can duplicate inbox
entries; Gotify only archives delivered messages. All components run in the
homelab, so cluster or home-network outages need an external heartbeat monitor
and independent delivery channel.
