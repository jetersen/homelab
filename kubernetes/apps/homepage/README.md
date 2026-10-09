# Homepage

Internal dashboard at https://home.jetersen.dev. Authentication is not configured;
keep access internal.

Edit [app/config](app/config/) for links, layout, and widgets.

The TrueNAS widget uses the WebSocket API (`version: 2`). Its API key is stored
in `app/secret.sops.yaml` and injected as `HOMEPAGE_VAR_TRUENAS_KEY`; configuration
contains only the placeholder.

The widget connects directly to TrueNAS, independent of Envoy. Configure its
endpoint in [services.yaml](app/config/services.yaml).
