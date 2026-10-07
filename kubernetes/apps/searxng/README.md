# SearXNG

SearXNG is available at `https://search.jetersen.dev` through the existing Envoy
gateway and wildcard certificate. Internal DNS resolves the gateway VIP, which
Talos advertises to Tailscale. The route allows private LAN, tailnet, and cluster
clients; other sources are denied. No public DNS alias or tunnel is configured.
Linux Tailscale clients must accept subnet routes and use tailnet DNS.

The official image generates `settings.yml` and a random application secret on
first boot. The retained `searxng-config` PVC preserves them across upgrades.
Do not print that file or commit it unencrypted. The cache is disposable.
There is no search history database or account setup.

Deployment environment variables set the base URL and enable image proxying.
The limiter and public-instance features are disabled for private use, so Valkey
is not required. Engine and interface preferences can be changed in the browser.

The image is pinned by version and digest. See the upstream
[container documentation](https://docs.searxng.org/admin/installation-docker.html)
and [settings reference](https://docs.searxng.org/admin/settings/).
