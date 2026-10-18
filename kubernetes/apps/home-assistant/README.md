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
binds only to loopback and the pod hostname `home-assistant`, which resolves to
its Cilium addresses. Configure those hosts under Settings > System > Network >
HTTP server; the pod hostname keeps Service access and kubelet probes working
after pod replacement. Access the web UI through the Kubernetes Service and
Envoy HTTPRoute. Port `8123` does not listen on either secondary LAN interface.
See the [networking overview](../../../NETWORKING.md).

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

The controller owns the physical fan and combines independent demands. Manual
modes take priority and persist across restarts. Timed manual demand can end
without stopping active humidity or CO2 demand. The reason sensor reports active
demands and flags an unexplained on state. See the package for entity mappings,
thresholds, timers, and safety limits.

## KVM certificate delivery

cert-manager issues a dedicated Let's Encrypt certificate for the KVM.
Internal DNS resolves its configured hostname directly to the device,
so console access does not depend on the Kubernetes ingress during maintenance.
The Certificate and its TLS Secret live in Home Assistant's namespace and are
managed alongside the application. The KVM administrator password is stored in a
separate SOPS-encrypted Secret.

The [certificate package](home-assistant/glkvm_certificates.yaml) synchronizes
the certificate when the configured device tracker reports the KVM online,
when Home Assistant starts, and when Folder watcher detects a change to the
mounted TLS Secret. Configure Folder
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
