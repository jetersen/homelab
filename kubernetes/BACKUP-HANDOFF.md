# Homelab backup handoff

Prepared 2026-09-27 from repository manifests and read-only inspection of Kubernetes context `homelab`.

## Objective and current status

Back up important application state to encrypted, offsite S3-compatible storage using Kopia. Keep the existing single Talos node, local-path provisioner, and separate TrueNAS NFS storage. Local snapshots, quotas, volume expansion, and distributed storage are not requirements.

This document is a handoff, not a deployed backup system. No live Kopia repository, backup schedule, Kubernetes connection secret, or restore test has been deployed during this work. The user selected OVHcloud Standard One Zone on 2026-10-02, then chose a European account on 2026-10-03. After approval, Pulumi provisioned private bucket `jetersen-homelab-kopia`, separate owner and Kopia users, a scoped policy, and an S3 credential in EU project `8f573109804548c5acd72a72af919479`. Live S3 tests passed. The user created both S3 and Kopia logins in Proton Pass; Varlock validates them. SOPS-encrypted connection manifests and paused Home Assistant/Zigbee native-export pilots are prepared, with offline mover/restore tests. Live application backups and restore verification remain pending. See [the pilot runbook](apps/home-assistant/backup/README.md).

## Storage and recovery scope

- Node: `talos01`, `192.168.1.10`; Kubernetes context: `homelab`.
- Local application PVCs use `local-path`, backed by `/var/mnt/local-path-provisioner`.
- `media/media-data` is a static NFS PV/PVC pointing to TrueNAS at `192.168.1.2:/mnt/nvme/media`.
- Flux manages manifests under `kubernetes/`. Changing storage provisioners is outside this backup work.
- Recover application state into fresh PVCs and recreate workloads from Git. A PVC backup alone does not recover the node, cluster configuration, NAS, or external services.

## Measured backup candidates

Measurements below are allocated disk usage from `du -sk`, not PVC capacity, logical file size, or predicted compressed repository size. Applications were running, so values are approximate point-in-time observations. Grafana was inspected using a temporary pod with a read-only PVC mount; that pod was removed.

| Namespace / PVC | Mount | Measured usage | Data to preserve |
| --- | --- | ---: | --- |
| `home-assistant/home-assistant-pvc` | `/config` | 325 MiB | Full configuration including hidden `.storage`, integrations, automations, dashboards, and recorder history |
| `home-assistant/zigbee2mqtt` | `/data` | 101 MiB | Configuration, device database, coordinator backup, and state |
| `home-assistant/mosquitto` | `/mosquitto/data` | 0.5 MiB | Persisted retained messages and sessions |
| `technitium/technitium` | `/etc/dns` | 276 MiB | DNS settings, zones, and application configuration |
| `media/sonarr` | `/config` | 19.5 MiB | Configuration, library database, profiles, and history |
| `media/radarr` | `/config` | 2.2 MiB | Configuration, library database, profiles, and history |
| `media/prowlarr` | `/config` | 5.4 MiB | Indexer configuration and application integrations |
| `media/jellyfin-config` | `/config` | 0.7 MiB | Users, watch history, library settings, and metadata |
| `media/qbittorrent` | `/config` | 8.7 MiB | Settings, torrent metadata, and resume state |
| `monitoring/grafana` | `/var/lib/grafana` | 743 MiB | Database, UI-created dashboards, and settings |

The ten PVCs total approximately **1.45 GiB** before exclusions. Media applications were recently deployed when measured, so their usage may grow.

### Proposed exclusions

These are recommendations, not applied policies. Paths are relative to each volume's backup root. Verify Kopia/VolSync exclusion syntax and resulting file selection before implementation.

