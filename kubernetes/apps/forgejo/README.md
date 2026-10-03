# Forgejo

Forgejo uses the official Helm chart with an explicit application version.
Application and chart major upgrades require Renovate dashboard approval and
manual merge because upgrades can change the database schema. Flux manages the
application and backup jobs. Web access is available at
`https://forgejo.jetersen.dev` on the LAN and Tailscale. The gateway policy
allows private client networks and cluster workloads; public DNS publication
is disabled.

Git SSH uses port 22 on the existing gateway IP. Add an account SSH key in
Forgejo, then use `git@forgejo.jetersen.dev:owner/repository.git`. The container
listens on unprivileged port 2222. Tailscale grants must allow TCP 22 to the
gateway host route.

Registration and anonymous browsing are disabled. The bootstrap administrator
is `jetersen`; its initial password is the `password` key in the
`forgejo-admin` Kubernetes Secret. Change it at first login. The chart creates
the administrator only once and does not reset its password during upgrades.
GitHub OAuth is configured for browser login, using a separate OAuth app owned
by `jetersen-cloud`. Its callback is
`https://forgejo.jetersen.dev/user/oauth2/GitHub/callback`. Client credentials
are SOPS-encrypted in `forgejo-github-oauth`; it requests only `user:email`.
Automatic registration is disabled. Existing users link their GitHub identity
by authenticating their Forgejo account once; account linking is not automatic.
Keep the local administrator login available for recovery.

Enable TOTP or WebAuthn security keys in account settings. Git over HTTPS can
use a scoped access token; store it in a credential manager. Git SSH keys and
HTTPS tokens remain managed by Forgejo regardless of browser login provider.

## Storage

The 5 GiB local PVC contains SQLite, its WAL, configuration and generated
secrets, SSH host keys, queues, and indexes. A dedicated NAS dataset contains
repositories, LFS objects, attachments, avatars, packages, repository archives,
and Actions logs/artifacts. `[storage].PATH` supplies the subsystem defaults;
`[repository].ROOT` supplies the Git repository path.

The application runs once, as UID/GID 1000, with a Recreate upgrade strategy.
SQLite WAL stays on local storage. The in-memory `twoqueue` cache follows
Forgejo's small-instance recommendation; database sessions and local LevelDB
queues avoid another service.

NAS volumes use NFSv4, retained PVs, and node-restricted exports. Dataset
locations and storage credentials are SOPS-encrypted. PVCs are excluded from
Flux pruning. Local-path storage is node-local and has no enforced capacity
quota; monitor node disk space and dataset usage before importing large repos.

## Backup and recovery

At 03:00 UTC, `forgejo-backup` stages both stores on a separate NAS dataset.
It first copies while Forgejo is online, stops the deployment, waits for all
application pods to terminate, then performs a checksum synchronization.
It validates a local copy of the staged SQLite database and resumes Forgejo
before uploading an encrypted Kopia snapshot to the dedicated S3 repository.
Staging is not an independent backup. The S3 snapshot is the offsite copy.

Retention keeps 3 latest, 14 daily, 8 weekly, and 6 monthly snapshots.
Daily maintenance runs at 10:00 UTC. Failed and stale jobs use the existing
backup alerts. A five-minute watchdog resumes a pause older than 25 minutes,
including after an abruptly terminated backup pod. Copy or validation failure
resumes the application and prevents upload.

Provision an empty, separate staging dataset with room for both stores. Use the
existing SOPS manifests as the schema for NAS volumes, administrator credentials,
and the backup connection. Resolve credentials through Varlock, keep NAS destination
records private, and encrypt protected values before writing manifests. Review
existing storage and credentials before replacing them. Initialize the dedicated
S3 repository once using the backup runner's `--initialize` option; scheduled jobs only connect
and fail if the repository is unavailable.

For recovery, suspend the backup and recovery CronJobs and the HelmRelease,
then stop Forgejo. Connect to Kopia with the backup Secret and restore one
snapshot into an isolated destination. Restore its `local/` and `nas/` trees
together onto the corresponding volumes, preserving configuration, generated
secrets, host keys, and UID/GID 1000 permissions. Validate SQLite on local
storage and run `git fsck` on restored repositories before starting Forgejo.
Keep the backup password recoverable outside the cluster. Resume Flux and
the backup schedules after verifying login, clone/push, LFS, and uploads.

References: [Forgejo storage](https://forgejo.org/docs/v15.0/admin/setup/storage/),
[recommended settings](https://forgejo.org/docs/v15.0/admin/setup/recommendations/),
and [SQLite WAL restrictions](https://sqlite.org/wal.html).
