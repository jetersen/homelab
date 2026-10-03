# Direct tailnet access

Envoy's generated Service is exposed through Tailscale operator annotations in
[EnvoyProxy](../envoy-gateway/config/envoy.yaml). TCP HTTPS and UDP HTTP/3 share
its listeners, application hostnames, and certificates.

The `envoy-ingress` ProxyClass sets `TS_TUN_DISABLE_UDP_GRO=true` to prevent
oversized coalesced QUIC packets in the kernel TUN. Keep this setting scoped to
Envoy's proxy. Its Kubernetes Service is IPv4-only; verify IPv6 forwarding before
publishing an application AAAA record.

## DNS and ExternalDNS

[The Split Horizon reference](../technitium/tailnet-split-horizon.json) translates
Envoy's LAN VIP to its tailnet address for the configured tailnet source ranges.
Apply changes through Technitium's primary API so cluster replication preserves
them. This reference is not a Flux-managed object.

Leave `domainGroupMap` empty: domain mappings take precedence over source-network
mappings and can affect LAN answers. Keep internal ExternalDNS targets on the
Gateway's LAN address; translate responses after lookup. Cloudflare separately
publishes opt-in CNAMEs to the public ingress. Do not publish the Envoy tailnet
address through public DNS.

NAS-hosted Technitium needs host networking to preserve DNS client source
addresses. When changing from Docker bridge networking, remove published `ports`
and the container-local `net.ipv4.ip_local_port_range` sysctl. Do not change the
NAS host's sysctl. Preserve image, credentials, volumes, and restart settings.
Both UDP and TCP must retain client source addresses.

The operator-managed proxy Secret persists Envoy's identity. If that identity is
replaced, verify its new address and update the primary's Split Horizon mapping.
ExternalDNS does not maintain this translation. Keep device identities, addresses,
authentication state, and NAS/tailnet configuration in private operational records.
Do not remove subnet routing until Kubernetes and Talos administration paths
have been migrated and verified.

## Verification

Use Kubernetes context `homelab`. Check Service `TailscaleProxyReady` and proxy
readiness. Compare UDP and TCP DNS responses from tailnet and LAN clients,
including split DNS/search-domain behavior, public recursion, HTTPS, and repeated
HTTP/3 requests with TLS verification:

```bash
dig @TAILNET_RESOLVER APPLICATION_HOSTNAME A
dig +tcp @TAILNET_RESOLVER APPLICATION_HOSTNAME A
dig @LAN_RESOLVER APPLICATION_HOSTNAME A
tailscale dns status
tailscale dns query APPLICATION_HOSTNAME
curl --http2 --max-time 20 https://APPLICATION_HOSTNAME/ -o /dev/null
```

Expect tailnet answers to use the Envoy proxy address and LAN answers to retain
the LAN VIP. Record actual addresses and verification results privately.
