# Forgejo

User repositories can be created with the first SSH push. Push-created repos
default to private; pass `git push -o repo.private=false origin main` to publish
one. Organization push-to-create remains disabled. Public repositories and
public owners' packages allow anonymous reads; private repositories require
authorized access. Account registration remains disabled.

Web access is available at `https://forgejo.jetersen.dev` on the LAN and Tailscale.
For Git SSH, add an account SSH key and use
`git@forgejo.jetersen.dev:owner/repository.git`. Tailscale grants must allow TCP 22
to the gateway host route.

Edit [app/error-page.html](app/error-page.html) for gateway error responses,
including backup downtime. The embedded mascot is by David Revoy, CC BY 4.0.

The bootstrap administrator is `jetersen`; its initial password is the `password`
key in the `forgejo-admin` Secret. Change it at first login. The chart creates the
administrator only once and does not reset its password during upgrades.
Existing users link their GitHub identity by authenticating their Forgejo account
once. Keep the local administrator login available for recovery.

Application and chart major upgrades require Renovate dashboard approval and
manual merge because upgrades can change the database schema.

## Storage

SQLite and its WAL stay on the local PVC. Repositories, LFS objects, attachments,
packages, and Actions data live on the NAS. Both stores are required for recovery.
The [local PVC](app/lvm-storage.yaml) uses thick LocalPV LVM with enforced
capacity. Monitor PVC capacity and NAS usage before importing large repositories.

## Backup and recovery

The backup job briefly stops Forgejo to stage a consistent copy of both stores,
validates SQLite on local storage, and resumes Forgejo before Kopiur uploads the
staged copy to S3. Staging is not an independent backup. If a backup pod dies
while Forgejo is paused, the `ForgejoStopped` alert fires after 15 minutes.

Provision a separate staging dataset with room for both stores. See the
[shared backup setup](../../cluster/kopiur/README.md#storage-and-credentials)
for repository initialization and credentials.

For recovery, suspend the Kopiur SnapshotSchedule, maintenance, and the
HelmRelease, then stop Forgejo. Connect to Kopia with the backup
Secret and restore one snapshot into an isolated destination. Restore its
`current/local/` and `current/nas/` trees together onto the corresponding volumes,
preserving configuration, generated secrets, host keys, and UID/GID 1000
permissions. Validate SQLite on local storage and run `git fsck` on restored
repositories before starting Forgejo. Resume Flux and the backup schedules after
verifying login, clone/push, LFS, and uploads.

To resume Forgejo after a stranded pause, inspect the failed backup job, then
remove the pause marker so later backups can run and scale Forgejo back up:

```sh
kubectl --context homelab -n forgejo annotate deployment/forgejo backup.jetersen.dev/forgejo-pause-
kubectl --context homelab -n forgejo scale deployment/forgejo --replicas=1
```

For a recovery that needs the helper while the registry is down, clone the
GitHub mirror, check out the helper's recorded source revision, and build it
locally with `docker build -f infrastructure/backup/image/Dockerfile -t
homelab-backup-helper:recovery .`. Run `docker run --rm
homelab-backup-helper:recovery --help` to verify it. A Kubernetes recovery job
needs that image imported into its node runtime or pushed to another reachable
registry first. Do not rely on the Forgejo registry as the only source of
recovery tooling.
