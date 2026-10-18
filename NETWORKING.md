# Networking

Use maintained configuration for deployed addresses, routes, and access rules.
This document covers constraints for changing network boundaries. Do not create
separate inventories or operational audits unless explicitly requested.

## Application and remote access

Gateway authorization does not protect direct access to backend Pod addresses;
workload policy is a separate control. Check IPv4 and IPv6 routes, source
addresses, and return paths together. See [Talos networking](kubernetes/talos/README.md).

Keep ICMP Packet Too Big feedback working across lower-MTU tunnels. Matching a
LAN MTU does not raise a tunnel's MTU. Validate both address families after changes.

Prefer direct Tailscale connections to enrolled hosts. Advertise narrow host or
service routes for destinations without a client. Route approval establishes
reachability; tailnet grants establish permission. Subnet routers may translate
source addresses, so check the observed source before writing allowlists. See
[Tailscale subnet routers](https://tailscale.com/docs/features/subnet-routers).

Neither tailnet policy nor VLAN placement replaces restrictions on LAN-facing
services. Ordinary SSH over Tailscale uses the destination's existing SSH server
and authentication; Tailscale SSH is a separate authentication option.

## DNS and filtering

Keep bootstrap DNS independent of workloads running on the node being bootstrapped.
Zone replication and blocking configuration are separate concerns; matching
internal records does not imply matching blocklists. See
[CoreDNS](kubernetes/cluster/coredns/README.md) and
[DNSControl](infrastructure/dns/README.md) for configuration requirements.

Do not rely on DHCP or Tailscale resolver order as strict failover. Use resolvers
with equivalent filtering when filtering must survive fallback. Split DNS for
internal domains alone does not filter other queries. See
[Tailscale DNS behavior](https://tailscale.com/docs/reference/dns-in-tailscale).

Allow DNS over both UDP and TCP. Restrictions on ports 53 and 853 do not cover
DNS over HTTPS or DNS carried through a VPN. Avoid forwarding loops and verify
both internal resolution and filtering after changing resolver paths.

## Kubernetes policy and additional interfaces

Introduce restrictions per application, allowing its gateway, DNS, dependencies,
monitoring, and required external access. Verify the configured enforcement mode
and inspect flows before enforcement. See
[Cilium policy enforcement](https://docs.cilium.io/en/stable/security/policy/intro/).

L3/L4 policies cannot distinguish HTTPS hostnames sharing a listener. Pod egress
policy does not restrict node-mounted storage, and network policy does not make
privileged CI workers safe for untrusted workflows. Validate application
authentication separately from TCP listener availability.

Use additional interfaces only when direct attachment is required; routed access
does not require Multus. Verify policy coverage for every interface. Policy on the
primary Cilium interface does not automatically protect secondary interfaces.
Keep default routes and DNS on the primary network, and restrict application
listeners on secondary networks. See
[Multus on Talos](https://docs.siderolabs.com/kubernetes-guides/cni/multus) and
[Home Assistant setup constraints](kubernetes/apps/home-assistant/README.md).

A VLAN separates Layer 2 networks; routed firewall rules do not restrict traffic
within a VLAN. Use supported switch/AP isolation or host firewalls where needed.
IoT validation must cover gateway management and DNS as well as other VLANs.
Test device-specific exceptions from another client to verify their scope. See
[UniFi's isolation layers](https://help.ui.com/hc/en-us/articles/18965560820247-Implementing-Network-and-Client-Isolation-in-UniFi).

## Discovery and wake-on-LAN

mDNS discovery, application connections, and wake-on-LAN require separate paths.
An mDNS proxy does not relay wake-on-LAN broadcasts. Permit the required application
connections after discovery. See
[UniFi mDNS](https://help.ui.com/hc/en-us/articles/12648701398807-UniFi-Gateway-Multicast-DNS-mDNS-Proxy)
and [Home Assistant wake-on-LAN](https://www.home-assistant.io/integrations/wake_on_lan/).

Use subnet-specific broadcast addresses. A generic broadcast follows the sender's
selected route. Before separating a wake target from its sender, provide a tested
wake path, such as a narrowly authorized relay or a dedicated sender interface.
An ordinary UDP allow rule does not establish directed broadcast forwarding.
Test after a long sleep as well as immediately after shutdown.

When changing a boundary, verify allowed and denied connections from each affected
network, both address families, remote access, DNS filtering and fallback,
discovery, and device control. Preserve a working management path for rollback.
