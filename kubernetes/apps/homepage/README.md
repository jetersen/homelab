# Homepage

Edit [config](config/) for links, layout, and widgets. Keep access internal unless
authentication is added.

Configure the TrueNAS widget endpoint in [services.yaml](config/services.yaml)
and use WebSocket API `version: 2`. Use `HOMEPAGE_VAR_TRUENAS_KEY` as the credential
placeholder; keep the API key in the SOPS-encrypted Secret.
