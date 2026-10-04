# Hardware transcoding

Jellyfin requests an Intel GPU from the Flux-managed `intel-gpu-plugin`.
The plugin runs on `talos01`, whose Talos image includes `siderolabs/i915`.
The render device is accessible to Jellyfin's non-root user without extra groups.

In Dashboard → Playback → Transcoding, select Intel Quick Sync (QSV) and
`/dev/dri/renderD128`. Enable hardware decoding only for codecs reported by
`/usr/lib/jellyfin-ffmpeg/vainfo --display drm --device /dev/dri/renderD128`
inside the Jellyfin container. The N97 supports H.264 and HEVC encoding and
AV1 decoding, but not AV1 encoding. Jellyfin saves these settings in its config
PVC; they are separate from the HelmRelease.

Verify hardware acceleration with a forced video transcode and inspect its
FFmpeg log for the QSV hardware encoder. Direct Play does not use the transcoder.
