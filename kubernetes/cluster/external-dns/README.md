# ExternalDNS

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
