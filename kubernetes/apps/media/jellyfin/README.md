# Hardware transcoding

See the [HelmRelease](helmrelease.yaml) for GPU and storage configuration.

In Dashboard → Playback → Transcoding, select Intel Quick Sync (QSV) and
`/dev/dri/renderD128`. Enable hardware decoding only for codecs reported by
`/usr/lib/jellyfin-ffmpeg/vainfo --display drm --device /dev/dri/renderD128`
inside the Jellyfin container. The N97 supports H.264 and HEVC encoding and
AV1 decoding, but not AV1 encoding. Jellyfin saves these settings in its config
PVC; they are separate from the HelmRelease.

Verify hardware acceleration with a forced video transcode and inspect its
FFmpeg log for the QSV hardware encoder. Direct Play does not use the transcoder.

## Transcode storage

Keep the database and image cache separate from transcode scratch storage.
NAS-backed scratch storage consumes network bandwidth; its NFS hard mount can
stall transcoding while the NAS is unavailable.

Keep the Transcode path unset in Dashboard → Playback → Transcoding so Jellyfin
uses `/cache/transcodes`. Enable Throttle Transcodes to limit how far FFmpeg runs
ahead of playback, and enable Delete Segments to reclaim older playback segments.
Use Jellyfin 12.2 or later for segment deletion because earlier versions have an
MKV remux cleanup bug. These playback settings are saved in the config PVC.

Mount changes recreate the pod and interrupt active playback. NAS scratch files
survive pod restarts and Jellyfin cleans them through its transcode cleanup task.
Reverting the mount restores local transcode storage without moving the database.

## IoT access

For IoT clients, use the dedicated endpoint defined in the
[HelmRelease](helmrelease.yaml).

Permit IoT clients to reach only this Service address on TCP 443 through UniFi.
Keep DNS access to Technitium. A firewall rule allowing the shared ingress
address would also expose other applications on that listener.
