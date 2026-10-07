# IoT wake relay

The relay keeps Home Assistant's existing Wake-on-LAN integration usable across
VLANs. Configure the TV's integration options with broadcast address
`wol-relay.home-assistant.svc.cluster.local` and broadcast port `9`. Keep the
existing target MAC and entity so automations continue to work.

The Service delivers UDP to a listener bound only to the primary Cilium address.
The relay accepts exactly the configured target's magic packet and sends it from
its secondary IoT address to the local broadcast address. SecureOn packets are
not supported. The target MAC is stored in a SOPS-encrypted Secret.

Multus attaches a macvlan interface using the Talos VLAN link. Keep that link
without node addresses or DHCP, disable IPv6 on that host link to prevent a
link-local address, permit its tag on the switch path, and reserve
the relay address outside DHCP. The secondary interface has no default route;
IPv4 and IPv6 forwarding are disabled in the pod. The process runs without root,
Linux capabilities, a writable root filesystem, or a Kubernetes API token.

NetworkPolicy restricts the primary interface and denies new outbound
connections there. Home Assistant currently uses host networking, so access from
its node also allows other processes on that node. Secondary LAN traffic is not
covered by that policy; the relay binds no command listener to IoT. Moving Home
Assistant onto its own pod network allows removal of the node-address exception.

Apply the Talos VLAN patch before deploying the relay. Cilium's VLAN filter needs
the link present on the node when it builds its datapath; keep `bpf.vlanBypass`
limited to the required tag. Multus delegates the primary network to Cilium and
installs only the additional macvlan and tuning plugins.

The tuning plugin pins the secondary interface's MAC so UniFi retains its client
alias (`wol-relay-iot`) across pod replacements. The CNI network name is internal
to Kubernetes; host-local IPAM does not send a DHCP hostname. Keep this attachment
exclusive to the single relay replica, since its IP and MAC are fixed.

After changes, verify primary-network DNS, denied relay access from unrelated
pods, disabled forwarding, and wake after sustained TV standby. Allow at least a
minute for the TV to become available in Home Assistant. WiFi isolation or
broadcast filtering can prevent delivery even when the relay sends successfully.
Connect WiFi wake targets to the destination VLAN's SSID. Validate broadcast
delivery separately if using a per-client Virtual Network Override.

Run the packet validation tests with:

```sh
python3 -m unittest discover -s kubernetes/apps/home-assistant/wol-relay
```
