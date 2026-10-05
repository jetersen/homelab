# Notifications

VMAlert evaluates infrastructure rules and VMAlertmanager groups warning and
critical alerts, including recovery messages. Chaski formats them and sends each
message independently to Home Assistant and Gotify. Home Assistant delivers
Android push through its Companion app; Gotify stores the message inbox on a
retained PVC. Gotify's Android app is optional.

Existing rules cover Flux failures, unhealthy workloads, failed Jobs, failed and
stale backups, offsite replication, and cluster upgrades. Rule thresholds remain
in the monitoring stack. Watchdog, InfoInhibitor, and informational alerts do not
notify the phone. Alertmanager groups new alerts for 30 seconds, sends group
changes at five-minute intervals, and repeats ongoing alerts every 12 hours.
A resolved alert means its expression stopped firing; deleting a failed Job can
also resolve its alert.

Flux sends HelmRelease events to Chaski. Only successful installs, upgrades, and
rollbacks produce activity notifications. Routine reconciliations are filtered
out; deployment failures use the monitoring rules to avoid duplicate messages.
Forgejo and TrueNAS event sources are not enabled.

## Android and desktop

The Home Assistant script sends notifications to the configured Companion device
and creates a desktop persistent notification. Android uses separate channels for
warnings, critical alerts, and quiet activity/recoveries. Configure sounds and
Do Not Disturb behavior in Android's channel settings. Notifications carry
Kubernetes or Flux avatars, severity colors, and Grafana, Inbox, and History
buttons. Repeated messages update the same phone/desktop notification; Gotify
keeps each received message separately.

Open `https://gotify.jetersen.dev` for the complete alert/activity inbox without
subscribing to individual senders. Account and application credentials are
provisioned privately and stored in encrypted Kubernetes Secrets. Registration
is disabled. The endpoint uses the LAN/Tailscale gateway, not the public tunnel.
Grafana and Gotify links require LAN/Tailscale access away from home; Google push
delivery itself does not require a connection to the cluster from the phone.

Grafana's **Homelab alerts** dashboard shows current alerts and their historical
states from VictoriaMetrics, with a namespace filter. Its Alertmanager data
source provides active notification groups and silences. Rules, routing and
templates remain managed through manifests. State history follows VictoriaMetrics
retention; it is different from Gotify's archive of message text. Gotify messages
remain until deleted and require storage capacity planning and backups if their
history must survive loss of the node or PVC.

## Configuration

- Alert routing and repeat intervals: `../victoria-metrics/app/helmrelease.yaml`.
- Message formatting, priorities, destinations and activity filters: `app/chaski.yaml`.
- Flux event sources and webhook authentication: `events/`.
- Gotify server and persistence: `app/gotify.yaml`.
- Home Assistant delivery: `../../apps/home-assistant/home-assistant/notifications.yaml`.
- Grafana provisioning and dashboard: `../grafana/app/`.

Home Assistant mounts the notification script as a GitOps package. Its persistent
`configuration.yaml` must contain:

```yaml
homeassistant:
  packages: !include_dir_named gitops-packages
```

Merge this into an existing `homeassistant` mapping rather than creating a second
one. After changing the package, reload scripts or restart Home Assistant. Update
the script's `notify.mobile_app_*` action when changing the destination phone.
Chaski calls the script synchronously with a bearer token. Gotify uses separate
application tokens for alerts and activity.

Chaski exposes health checks and delivery metrics. The blackbox exporter probes
Chaski and Gotify; Home Assistant has its existing service probe. Alertmanager's
delivery-failure rules remain enabled. Chaski is stateless and has bounded retries,
so Gotify archives delivered messages but does not act as a durable relay queue.
Retries can produce duplicate inbox entries.

All components run in the homelab cluster. A cluster or home-network outage
requires an external heartbeat monitor and independent delivery channel.
