# Music Assistant

The deployment uses the [private fork](https://forgejo.jetersen.dev/jetersen/music-assistant)
and its pinned image from the internal Forgejo registry. Build and upstream-sync
procedures live in the fork's `FORK.md` and `Dockerfile.private`.

The [deployment](../../kubernetes/apps/music-assistant/app/deployment.yaml) and
[storage claims](../../kubernetes/apps/music-assistant/app/storage.yaml) define
the runtime configuration and persistent storage.
