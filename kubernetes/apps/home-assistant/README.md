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
Multus attaches `lan0` directly to the main LAN for zeroconf and SSDP discovery;
see [the attachment](home-assistant/network.yaml) for its reserved IP and MAC.
Keep that address outside DHCP and other allocation pools. The attachment is
exclusive to Home Assistant's single replica on `talos01` and adds no default
route; router advertisements cannot add an IPv6 default route on `lan0`.

Select only `lan0` in Settings > System > Network and restart Home Assistant
after changing the selection. Automatic detection follows the primary pod's
multicast route. Cilium policy covers only the primary interface, and macvlan
cannot directly reach its parent host. A short-lived init container uses
`NET_ADMIN` to route the node's IPv4 address through the primary Cilium gateway,
so kubelet probe replies keep working. Home Assistant itself keeps all Linux
capabilities dropped. Keep IoT wake traffic on the [wake relay](wol-relay/README.md).
See the [networking overview](../../../NETWORKING.md).

Configure main-LAN Wake-on-LAN targets with the LAN subnet's broadcast address.
The generic `255.255.255.255` broadcast follows Cilium's primary interface;
selecting `lan0` for discovery does not change that route.

## CO2 ventilation

The [CO2 package](home-assistant/co2_ventilation.yaml) controls
`input_boolean.co2_ventilation_demand` from the bedroom AIR sensor. Select
`input_boolean.ventilation_fan_override` as the existing Bathroom Humidity
Exhaust Fan blueprint's Bypass Switch, using "Keep the current fan state".
Disable bypass auto-off and leave the
"Turn the fan OFF when bypass clears" extra option unselected so humidity
control resumes when CO2 demand ends. The upstream blueprint remains unchanged.

Use `input_select.ventilation_fan_mode` to select Auto, Always on, or Always off.
The manual modes take priority over both CO2 and humidity control and persist
across restarts. Auto gives CO2 demand priority, then returns control to the
humidity blueprint. The override automation holds the selected fan state while
the blueprint bypass prevents conflicting humidity actions.

Press `button.ventilation_fan_add_hour` for timed manual ventilation. Each press
adds an hour to the active timer and selects Auto mode. Cancel
`timer.ventilation_fan_manual_run` to end it early. Automatic control resumes
afterward; without usable bathroom humidity feedback, the released override
turns the fan off unless CO2 demand still requires it. Assign the button, timer,
and mode selector to Utility Closet for its area controls.

Demand starts after ten minutes above 1,000 ppm and clears after ten minutes
below 800 ppm, or five minutes without usable sensor readings. Each CO2 override
is limited to one hour, followed by a one-hour cooldown after a timeout. Restored
deadlines and periodic reconciliation cover restarts and missed transitions.
With usable humidity feedback, clearing the bypass allows the blueprint's
humidity timeout and run-on delay to finish; the override limit is not a hard
limit on total fan runtime.

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
