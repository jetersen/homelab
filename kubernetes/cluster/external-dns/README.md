# ExternalDNS

Public DNS watches HTTPRoutes. Internal DNS watches HTTPRoutes, TCPRoutes and
DNSEndpoints for infrastructure outside Kubernetes. Keep DNS annotations on
routes: controllers do not watch Services, Pods, Nodes or EndpointSlices.
Enable additional sources only when they need to publish records.

MQTT uses Envoy's shared addresses on TCP ports 1883 and 9001. Its hostname is
published by the MQTT TCPRoute; the WebSocket route shares that hostname.
In-cluster clients connect directly to the Mosquitto ClusterIP Service.

The Technitium release uses the native RFC2136 provider with HMAC-SHA256 TSIG
authentication and authenticated AXFR reads. Its key is stored in a
SOPS-encrypted Kubernetes Secret. Keep `txtOwnerId` and `txtPrefix` unchanged
when switching providers so existing TXT ownership remains valid.

Configure the key on the Technitium primary and allow A, AAAA and TXT updates
only in the managed zones, with an ACL matching the Kubernetes pod network.
TSIG authenticates DNS messages; it does not encrypt them.

Catalog members need zone transfer overrides to grant ExternalDNS access
without granting it access to every catalog zone. Retain the catalog's replica
ACL entries and TSIG keys alongside the ExternalDNS pod network and key. Keep
these overrides aligned with catalog changes so NAS replication continues to
work. Configure server settings through the primary so they replicate to the
other Technitium members.

For provider migrations, disable deletions until authenticated transfers and
the existing ownership records have been checked. The native RFC2136 provider
supports a read-only dry run; webhook providers require independent verification
that their dry-run path suppresses writes.
