# Media stack

Sonarr, Radarr, Lidarr, Prowlarr, qBittorrent, and Jellyfin run in the `media`
namespace on Kubernetes context `homelab`. Each application uses the existing
app-template Helm chart and has its own persistent configuration volume.

## Storage

TrueNAS `192.168.1.2` exports the existing `nvme/media` dataset at
`/mnt/nvme/media`. The `media-data` PV and PVC mount it over NFSv4.2.
The declared `1Ti` capacity is for Kubernetes binding, not a reservation or quota.

```text
/mnt/nvme/media                       /data in the ARR apps and qBittorrent
├── torrents
│   ├── incomplete
│   ├── tv
│   ├── movies
│   └── music
└── media
    ├── tv
    ├── movies
    └── music
```

These are directories in one ZFS dataset. Do not turn them into child datasets
or split the ARR apps' `/data` mount into separate download and library mounts.
This preserves hardlinks and atomic renames. Torrents still being seeded should
be imported using hardlinks; the original download remains available for seeding.
No remote path mappings are needed because the apps see identical paths.
See the [Servarr storage guide](https://wiki.servarr.com/docker-guide).

Jellyfin mounts only the `media` subdirectory at `/data/media`, read-only.
Prowlarr has no media mount. Databases and application configuration use
`local-path` PVCs on `talos01`, avoiding SQLite databases on NFS. Back up these
PVCs separately from the TrueNAS dataset. They cannot fail over to another node.
Config PVCs and the shared media volume are retained when releases are removed.
Jellyfin's separate local cache PVC is disposable.

## TrueNAS prerequisite

Inspection found `/mnt/nvme/media` empty, owned by `root:root`, mode `0755`,
without an ACL or NFS export. NFS is already running, and `apps:apps` is UID/GID
`568:568`. Before deploying, recheck that state and obtain approval for:

- Set the dataset root owner and group to `568:568`, mode `0775`, without
  recursive changes or ACL removal.
- Create a read-write NFS export of `/mnt/nvme/media`, restricted to Kubernetes
  node `192.168.1.10`, mapping users to `apps:apps`.

The intended API requests are in `truenas-setup.json`; this file is a reviewable
plan, not a controller or an automatically applied manifest. The storage Job
creates the directories as UID/GID 568 after the export is available.

Rollback: stop the new media workloads, remove only this new NFS export, and
restore the dataset root to UID/GID `0:0`, mode `0755`. Leave all data intact.
Never delete the dataset or recursively reset permissions as part of rollback.

## DNS and VPN

The ARR apps and Jellyfin use `dnsPolicy: None` with Technitium at `192.168.1.21`.
The live resolver forwards to `security.cloudflare-dns.com` at `1.1.1.2` and
`1.0.0.2` over TLS, with DNSSEC validation enabled. This encrypts the upstream
DNS hop, not media transfers or the LAN DNS hop.

Technitium does not resolve `cluster.local`, so use the LAN HTTPS URLs below for
application integrations. This avoids changing cluster-wide DNS or creating
a DNS forwarding loop. The existing internal external-dns controllers manage
these records; none opt in to public Cloudflare DNS publication.

qBittorrent uses a Gluetun native sidecar for Proton WireGuard, its firewall,
and NAT-PMP port forwarding. Its resolver is `127.0.0.1`, served by Gluetun
through the VPN. Its application process is bound to `tun0`. The sidecar's
startup health check must pass before qBittorrent starts. Only the VPN container
gets `NET_ADMIN`; it does not use host networking or privileged container mode.

The `qbittorrent-wireguard` Secret contains `wg0.conf` encrypted with SOPS for
Flux. Generate Proton configurations with NAT-PMP enabled. Do not commit the
downloaded plaintext configuration. See [Proton setup in Gluetun](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/protonvpn.md).

Gluetun updates qBittorrent's listening port when Proton allocates a port and
binds it to loopback when port forwarding stops. The hook uses qBittorrent's
localhost authentication bypass inside the same pod; network authentication
remains enabled. The seed config is copied only when no config exists.
Do not disable the VPN firewall, enable subnet authentication bypass, or publish
the peer port through a Kubernetes Service. Inbound peers use Proton's port.

## Application setup

| Application | URL | Library / download category |
| --- | --- | --- |
| Sonarr | https://sonarr.lan.jetersen.dev | `/data/media/tv`, category `tv` |
| Radarr | https://radarr.lan.jetersen.dev | `/data/media/movies`, category `movies` |
| Lidarr | https://lidarr.lan.jetersen.dev | `/data/media/music`, category `music` |
| Prowlarr | https://prowlarr.lan.jetersen.dev | Sync indexers to the three ARR apps |
| qBittorrent | https://qbittorrent.lan.jetersen.dev | `/data/torrents/<category>` |
| Jellyfin | https://jellyfin.lan.jetersen.dev | Read-only TV, movies, and music libraries |

Set application administrator credentials on first use. Add the three categories
in qBittorrent with the paths above. Configure each ARR app's root folder,
enable hardlinks, and add qBittorrent at `qbittorrent.lan.jetersen.dev`, port 443,
SSL enabled, using the matching category. Prowlarr connects to each ARR app via
its LAN URL and application API key. Indexer accounts and quality profiles are
user choices, not supplied by these manifests.

Configure Jellyfin's initial administrator and libraries using `/data/media/tv`,
`/data/media/movies`, and `/data/media/music`. Hardware transcoding is not
configured; direct play avoids transcoding load on the Kubernetes node.

## Deployment verification

After approval and deployment, check all seven Flux Kustomizations and six
HelmReleases in context `homelab`. Verify the NFS mount from each importing app,
including creating a temporary file, hardlinking it between torrents and media,
comparing inode/device numbers, and renaming it. Remove only those test files.

Check Technitium DNS and the six HTTPS routes. For qBittorrent, confirm a Proton
exit IP, a recent WireGuard handshake, an allocated incoming port matching its
listening port, and that torrent traffic cannot leave when the VPN is unavailable.
Do not start downloads before these checks pass.
