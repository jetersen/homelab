# Music Assistant

The deployment uses the [private fork](https://forgejo.jetersen.dev/jetersen/music-assistant)
and its pinned image from the internal Forgejo registry. Build and upstream-sync
procedures live in the fork's `FORK.md` and `Dockerfile.private`.

The fork adds optional YouTube Music video search and caches completed YouTube
Music tracks using their original compressed audio. A separate thin LVM volume
holds the disk cache. Both disk and RAM caches evict least-recently-used entries;
active disk readers are protected. Recently used tracks also stay in a bounded
RAM cache for five minutes of inactivity. The normal decoded audio buffers feed
players. Clients still need a connection to the Music Assistant server.

The [deployment](../../kubernetes/apps/music-assistant/app/deployment.yaml) defines
cache budgets and mounts; the [claims](../../kubernetes/apps/music-assistant/app/storage.yaml)
keep application state separate from replaceable audio cache data. Allow filesystem
headroom above the disk-cache budget. Cache failures fall back to upstream streaming.

## Runtime and networking

Music Assistant runs as UID/GID 568. Existing state and cache files must have that
ownership. Cilium supplies cluster DNS and the default route; Multus attaches
`lan0` only to the main LAN for discovery and player connections. Its fixed IP
and MAC are defined in the network attachment and must stay outside DHCP and
other allocations. No IoT interface is attached, and IP forwarding is disabled.
A short-lived route init container keeps replies to the parent node on Cilium;
the application itself has no Linux capabilities or Kubernetes API token.

Use `http://music-assistant.home-assistant.svc.cluster.local:8095` for the Home
Assistant integration and `https://music.jetersen.dev` for browser access.
Players fetch streams through the LAN address on port 8097. Direct LAN traffic
bypasses Cilium NetworkPolicy and the router's inter-VLAN firewall.

The fork's shell-free image preserves its media helpers and native libraries.
Keep state, the track cache, and `/tmp` writable while the root filesystem is
read-only. Build it with the maintained `Dockerfile.private` in the fork;
its `FORK.md` describes the runtime and upstream update procedure.
