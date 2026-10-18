# Music Assistant

The deployment uses the [private fork](https://forgejo.jetersen.dev/jetersen/music-assistant)
and its pinned image from the internal Forgejo registry. Build and upstream-sync
procedures live in the fork's `FORK.md` and `Dockerfile.private`.

The [deployment](../../kubernetes/apps/music-assistant/app/deployment.yaml) and
[storage claims](../../kubernetes/apps/music-assistant/app/storage.yaml) define
the runtime configuration and persistent storage.

## Runtime and networking

Music Assistant runs as UID/GID 568. Existing files in writable volumes must have that
ownership. Cilium supplies cluster DNS and the default route; Multus attaches
`lan0` only to the main LAN for discovery and player connections. Its fixed IP
and MAC are defined in the network attachment and must stay outside DHCP and
other allocations. No IoT interface is attached, and IP forwarding is disabled.
A short-lived route init container keeps replies to the parent node on Cilium;
the application itself has no Linux capabilities or Kubernetes API token.

Set the webserver Base URL to `https://music.jetersen.dev` so discovery advertises
a stable address rather than a changing pod IP. Use that URL for Home Assistant
and browser access; Envoy forwards requests to the Kubernetes Service.
Players fetch streams through the LAN address on port 8097. Direct LAN traffic
bypasses Cilium NetworkPolicy and the router's inter-VLAN firewall.

The fork's shell-free image preserves its media helpers and native libraries.
Keep the configured writable mounts available while the root filesystem is
read-only. Build it with the maintained `Dockerfile.private` in the fork;
its `FORK.md` describes the runtime and upstream update procedure.
