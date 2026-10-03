# OVHcloud backup infrastructure

Pulumi manages private Frankfurt One Zone buckets for Kopia and Pulumi state.
An OVHcloud European Public Cloud project with billing and region activation is
required. The buckets use separate scoped credentials.

Resources use `Protect` and `RetainOnDelete`. Review recovery before removing
protection: the provider can empty a bucket when deleting it. Retained resources
remain billable and require import if removed from state.

## Credentials

Resolve credentials from these Proton Pass items through Varlock:

- `Personal/OVHcloud Homelab API`: custom fields `application-key`,
  `application-secret`, and `consumer-key` for the OVH control plane.
- `Personal/Homelab Pulumi`: a separate encryption passphrase in the password field.

Create API credentials through [the European token page](https://api.ovh.com/createToken/).
Scope GET, POST, and PUT rights to `/cloud/project/PROJECT_ID` and its child paths.
The retained-resource setup does not require DELETE or account-wide rights.
Set `BACKUP_IAC_CONFIGURED=true` in local Varlock overrides once the items exist.
Keep `BACKUP_S3_CONFIGURED=false` until the generated S3 credentials are stored.

Transfer decrypted credential outputs in memory through stdin. Keep decrypted
state and one-off transfer helpers outside the repository.

## State and deployment

Use Pulumi CLI 3.254.0 or later and .NET 10. `Pulumi.yaml` and Varlock default to
the OVH S3 backend. Set `PULUMI_STATE_CONFIGURED=false` explicitly for a first
deployment to bootstrap the state bucket against local state. Run all Pulumi
commands through Varlock. State metadata can contain credential identifiers even
when secret values are encrypted. Keep recovery copies of state and stack settings
in protected storage outside the repository, with the passphrase stored separately.

For a first deployment, set `PULUMI_STATE_CONFIGURED=false` in local Varlock
overrides and run from the repository root after configuring Proton Pass:

```bash
npm exec -- varlock load --agent
mkdir -p infrastructure/backup/.pulumi-state
npm exec -- varlock run -- pulumi -C infrastructure/backup stack init homelab --secrets-provider passphrase
npm exec -- varlock run -- pulumi -C infrastructure/backup config set projectId PROJECT_ID --stack homelab
npm exec -- varlock run -- pulumi -C infrastructure/backup config set bucketName BUCKET_NAME --stack homelab
npm exec -- varlock run -- pulumi -C infrastructure/backup preview --stack homelab --diff
```

For an existing stack, use `stack select homelab`. `projectId` is required;
`bucketName` and `stateBucketName` have defaults in `Pulumi.yaml`. Confirm them
against local stack settings. Import existing resources instead of creating
duplicates. Bucket import IDs are `PROJECT_ID/DE/BUCKET_NAME`; user import IDs
are `PROJECT_ID/USER_ID`. Review ownership before adopting a bucket.

Review the live preview before running `pulumi up`.

## Migrating local state to OVH

Keep `PULUMI_STATE_CONFIGURED=false` until the state bucket and credential exist.
Provision them against the local backend. Superseded state bucket versions expire
after 90 days; keep independent recovery copies for longer retention.

Store Pulumi's `stateAccessKeyId` and `stateSecretAccessKey` outputs in
`Personal/OVHcloud Homelab Pulumi S3`, with the access key in username and secret
key in password. Transfer through Varlock with `BACKUP_IAC_CONFIGURED=true` and
`PULUMI_STATE_CONFIGURED=false`. Preserve existing logins.

Before migrating, pause Pulumi updates and copy the entire local backend and
`Pulumi.homelab.yaml` to protected storage outside the repository. Keep the current
`Personal/Homelab Pulumi` passphrase. Set `PULUMI_STATE_CONFIGURED=true` and
`BACKUP_IAC_CONFIGURED=true` in local Varlock overrides, then run:

```bash
npm exec -- varlock load --agent
npm exec -- varlock run -- pulumi -C infrastructure/backup login 's3://STATE_BUCKET_NAME?endpoint=https://s3.de.io.cloud.ovh.net&region=de&s3ForcePathStyle=true&awssdk=v2'
npm exec -- varlock run -- pulumi -C infrastructure/backup stack migrate 'file://./.pulumi-state' homelab --secrets-provider passphrase
npm exec -- varlock run -- pulumi -C infrastructure/backup whoami -v
npm exec -- varlock run -- pulumi -C infrastructure/backup preview --stack homelab --refresh --expect-no-changes
```

The S3 backend uses `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` resolved by
Varlock from the dedicated state login. Remove inherited `AWS_SESSION_TOKEN` or
AWS credential overrides when using these long-lived OVH credentials.

Verify resource URNs and IDs, secret outputs, and a no-change refreshed preview
before treating OVH as authoritative. Move the retired local backend to protected
storage outside the repository; historical updates remain in that recovery copy.
Never run updates against both copies.

To roll back before subsequent remote updates, stop updates, restore the saved
backend to `.pulumi-state` and the matching stack settings, set
`PULUMI_STATE_CONFIGURED=false`, and verify the local preview.
If OVH has newer updates, recover its latest checkpoint before switching back;
the retained bootstrap copy is stale. Recovery needs both the S3 login and the
encryption passphrase outside the cluster.

## S3 credentials and Kubernetes connections

Store Pulumi's `accessKeyId` and `secretAccessKey` outputs in
`Personal/OVHcloud Homelab S3`, with the access key in username and secret key in
password. Create `Personal/Homelab Kopia` with a separate generated repository
password. Transfer through Varlock with `BACKUP_IAC_CONFIGURED=true`. Preserve
existing logins and repository passwords.

After storing the items, set `BACKUP_S3_CONFIGURED=true` in local Varlock overrides,
confirm `BACKUP_S3_BUCKET`, and validate Varlock. Use the existing application
Secret manifests as the schema for new connections and encrypt payloads with
SOPS using the destination filename and the repository's `.sops.yaml` rules.
See [application backup setup](../../kubernetes/cluster/kopiur/README.md) for
consistency, manual backup, and recovery procedures.

## Local validation

Run from this directory; these checks call no cloud APIs:

```bash
dotnet restore Homelab.Backup.csproj --locked-mode
dotnet build Homelab.Backup.csproj --no-restore
dotnet run --project tests/Backup.Tests.csproj
```
