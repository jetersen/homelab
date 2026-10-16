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
