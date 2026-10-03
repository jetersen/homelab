# Application backups

## Status

The controller manifests are prepared locally. The private Frankfurt S3 bucket,
users, scoped policy, and S3 credential have been provisioned with Pulumi.
No controller, Kopia repository, backup source, schedule, Kubernetes connection
secret, maintenance job, or restore test has been deployed by this work.
Installing this controller alone does not protect data. Both Proton Pass entries
now validate. SOPS-encrypted connections and paused native-backup pilots for Home
Assistant and Zigbee2MQTT are prepared in [the pilot runbook](../../apps/home-assistant/backup/README.md).
Offline archive-selection/restore tests and server dry runs passed; live Kopia
backup, isolated restore and application recovery remain pending.

See [the backup handoff](../../BACKUP-HANDOFF.md) for the ten application volumes,
consistency requirements, recovery material, and separate NAS backup scope.

## OVHcloud setup

The user selected OVHcloud Standard One Zone on 2026-10-02 and Frankfurt,
Germany (`de`) on 2026-10-03. US-owned providers are excluded. The previous
project `f2d4d802d8834a48819bd7828694f56c` is on the Canadian control platform.
The user chose a European account instead. Project
`8f573109804548c5acd72a72af919479` and its updated API keys have been verified
against `ovh-eu`; Frankfurt is active. The old project remains untouched.
After user approval on 2026-10-03, Pulumi provisioned `jetersen-homelab-kopia` and
the four related OVH resources. Live S3 checks passed for CRUD, multipart handling,
Standard-class uploads, denied anonymous reads, and denied object ACL changes.
All temporary test data was removed. A refreshed update reported no changes.

Use [the Pulumi C# project](../../../infrastructure/backup/README.md) to create
the bucket, separate owner and Kopia users, scoped policy, and S3 credentials.
The user selected IaC on 2026-10-03, so do not create the bucket through the wizard.
Future infrastructure changes should start with a reviewed live Pulumi preview.

Use the user-terminal transfer in the Pulumi guide to store the access key and secret key in the
username/password fields of `Personal/OVHcloud Homelab S3` in Proton Pass. Store a
separate generated repository password in `Personal/Homelab Kopia`. The bucket
name is now the schema default. Set `BACKUP_S3_CONFIGURED=true` in local Varlock overrides, then run
`npm exec -- varlock load --agent`. Never paste credentials into chat.

Use endpoint `s3.de.io.cloud.ovh.net`. Confirm the actual region and endpoint
from the deployed bucket before generating connection secrets. Start without
object expiry, archive transitions, versioning, Object Lock, or replication.

OVHcloud's `io` endpoint maps default uploads to Standard storage. Its legacy
`perf` endpoint maps default uploads to High Performance, so use the `io`
endpoint. Kopia's connection endpoint is the hostname without a protocol or
bucket prefix; the repository URL supplies the bucket and repository prefix.

The Proton Pass items are filled and the pilot connection manifests are encrypted.
Next, review and approve the controller/pilot deployment and isolated restores. No offsite backup exists
until those operations succeed.

References:

- [Create a Public Cloud project](https://docs.ovhcloud.com/en/guides/public-cloud/cross-functional/create-a-public-cloud-project)
- [Create and manage an S3 bucket](https://docs.ovhcloud.com/en/guides/storage-and-backup/object-storage/s3-getting-started-with-object-storage)
- [Endpoint and region mapping](https://github.com/ovh/docs/blob/develop/pages/storage_and_backup/object_storage/s3_location/guide.en-gb.md)

## Additional copies

On 2026-10-03, the user chose Frankfurt 1-AZ Standard without cross-region
replication. This is the current backup scope. If the data becomes more critical,
a second S3 provider can be considered for an independent copy. No second bucket,
replication rule, or additional provider is configured or planned for this setup.

## Controller

Use the Kopia-enabled `perfectra1n/volsync` distribution, not the upstream chart.
The published chart is pinned to `0.18.5`, with controller and Kopia mover image
`0.17.11` pinned by digest. The chart includes the ReplicationSource,
ReplicationDestination, and KopiaMaintenance CRDs. Its controller runs without
root privileges in `volsync-system`; movers run in their application's namespace.

Verified against the published chart and source commit
`6966ac301ba3580d5cbadc2c4475f2c6ad1246d2` on 2026-10-02. The chart supports the
cluster's Kubernetes 1.36.1 version. Direct Kopia backups are supported and require
no CSI snapshot provisioner. Runtime compatibility still needs a cluster pilot.

`copyMethod: Direct` reads the application PVC without creating a point-in-time
copy. It does not make a changing database consistent. Kopia snapshot actions run
in the mover container and do not automatically stop another pod's application.

## Setup sequence

1. The Pulumi project has provisioned the dedicated private S3 bucket in the
   new European Public Cloud project with Standard One Zone in Frankfurt.
   Keep the active
   repository in normal online storage. Do not configure object expiry, archival
   transitions, or object locking until their maintenance implications are reviewed.
2. Store scoped S3 access credentials and a separate Kopia repository password in
   Proton Pass. Wire their references into Varlock and generate a SOPS-encrypted
   Kubernetes Secret without printing the values. Keep recovery material outside
   the cluster. The current connection manifests and secret references have been verified.
3. Choose the pilot application and its consistency method. Prefer completed
   native Home Assistant backups for a first pilot if they can be generated and
   restored reliably. Do not enable raw live-PVC database copies as reliable backups.
4. Use a separate repository prefix for the pilot. Before expanding, choose
   whether to retain per-application repositories or share one repository, with
   explicit source identities and one maintenance owner per repository.
5. Prepare ReplicationSource, KopiaMaintenance, file-selection policies, and
   failure/staleness alerts using the installed chart's CRDs. Start with a manual
   trigger. Proposed retention is 14 daily, eight weekly, and six monthly snapshots.
6. Review the rendered configuration before deploying. Use Kubernetes context
   `homelab` for every cluster command. Coordinate any application downtime before
   a stopped-writer copy; account for Flux reconciliation and failed-job recovery.
7. Back up the pilot and restore an explicit snapshot into a separate fresh PVC.
   Check the recovered data and application behavior in isolation. Verify access
   from a fresh client using the external recovery material, and verify maintenance
   and alert behavior before enabling nightly jobs or expanding the backup set.

The account, bucket and credentials are ready. Application pilots still need deployment
and live backup/restore verification before they provide protection. NAS files, Talos recovery material, SOPS keys, and other external
state need their own recovery copies as described in the handoff.

## Local validation

```bash
kustomize build kubernetes/flux/namespaces
kustomize build kubernetes/cluster
kustomize build kubernetes/cluster/volsync/app
```

For a chart render, extract the `values` mapping from `app/helmrelease.yaml` into
a temporary values file, then run:

```bash
helm template volsync volsync \
  --repo https://perfectra1n.github.io/volsync/charts \
  --version 0.18.5 --namespace volsync-system --kube-version 1.36.1 \
  --values /path/to/temporary-values.yaml
```

References:

- [Distribution source](https://github.com/perfectra1n/volsync)
- [Kopia backup configuration](https://perfectra1n.github.io/volsync/usage/kopia/backup-configuration.html)
- [Kopia restore configuration](https://perfectra1n.github.io/volsync/usage/kopia/restore-configuration.html)
- [Repository maintenance](https://perfectra1n.github.io/volsync/usage/kopia/kopiamaintenance.html)
