# Forgejo

Web access is available at `https://forgejo.jetersen.dev` on the LAN and Tailscale.
For Git SSH, add an account SSH key and use
`git@forgejo.jetersen.dev:owner/repository.git`. Tailscale grants must allow TCP 22
to the gateway host route.

The bootstrap administrator is `jetersen`; its initial password is the `password`
key in the `forgejo-admin` Secret. Change it at first login. The chart creates the
administrator only once and does not reset its password during upgrades.
Existing users link their GitHub identity by authenticating their Forgejo account
once. Keep the local administrator login available for recovery.

Application and chart major upgrades require Renovate dashboard approval and
manual merge because upgrades can change the database schema.

Pull requests default to rebase for merging and updating an outdated branch.
Existing repositories with explicit settings retain their own defaults.

## Storage

SQLite and its WAL stay on the local PVC. Repositories, LFS objects, attachments,
packages, and Actions data live on the NAS. Both stores are required for recovery.
Local-path storage has no enforced capacity quota; monitor node disk space and
NAS usage before importing large repositories.

## Backup and recovery

The backup job briefly stops Forgejo to stage a consistent copy of both stores,
validates SQLite on local storage, and resumes Forgejo before Kopiur uploads the
staged copy to S3. Staging is not an independent backup. A watchdog resumes a
pause older than 25 minutes, including after an abruptly terminated backup pod.

Provision a separate staging dataset with room for both stores. See the
[shared backup setup](../../cluster/kopiur/README.md#storage-and-credentials)
for repository initialization and credentials.

For recovery, suspend the Kopiur SnapshotSchedule, maintenance, the recovery
CronJob, and the HelmRelease, then stop Forgejo. Connect to Kopia with the backup
Secret and restore one snapshot into an isolated destination. Restore its
`current/local/` and `current/nas/` trees together onto the corresponding volumes,
preserving configuration, generated secrets, host keys, and UID/GID 1000
permissions. Validate SQLite on local storage and run `git fsck` on restored
repositories before starting Forgejo. Resume Flux and the backup schedules after
verifying login, clone/push, LFS, and uploads.
