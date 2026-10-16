# Music Assistant

The image applies a YouTube Music provider patch to the pinned upstream release.
Enable **Include videos in search results** in the provider settings to search
videos alongside songs. The option defaults to off and leaves radio and library
imports unchanged. Search results interleave songs and videos and deduplicate IDs.

Build from the repository root:

```sh
docker build --build-arg REVISION="$(git rev-parse HEAD)" \
  -t forgejo.jetersen.dev/jetersen/homelab/music-assistant:2.10.6-videos.1 \
  infrastructure/music-assistant/image
```

Push the image, then update the deployment's image digest through GitOps. Treat
published version tags as immutable. To update the patch, use the matching upstream
source, run its provider tests and pre-commit checks, and regenerate `provider.patch`
with `git diff` for the provider directory and generated English translations.
Remove the patch when an upstream release includes the setting.
