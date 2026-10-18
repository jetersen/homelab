# SearXNG

Edit the [managed settings](app/config/settings.yml) for instance defaults and the
[deployment](app/deployment.yaml) for runtime configuration.

Edit the managed template rather than the generated PVC settings file, which
contains the application secret. Preserve the [configuration PVC](app/pvc.yaml)
across upgrades; do not print its settings file or commit it unencrypted.

Keep the instance private while the limiter and public-instance features are
disabled. Linux Tailscale clients need subnet routes and tailnet DNS for access.
Browser preferences can override managed defaults. Upstream rate limits and
CAPTCHAs can still prevent searches; browser cookies are not shared with SearXNG.

See the upstream [container documentation](https://docs.searxng.org/admin/installation-docker.html)
and [settings reference](https://docs.searxng.org/admin/settings/).