| Application | Candidate exclusions | Conditions and expected result |
| --- | --- | --- |
| Grafana | `plugins/` | About 717 MiB, including 212 MiB for VictoriaMetrics Logs. Exclude only after verifying all required plugins can be recreated from declared configuration. Remaining data: about 25.5 MiB. |
| Zigbee2MQTT | `log/`, known migration log files | About 101 MiB of logs. Preserve `database.db`, `coordinator_backup.json`, `configuration.yaml`, state, and configuration backups. Remaining data: about 56 KiB before removing migration logs. |
| Technitium | `stats/`, `logs/`, `blocklists/` | About 178 MiB of statistics, 26 MiB of logs, and 13 MiB of downloaded lists. Verify blocklists are reproducible from configured sources. Retain the whole `apps/` directory initially because it also contains app settings/data. Remaining data: about 60 MiB. |
| Home Assistant | `.cache/`, known `home-assistant.log*` files | Rebuildable cache and logs. Preserve `.storage`; do not exclude hidden files generally. |
| Home Assistant, conditional | `backups/` | Three existing backup archives use about 164 MiB. Exclude only after the chosen Kopia workflow has a tested consistent recovery path. If native Home Assistant archives are the backup source, preserve those archives instead. |

Home Assistant's recorder database uses about 151 MiB plus a 4 MiB WAL. Keep history initially. Do not omit a live database's WAL/SHM files while treating a raw database copy as consistent.

With these exclusions, including the conditional exclusion of duplicate Home Assistant archives, the combined source is approximately **280 MiB**. This is an estimate, not a tested backup size. Retention and database churn can increase repository storage; compression and deduplication can reduce it.

### Outside the initial backup set

- `media/jellyfin-cache`: rebuildable cache.
- `konflate/konflate-cache`: expected to be rebuildable, but inspect/verify its role before formally excluding it.
- VictoriaMetrics and VictoriaLogs: proposed acceptance of lost monitoring history. Configured retention is 30 days and seven days respectively.
- `media/media-data`: exclude replaceable media and incomplete downloads from the initial application-state job. NAS contents have not been inspected. Identify personal or irreplaceable files separately and give them an explicit NAS backup policy.
- Stateless applications/controllers: recreate from Git, accounting separately for secrets and generated state needed for recovery.

## S3 provider recommendation

User requirements clarified on 2026-10-02:

- US-owned providers are excluded. An EU storage region does not make a US-owned provider acceptable; Backblaze B2 is excluded.
- A single availability zone is acceptable to the user.

