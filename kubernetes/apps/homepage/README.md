# Homepage

Internal dashboard at https://home.jetersen.dev. Authentication is not configured;
keep access internal.

Edit `app/config/services.yaml` for links and Kubernetes pod associations,
`settings.yaml` for layout, and `widgets.yaml` for the cluster summary.

The TrueNAS widget uses the WebSocket API (`version: 2`). Its API key is stored
in `app/secret.sops.yaml` and injected as `HOMEPAGE_VAR_TRUENAS_KEY`; configuration
contains only the placeholder.

TrueNAS connects directly at `https://truenas.lan.jetersen.dev`, independent of
Envoy. TrueNAS renews its certificate using Let's Encrypt and Cloudflare DNS
validation. The DNS token must allow the NAS's outbound IP addresses.

```sh
kustomize build kubernetes/apps/homepage/app
```
