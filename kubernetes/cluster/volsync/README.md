# Application backups

Flux manages the Kopia-enabled `perfectra1n/volsync` controller and pinned snapshot
API definitions. Chart and image versions are declared in `app/helmrelease.yaml`.
The controller runs in `volsync-system`; movers run in application namespaces.
Direct backups require the snapshot API definitions for controller startup, but
use no snapshot controller or storage driver.

`copyMethod: Direct` reads a PVC without making a point-in-time copy. Use completed
native exports or stopped writers for consistency. Snapshot actions in a mover
do not automatically stop another pod's application.

## Storage setup

Use [the Pulumi project](/infrastructure/backup/README.md) to manage the
private OVHcloud bucket and scoped S3 access. Region `de` and endpoint
`s3.de.io.cloud.ovh.net` provide Frankfurt Standard storage. Kopia takes a hostname
without a protocol or bucket prefix; its repository URL supplies the bucket and
repository prefix. Confirm connection values against the deployed bucket.

Keep credentials and a separate Kopia repository password in Proton Pass, resolve
them through Varlock, and generate SOPS-encrypted connection Secrets. Keep recovery
material outside the cluster. The active repository requires online storage;
review Kopia maintenance before adding object expiry, archive transitions,
versioning, Object Lock, or replication.

## Backup and recovery

1. Choose a native export or stopped-writer consistency method for each application.
   Preserve required hidden configuration, database state, and external recovery keys.
2. Choose repository prefixes and source identities. Assign one maintenance owner
   per repository and define retention, selection policies, and failure/staleness alerts.
3. Review the rendered configuration and coordinate downtime before deploying.
   Use Kubernetes context `homelab` and account for Flux reconciliation.
4. Start with a manual backup and restore into a separate fresh PVC. Verify selected
   data, isolated application recovery, and access from a fresh client.
5. Verify maintenance, pruning, and alerts before scheduling jobs or expanding coverage.

See [Home Assistant and Zigbee backup procedures](/kubernetes/apps/home-assistant/backup/README.md).
See [Sonarr backup procedures](/kubernetes/apps/media/backup/README.md) for native database
and configuration exports without logs or media.
Application PVC backups do not recover Talos configuration, SOPS keys, NAS data,
Pulumi state, or runtime secrets outside those volumes. Give these separate
recovery procedures. Keep inventory, measurements, and test results private.

## Local validation

```bash
kustomize build kubernetes/flux/namespaces
kustomize build kubernetes/cluster
kustomize build kubernetes/cluster/volsync/app
```

For Helm validation, extract `values` from `app/helmrelease.yaml` and render the
version declared there with the target Kubernetes version:

```bash
helm template volsync volsync \
  --repo https://perfectra1n.github.io/volsync/charts \
  --version CHART_VERSION --namespace volsync-system --kube-version KUBERNETES_VERSION \
  --values /path/to/temporary-values.yaml
```

References:

- [Distribution source](https://github.com/perfectra1n/volsync)
- [Kopia backup configuration](https://perfectra1n.github.io/volsync/usage/kopia/backup-configuration.html)
- [Kopia restore configuration](https://perfectra1n.github.io/volsync/usage/kopia/restore-configuration.html)
- [Repository maintenance](https://perfectra1n.github.io/volsync/usage/kopia/kopiamaintenance.html)