The user selected **OVHcloud Standard One Zone** on 2026-10-02 after comparing non-US providers, then selected Frankfurt, Germany (`de`) on 2026-10-03. Provisioned bucket `jetersen-homelab-kopia` uses verified S3 endpoint `s3.de.io.cloud.ovh.net` and region `de`. See [the OVHcloud setup steps](cluster/volsync/README.md#ovhcloud-setup).

The previous Public Cloud project `f2d4d802d8834a48819bd7828694f56c` belongs to the Canadian/rest-of-world control platform. Read-only checks authenticated its API keys against `ovh-ca`, confirmed region `DE` is available, and found no Frankfurt buckets or project users. The user chose a European account on 2026-10-03. The old account/project remain untouched. The replacement EU project is `8f573109804548c5acd72a72af919479`; updated Proton Pass credentials authenticated against `ovh-eu`, with scoped GET/POST/PUT rights and no DELETE rights. Read-only checks found Frankfurt `DE` active, no Frankfurt buckets, and no project users. Pulumi has no default project ID; the replacement ID is explicit local stack config.

On 2026-10-03, the user selected Pulumi IaC and approved provisioning after reviewing the preview. The [C# infrastructure project](../infrastructure/backup/README.md) created the bucket, separate users, policy, and S3 credential. Local state uses passphrase-encrypted secret fields; API credentials and the passphrase resolve through Varlock from Proton Pass. The local `homelab` stack has seven resources, including the stack and EU provider. The bucket owner is `825482`, Kopia is `825483`, and only Kopia has an S3 credential. Builds passed with zero warnings/errors. A refreshed update reported seven unchanged resources after removing the AWS `Version` field that OVH strips from policies; the mock regression checks passed.

Live S3 tests verified region, list/upload/download/delete, Standard-class uploads, multipart create/upload/list/abort, denied anonymous reads, and denied object ACL changes. Temporary test objects and multipart uploads were removed. The initial boto3 anonymous request returned `InvalidRequest`; a raw unsigned virtual-host GET returned `403 AccessDenied`. These checks validate the storage foundation, not application consistency or a Kopia restore. The user-terminal helper saved the S3 entry, then failed while creating Kopia with a generic withheld diagnostic; the original CLI cause remains unconfirmed. The helper now uses the verified standalone password generator and stdin login template, preserves existing logins, and identifies the failing operation. Four offline regression tests passed, including partial-success recovery and preservation of an existing repository password. The user then created `Homelab Kopia`; Varlock validates both backup logins and the Pulumi passphrase. Agents have not executed storing mode.

On 2026-10-03, the user chose Frankfurt 1-AZ Standard without cross-region replication. A second S3 provider can be considered if the data becomes more critical; an additional copy is outside the current setup scope. No replication has been configured.

OVHcloud's published One Zone Standard rate was approximately €0.0070956/GiB-month before VAT when checked on 2026-10-02, with free requests, retrieval, and outgoing traffic. Use the `io` endpoint, where default uploads map to Standard; the legacy `perf` endpoint defaults to High Performance.

Pricing researched on 2026-09-27:

| Option | Indicative price excluding VAT | Notes |
| --- | --- | --- |
| Scaleway Standard Multi-AZ | €0.000022/GB-hour, approximately €0.01606/GB-month at 730 hours | Roughly €0.16/month for 10 GB of repository storage, before transfer or other charges. |
| Scaleway Standard One Zone | Approximately €0.00803/GB-month | Alternative considered before OVHcloud was selected; roughly €0.08/month for 10 GB, before transfer or other charges. |
| Hetzner Object Storage | Reported €6.49/month base, including 1 TB storage and 1 TB outbound traffic | Confirm current checkout pricing: the official page's dynamically rendered price could not be read during research. |

Scaleway's pricing page listed 75 GB/month free outbound traffic, then €0.01/GB. Do not assume a permanent free storage tier. Recheck prices and region availability when provisioning.

Scaleway pricing and Amsterdam One Zone availability were rechecked on 2026-10-02. Kopia requires immediately readable storage for its active repository. Delayed-access archive tiers such as Scaleway Glacier and AWS Glacier Deep Archive are unsuitable for this role. Long-term recovery points can remain in online storage under Kopia retention policies; a separate archive workflow can be considered for substantial, rarely changing NAS data later.

- [Scaleway pricing update](https://www.scaleway.com/en/blog/a-transparent-update-on-scaleway-pricing/)
- [OVHcloud pricing](https://www.ovhcloud.com/en-ie/public-cloud/prices/)
- [OVHcloud endpoint and storage-class mapping](https://github.com/ovh/docs/blob/develop/pages/storage_and_backup/object_storage/s3_location/guide.en-gb.md)
- [Scaleway storage pricing](https://www.scaleway.com/fr/tarifs/storage/)
- [Scaleway ownership](https://www.scaleway.com/en/accelerating-your-ecological-transition-with-cloud-solutions/)
- [Scaleway regional availability](https://www.scaleway.com/en/product-availability-by-region/)
- [Kopia storage tier compatibility](https://kopia.io/docs/advanced/storage-tiers/)
- [Hetzner Object Storage features and billing model](https://www.hetzner.com/storage/object-storage/)

## Proposed implementation

1. Confirm provider, EU region, account, and bucket. Use a dedicated private bucket and scoped access. Do not put cloud credentials or repository passwords in plaintext manifests or chat.
2. Evaluate the Kopia-enabled `perfectra1n/volsync` distribution. Previous research found Kopia documentation there; do not assume upstream `backube/volsync` has the same mover or CRD schema. Verify current source, chart/image versions, maintenance status, Talos compatibility, direct-copy support, exclusion policies, and restore behavior before choosing it.
3. Define repository layout explicitly. Decide between per-application repositories/prefixes and a shared repository, and document maintenance ownership and restore identities. Verify the selected mover's supported model before creating repositories.
4. Add Flux-managed manifests following existing repository conventions. Use the repository's secure secret-management workflow; consult the Varlock skill before handling credentials and existing SOPS conventions before writing encrypted manifests.
5. Use direct filesystem backups with a deliberate per-application consistency method, since local-path has no CSI snapshots. Native backup exports or stopped-writer copies are candidates. Do not assume the mover automatically stops workloads or that a successful copy proves database consistency.
6. Pilot one application, perform a backup, and restore it into a separate PVC before expanding to all ten applications. Coordinate any downtime before running stopped-writer backups.
7. Configure retention, repository maintenance, and failure/staleness reporting. Confirm pruning and compaction actually run and that concurrent jobs are supported by the chosen repository arrangement.
8. Review rendered manifests and checks before deployment. Local infrastructure edits do not authorize a push or deployment by themselves.

Use normal online object storage for the active repository. Do not add bucket expiry, archival transitions, or object-lock rules without checking their interaction with Kopia's repository maintenance and retention. Kopia snapshots can share stored objects across recovery points.

### Consistency and scheduling

Proposed initial retention: **14 daily, eight weekly, and six monthly** recovery points, with nightly backups and an additional recovery point before risky upgrades. This policy is prepared for the paused pilots and verified with the pinned mover offline; live maintenance/pruning and scheduling are pending.

- Home Assistant: the pilot selects completed encrypted native archives only. Installed 2026.9.4 native backup code excludes logs and caches. The user confirmed its emergency kit/encryption key is saved outside the cluster. Application decryption/recovery testing remains pending.
- Zigbee2MQTT: the pilot uses its native MQTT export, which refreshes the coordinator backup. It validates device/coordinator data, preserves configuration/custom code and Kubernetes-injected network/MQTT settings, and excludes logs/OTA firmware. Current recovery files total 39,038 bytes versus 82,522,688 bytes of logs. The exporter remains suspended. Test restoration without running a second instance against the live coordinator.
- SQLite-backed applications: use supported native backup exports or cleanly stopped writers. Do not copy changing database files and assume they form one consistent recovery point.
- Mosquitto: account for persistence flushing before copying its on-disk state.
- Technitium: prefer a supported export or a consistent configuration copy. Stopping DNS may disrupt both applications and backup endpoint resolution, so plan that dependency before introducing downtime.
- Stagger jobs and coordinate any stop/start operation with Flux reconciliation. Avoid overlapping runs and ensure failed backups cannot leave workloads stopped.

## Encryption and recovery material

Kopia encrypts data client-side before uploading it. S3 access credentials and the Kopia repository password serve different purposes; recovery requires bucket access and the repository password. Store a recovery copy of the password outside the cluster, such as in the user's password manager.

Maintain recovery copies of:

- This Git repository and the SOPS decryption key.
- Kopia repository password, bucket/endpoint/region details, repository layout, and access recovery procedure.
- Talos bootstrap/recovery material and configuration.
- TrueNAS configuration and a separate policy for irreplaceable NAS data.
- Any runtime-generated secrets that cannot be recreated from Git or external account recovery.

Do not assume an application PVC backup includes any of those items. Encryption protects confidentiality; it does not by itself prevent backup deletion.

## Acceptance and restore checks

- Each selected application has a successful backup with the intended file selection and retention policy.
- Inspect backup inventory to confirm hidden configuration files are present and logs/caches are excluded as intended.
- Restore into a fresh PVC without overwriting the running application's data.
- Prioritize Home Assistant and Zigbee2MQTT recovery tests; isolate restored workloads from production devices and services.
- Validate restored application behavior, not just command exit status. For other apps, check representative settings, users, library entries, and dashboards.
- Demonstrate repository access from a fresh client using recovery material stored outside the cluster.
- Record actual repository usage, backup duration, restore duration, tested versions, and the exact commands/context used.
- Record failed/stale backup alert behavior and maintenance/pruning results.
- Only then exclude duplicate Home Assistant archives and rely on the new workflow.

## Cleanup already completed

The following unused PVCs and their backing PVs were deleted with user authorization after workload-reference checks in context `homelab`:

- `monitoring/server-volume-victoria-metrics-single-server-0`
- `monitoring/server-volume-victoria-metrics-victoria-metrics-single-server-0`
- `media/lidarr`

Active monitoring PVCs and the NAS media PVC remained bound. No application data was deleted as part of the subsequent usage inspections.

## Implementation references

- [Kopia encryption and repositories](https://kopia.io/docs/getting-started/)
- [Kopia-enabled VolSync backup configuration](https://perfectra1n.github.io/volsync/usage/kopia/backup-configuration.html)
- [Upstream VolSync Restic documentation](https://volsync.readthedocs.io/en/stable/usage/restic/index.html)
- [Home Assistant backup documentation](https://www.home-assistant.io/common-tasks/general/)
- [Zigbee2MQTT backup request documentation](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html)
- [Jellyfin backup and restore](https://jellyfin.org/docs/general/administration/backup-and-restore/)
