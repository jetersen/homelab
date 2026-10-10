# Technitium

Technitium runs as UID 1000 with all capabilities dropped. The DNS Service
exposes port 53 and forwards to the unprivileged port configured in the
[HelmRelease](app/helmrelease.yaml).

Technitium 15.6.0 does not expose its DNS listening endpoints through an
environment variable. On fresh storage, use the web console's Settings > General
> DNS Server Local End Points, or the `/api/settings/set` API parameter
`dnsServerLocalEndPoints`, to set `0.0.0.0:1053,[::]:1053`. The setting persists
under `/etc/dns` and must match the Service target and DNS probe ports. The web
console remains accessible while DNS is unready during this setup.
