# Home Assistant

## Runtime

Home Assistant runs as UID 568 from the rootless
[home-operations image](https://github.com/home-operations/containers/tree/main/apps/home-assistant).
Custom integration requirements install into `/config/.venv`, which the image
rebuilds when the Home Assistant version changes. Integrations that need raw
sockets or extra capabilities, such as DHCP discovery or Bluetooth, are
unavailable.

Cilium provides cluster DNS, the default route, and Service access. Configure the
MQTT integration with `mosquitto.home-assistant.svc.cluster.local` on port `1883`.
Multus attaches `lan0` to the main LAN and `iot0` to the IoT VLAN for zeroconf,
SSDP discovery, and direct device access;
see [the attachments](home-assistant/network.yaml) for their reserved IPs and MACs.
Keep those addresses outside DHCP and other allocation pools. The attachments are
exclusive to Home Assistant's single replica on `talos01` and add no default
route; router advertisements cannot add an IPv6 default route on either interface.

Select `lan0` and `iot0` in Settings > System > Network and restart Home Assistant
after changing the selection. Automatic detection follows the primary pod's
multicast route. Cilium policy covers only the primary interface, and macvlan
cannot directly reach its parent host. A short-lived init container uses
`NET_ADMIN` to route the node's IPv4 address through the primary Cilium gateway,
so kubelet probe replies keep working. Home Assistant itself keeps all Linux
capabilities dropped. Both secondary interfaces bypass UniFi's routed firewall;
IoT devices can reach integrations that listen on all addresses. The HTTP server
binds only to `192.168.1.11`, loopback, and the pod hostname `home-assistant`,
which resolves to its Cilium addresses. Configure those hosts under Settings >
System > Network > HTTP server; keep the pod hostname in the list so ingress and
kubelet probes work after pod replacement. Port `8123` does not listen on IoT.
See the [networking overview](../../../NETWORKING.md).

Configure Wake-on-LAN targets with their subnet's broadcast address: `192.168.1.255`
for the main LAN and `192.168.20.255` for IoT, on UDP port `9`.
The generic `255.255.255.255` broadcast follows Cilium's primary interface;
selecting discovery interfaces does not change that route.

## CO2 ventilation

The [ventilation package](home-assistant/co2_ventilation.yaml) combines independent
humidity, CO2, and timed manual demand. The Bathroom Humidity Exhaust Fan blueprint
must target `input_boolean.humidity_ventilation_demand` as its Fan Switch, with its
bypass disabled and no physical fan in its targets. The upstream blueprint retains
its humidity thresholds, safeguard, and run-on delays. It continues tracking humidity
during manual and CO2 ventilation; those demands do not restart its cycle.

Use `input_select.ventilation_fan_mode` to select Auto, Always on, or Always off.
The manual modes take priority and persist across restarts. In Auto, the controller
runs `switch.utility_fan_plug` while any demand remains active. Only this controller
should operate the physical fan. It reacts to demand, mode, and switch changes and
reconciles restored state at startup without periodic polling.

Press `button.ventilation_fan_add_hour` for timed manual ventilation. Each press
adds an hour to the active timer and selects Auto mode. Cancel
`timer.ventilation_fan_manual_run` to end it early. Canceling or finishing the timer
stops a manual-only run immediately; active humidity or CO2 demand keeps the fan
running. Assign the button, timer, and mode selector to Utility Closet for its
area controls.

`sensor.utility_fan_reason` explains the current fan state and lists simultaneous
demands. Bathroom humidity and its run-on delay share one reason, based on the
explicit humidity demand rather than whether an automation is running. An
unexplained on state is reported as unknown. Assign the sensor to Utility Closet
and add it to the dashboard favorites beside the fan controls. Its attributes
include demand states, the manual timer's finish time, and bathroom humidity readings.

CO2 demand starts after ten minutes above 1,000 ppm and clears after ten minutes
below 800 ppm, or five minutes without usable sensor readings. Each CO2 cycle
is limited to one hour, followed by a one-hour cooldown after a timeout. Restored
deadlines fire once for the cutoff and cooldown. These limits apply to CO2 demand;
independent humidity or manual demand can keep the fan running longer.

## KVM certificate delivery

cert-manager issues a dedicated Let's Encrypt certificate for
`glkvm.jetersen.dev`. Internal DNS resolves this hostname directly to the KVM,
so console access does not depend on the Kubernetes ingress during maintenance.
The Certificate and its TLS Secret live in Home Assistant's namespace and are
managed alongside the application. The KVM administrator password is stored in a
separate SOPS-encrypted Secret.

Home Assistant synchronizes the certificate when the UniFi tracker
`device_tracker.glkvm` becomes `home`, when Home Assistant starts, and when
Folder watcher detects a change to the mounted TLS Secret. Configure Folder
watcher for `/etc/glkvm/tls` with the pattern `..data`, and name its event entity
`event.glkvm_certificate_changed`. Kubernetes replaces this symlink atomically
when the Secret changes. No scheduled sync job is required.

The UniFi integration uses a local Network View Only account. Enable the KVM's
specific client in its tracking options. Home Assistant stores this integration
configuration on its persistent volume.

The sync compares the installed certificate before authenticating or uploading.
It verifies trusted HTTPS and the exact issued certificate after installation.
The last verified leaf fingerprint is retained in `/config` so an expired but
unchanged KVM certificate can be replaced after a long period offline. An unknown
certificate is rejected. Uploading reloads the KVM web server without rebooting
the KVM or its controlled computer.

Run `shell_command.glkvm_sync_certificate` to retry manually. Failures create a
persistent Home Assistant notification. A powered-off KVM is skipped; its next
online event retries with the latest certificate.

Folder watcher requires this entry in the persistent `configuration.yaml`:

```yaml
homeassistant:
  allowlist_external_dirs:
    - /etc/glkvm/tls
```

Keep the existing package configuration under the same `homeassistant` mapping.
