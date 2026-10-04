# Notifications

VMAlertmanager sends warning and critical alerts directly to ntfy. Existing
VictoriaMetrics rules cover Flux failures, unhealthy workloads, failed Jobs,
backup failures, stale backups, offsite replication, and cluster upgrades.
Rule thresholds and pending durations remain defined by the monitoring stack.
Watchdog, InfoInhibitor, and other informational alerts do not notify the phone.

The `homelab-alerts` topic receives grouped alerts and recovery messages.
Warnings use normal priority, critical alerts use maximum priority, and
recoveries use low priority. Alertmanager waits 30 seconds to group new alerts,
sends group changes at five-minute intervals, and repeats ongoing alerts every
12 hours. A resolved alert means its expression stopped firing; for failed Jobs,
this can also happen when Kubernetes deletes the Job.
Alerts show a Kubernetes icon and Helm activity shows a Flux icon. The Android
client downloads these PNGs from the Dashboard Icons collection on jsDelivr.

Flux sends HelmRelease events through the internal Chaski webhook. Chaski
forwards only successful installs, upgrades, and rollbacks to the low-priority
`homelab-activity` topic. Routine reconciliations are filtered out. Deployment
failures reach the alert topic through VMAlertmanager, avoiding duplicate event
notifications. Forgejo events are not enabled.

## Phone setup

Install the ntfy Android app, add `https://ntfy.jetersen.dev` with the provisioned
read-only user, and subscribe to `homelab-alerts`. Subscribe to
`homelab-activity` only if deployment activity is useful. Permit notification and
background access, then test delivery with the screen locked on mobile data.
The endpoint uses the existing LAN/Tailscale gateway and is not published through
the public tunnel. Tailscale must remain connected away from the LAN.

ntfy retains messages for seven days on its PVC. Login credentials, publisher
tokens, and topic permissions are provisioned from SOPS-encrypted Secrets.
The phone user can read both topics; Alertmanager and Chaski can publish only
to their respective topics. Anonymous access and self-registration are disabled.

## Configuration

- Alert routing and repeat intervals: `../victoria-metrics/app/helmrelease.yaml`.
- Message content and priority: `app/alertmanager-template.yml`.
- Activity filters and formatting: `app/chaski.yaml`.
- Flux event sources and webhook authentication: `events/`.
- Server settings and persistence: `app/ntfy.yaml`.

Chaski exposes health checks and metrics, and the existing blackbox exporter
probes both services. Alertmanager's delivery-failure rules remain enabled.
All components run in the homelab cluster, so a cluster or home-network outage
requires a separate external heartbeat monitor and delivery channel.
