# Home Assistant

## Setup constraints

See the [deployment](home-assistant/helmrelease.yaml) and
[network attachments](home-assistant/network.yaml) for runtime and networking
configuration. Keep reserved interface addresses outside dynamic allocation pools.
Integrations requiring raw sockets or extra capabilities are unavailable in the
rootless container.

Configure the MQTT integration with the broker's Kubernetes Service address.

Select `lan0` and `iot0` in Settings > System > Network and restart Home Assistant
after changing the selection. Automatic detection follows the primary pod's
multicast route. Secondary macvlan interfaces bypass Cilium policy and the routed
firewall. Under Settings > System > Network > HTTP server, bind only to loopback
and the pod hostname `home-assistant` to keep the web UI off those interfaces
while preserving Service access and kubelet probes. See the
[networking overview](../../../NETWORKING.md) for access constraints.

Configure Wake-on-LAN targets with their subnet's broadcast address on UDP port `9`.
The generic `255.255.255.255` broadcast follows Cilium's primary interface;
selecting discovery interfaces does not change that route.

## CO2 ventilation

The [ventilation package](home-assistant/co2_ventilation.yaml) combines independent
humidity, CO2, and timed manual demand. The Bathroom Humidity Exhaust Fan blueprint
must target `input_boolean.humidity_ventilation_demand` as its Fan Switch, with its
bypass disabled and no physical fan in its targets. The upstream blueprint retains
its humidity thresholds, safeguard, and run-on delays. It continues tracking humidity
during manual and CO2 ventilation; those demands do not restart its cycle.

Only the controller should operate the physical fan. See the package for demand
handling, entity mappings, thresholds, timers, and safety limits.

## KVM certificate delivery

See the [certificate package](home-assistant/glkvm_certificates.yaml) for sync
triggers and the [Certificate](home-assistant/glkvm-certificate.yaml) for issuance.
Keep the KVM hostname resolvable directly to the device so console access does
not depend on Kubernetes ingress during maintenance. Configure Folder watcher
for `/etc/glkvm/tls` with the pattern `..data`, and name its event entity
`event.glkvm_certificate_changed`. Kubernetes replaces this symlink atomically
when the Secret changes. No scheduled sync job is required.

Use a local Network View Only account for the UniFi integration and enable the
KVM client in its tracking options. Restore this integration separately from GitOps.

Preserve the last verified certificate fingerprint in `/config` during recovery;
it permits replacement of an expired but unchanged device certificate. Do not
bypass rejection of an unknown certificate.

Run `shell_command.glkvm_sync_certificate` to retry manually and check Home
Assistant notifications for failures.

Folder watcher requires this entry in the persistent `configuration.yaml`:

```yaml
homeassistant:
  allowlist_external_dirs:
    - /etc/glkvm/tls
```

Keep the existing package configuration under the same `homeassistant` mapping.
