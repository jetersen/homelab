# Direct tailnet access

Envoy is exposed by the Tailscale operator through annotations on its generated
Service, configured in [EnvoyProxy](../envoy-gateway/config/envoy.yaml). The LAN
VIP remains `192.168.1.20`. The operator's `envoy` device is `100.99.86.238` and
uses `tag:k8s`. TCP HTTPS and UDP HTTP/3 both reach the existing Envoy listeners
with the original application hostnames and certificates.

The `envoy-ingress` ProxyClass sets `TS_TUN_DISABLE_UDP_GRO=true`. Without this,
coalesced QUIC packets entering the kernel TUN were oversized and HTTP/3
connections intermittently stalled. Keep this setting scoped to Envoy's proxy.

The Kubernetes Service is IPv4-only. Do not publish the proxy's Tailscale IPv6
address as an application AAAA record until IPv6 forwarding is verified.

## TrueNAS

TrueNAS runs the community Tailscale app, hostname `truenas`, with kernel TUN and
host networking. Authentication state lives in its persistent `state` ixVolume.
It joined interactively without storing an enrollment auth key in this repo.
`accept_dns`, `accept_routes`, userspace mode, and exit-node advertising are off;
it advertises no subnet routes. `auth_once` is on and `reset` is off.

- IPv4: `100.99.103.178`
- IPv6: `fd7a:115c:a1e0::8937:3e29`
- MagicDNS: `truenas.rockhopper-bleak.ts.net`

The device is user-owned and retains the normal six-month node-key expiry.
Reauthenticate before expiry, or make an explicit decision about server tagging
and key lifetime. Existing tailnet ACL grants apply; this setup did not narrow
those grants. The NAS HTTPS certificate remains self-signed.

## DNS

Tailnet global DNS uses only `100.99.103.178`, with Override DNS servers and
MagicDNS enabled. The NAS resolves independently of Kubernetes. This makes the
NAS the sole configured global resolver for tailnet clients. LAN DHCP retains
the cluster and NAS LAN resolvers.

Technitium's official Split Horizon app version 11 is installed on the cluster
primary and replicated automatically to the NAS secondary. Its active config is
recorded in [tailnet-split-horizon.json](../technitium/tailnet-split-horizon.json).
This is a reference configuration applied through Technitium's API, rather than
a Flux-managed object. Apply future changes to the primary so cluster
replication preserves them.

Only clients in this tailnet's IPv4 allocation or IPv6 ULA range have answers
containing `192.168.1.20` translated to `100.99.86.238`. LAN answers retain the
VIP. Leave `domainGroupMap` empty: a domain mapping takes precedence over the
source-network mapping and could translate LAN answers too. Existing zone
records, public answers, and reverse lookups stay unchanged.

The NAS Technitium custom app uses `network_mode: host` to preserve DNS client
source addresses. Docker bridge port forwarding changed tailnet client sources
to the bridge gateway and prevented source-based translation. Host networking
requires removing published `ports` and the container-local
`net.ipv4.ip_local_port_range` sysctl; do not change the NAS host's sysctl.
Image, environment, credentials, volumes, hostname, and restart policy are
preserved. Both DNS transport protocols must preserve client sources.

On rocket, DHCP's `lan.jetersen.dev` search domain routes those names to LAN DNS
through systemd-resolved even when Tailscale owns the default DNS route. Those
local queries correctly retain the LAN VIP. Queries through MagicDNS and the
NAS tailnet resolver return the direct Envoy address.

## ExternalDNS

Keep the internal ExternalDNS target on the Gateway's LAN address. Its
Technitium and UniFi instances publish A/AAAA records from
`Gateway.status.addresses`, currently `192.168.1.20`. Technitium translates the
response for tailnet sources after record lookup. Replacing the internal target
with the Tailscale IP would replace LAN answers too.

The Cloudflare instance separately publishes opt-in CNAMEs to
`public.jetersen.dev`, which uses the existing public ingress. Do not publish
the Envoy tailnet IP to Cloudflare.

The proxy's identity is persisted in the operator-managed Secret
`ts-envoy-proxy-7hkks-0`, preserving its tailnet address across pod restarts.
If that identity is deleted and a new device receives another address, update
the Split Horizon mapping on the primary and this reference file. ExternalDNS
does not maintain the DNS app's translation configuration.

## Remaining subnet route

The existing `homelab-subnet-router` still advertises `192.168.1.0/24`. Direct
Envoy and NAS access no longer require it, but Kubernetes/Talos administration
still uses LAN endpoints. Migrate and verify those paths before removing the
Connector or route approval.

## Verification

Run cluster commands with context `homelab`. Verify Service `TailscaleProxyReady`
and the proxy pod's readiness, then compare DNS over UDP and TCP:

```sh
dig @100.99.103.178 home.jetersen.dev A
dig +tcp @100.99.103.178 jellyfin.lan.jetersen.dev A
dig @192.168.1.2 home.jetersen.dev A
dig @fd7a:115c:a1e0::8937:3e29 example.com A
tailscale dns status
tailscale dns query home.jetersen.dev
curl --http2 --max-time 20 https://home.jetersen.dev/ -o /dev/null
```

Expect the tailnet resolver to return `100.99.86.238`, the LAN resolver to return
`192.168.1.20`, and public recursion to succeed. Test HTTP/3 repeatedly with TLS
verification, plus the LAN VIP, when changing the operator or Envoy networking.
