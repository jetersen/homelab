# Kopiur

Flux installs the published Kopiur OCI chart in `kopiur-system`. The chart pins
controller, webhook, and mover images by digest. Repository and application
resources run in their application's namespace. Use `copyMethod: Direct` for
local-path and static NFS volumes; these backups do not need CSI snapshots.

The admission webhook uses cert-manager. Flux's shared HelmRelease defaults use
`CreateReplace` for CRD installation and upgrades. Kopiur is alpha, so review
release notes and CRD changes before upgrading. VictoriaMetrics scrapes the
controller's metrics service.

## Existing repositories

Connect to an existing Kopia repository with `create.enabled: false`, its current
password Secret, and `mode: ReadOnly` while verifying history and recovery. Set
`maintenance.enabled: false` and `catalog.adoption: Ignore` during this stage.
Discovery materializes existing snapshots without deleting their data.

For a VolSync Kopia repository, preserve both `username@hostname` and source path
when translating a policy. The existing application identities use hostname
`homelab` and source path `/data`; Forgejo uses `/stage/current`.
Keep the original credential Secrets and retained NAS PVs and PVCs.

Before cutover, stop the old backup and maintenance schedules and wait for active
jobs to finish. Verify the new policy's file selection, export hooks, retention,
snapshot identity, and offsite replication. Prove recovery into a separate PVC
before allowing Kopiur to prune snapshots or take over maintenance. Roll back by
suspending Kopiur schedules and restoring the old schedules; repository data and
credentials remain in place.

Native application exports and consistency checks still need application-specific
hooks. Kopiur's `runJob` hooks can execute those jobs; it manages snapshot jobs,
repository replication, maintenance, and restores.

References:

- [Installation](https://kopiur.home-operations.com/install/)
- [VolSync migration](https://kopiur.home-operations.com/cli/migrate-volsync/)
- [Repository replication](https://kopiur.home-operations.com/replication/)
