# OVHcloud backup infrastructure

Pulumi C# manages private Frankfurt One Zone buckets in a European OVHcloud
Public Cloud project. The account, payment method, project, and region activation
are prerequisites. The program creates a shared owner without S3 credentials,
a Kopia bucket, and a separate versioned Pulumi state bucket. Each bucket has its
own user, scoped policy, and S3 credentials. Kopia cannot access the state bucket.

The provider uses `ovh-eu` and region `DE`. Kopia uses region `de` and endpoint
`s3.de.io.cloud.ovh.net`, where uploads default to Standard storage. Storage
class is an upload setting. Kopia manages retention; its bucket has no
lifecycle expiry, archive transitions, versioning, Object Lock, or replication.
The state bucket expires noncurrent versions after 90 days and aborts incomplete
multipart uploads after seven days under `.pulumi/`. A separate rule removes
expired delete markers across the bucket because OVH rejects filters on that rule.
Current objects, including checkpoints and Pulumi history files, do not expire.
The state user can list the bucket and read, write, and delete objects under
`.pulumi/`, but cannot change lifecycle rules, disable versioning, or administer
buckets or ACLs. Versioning provides recovery history, not immutable retention.

All ten OVH resources use `Protect` and `RetainOnDelete`. Removing protection
requires a separate recovery and deletion review: the provider can empty a bucket
when deleting it. Retained resources remain billable and require import if removed
from state. OVH omits the policy `Version` field when reading policies.

## Credentials

Use Varlock to resolve credentials from Proton Pass. Keep values out of source,
chat, command arguments, and logs. Configure these items yourself:

- `Personal/OVHcloud Homelab API`: custom fields `application-key`,
  `application-secret`, and `consumer-key` for the OVH control plane.
- `Personal/Homelab Pulumi`: a separate encryption passphrase in the password field.

Create API credentials through [the European token page](https://api.ovh.com/createToken/).
Scope GET, POST, and PUT rights to `/cloud/project/PROJECT_ID` and its child paths.
The retained-resource setup does not require DELETE or account-wide rights.
Set `BACKUP_IAC_CONFIGURED=true` in local Varlock overrides once the items exist.
Keep `BACKUP_S3_CONFIGURED=false` until the generated S3 credentials are stored.

Provider inputs and credential outputs are secret in Pulumi. Do not use
`--show-secrets` interactively or export decrypted state into the repository.
For credential transfer, capture decrypted outputs only in memory and pass values
to the password manager through stdin. Keep any one-off helper outside the repository.

## State and deployment

Use Pulumi CLI 3.254.0 or later and .NET 10. `Pulumi.yaml` and Varlock default to
the OVH S3 backend. Set `PULUMI_STATE_CONFIGURED=false` explicitly for a first
deployment to bootstrap the state bucket against local state. Always run Pulumi through Varlock, including config
and stack commands. Stack settings, local state, and build output are ignored by
Git. Secret fields are encrypted, but other state metadata is not. Keep recovery
copies of state and stack settings in protected storage outside the repository,
with the passphrase stored separately.

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
against local stack settings. Import existing resources instead of creating duplicates. Bucket import
IDs are `PROJECT_ID/DE/BUCKET_NAME`; user import IDs are `PROJECT_ID/USER_ID`.
Review ownership before adopting a bucket.

Review the live preview before authorizing `pulumi up`. Code changes do not
authorize provisioning. Initial creates are the provider and ten OVH resources,
with no project creation, compute, replica, or deletion.

## Migrating local state to OVH

Keep `PULUMI_STATE_CONFIGURED=false` until the state bucket and credential exist.
Preview and provision them against the local backend after deployment approval.
For an existing backup stack this adds five OVH resources: the state bucket,
lifecycle policy, user, access policy, and credential. Lifecycle expiry permanently
removes superseded versions after the retention period; keep independent recovery
copies for longer retention.

Store Pulumi's `stateAccessKeyId` and `stateSecretAccessKey` outputs in
`Personal/OVHcloud Homelab Pulumi S3`, with the access key in username and secret
key in password. Perform the transfer in your own terminal through Varlock with
`BACKUP_IAC_CONFIGURED=true` and `PULUMI_STATE_CONFIGURED=false`. Preserve an
existing login and resolve duplicate names before storing credentials.

Before migrating, pause Pulumi updates and copy the entire local backend and
`Pulumi.homelab.yaml` to protected storage outside the repository. Keep the current
`Personal/Homelab Pulumi` passphrase. Set `PULUMI_STATE_CONFIGURED=true` and
`BACKUP_IAC_CONFIGURED=true` in local Varlock overrides, then run:

```bash
npm exec -- varlock load --agent
npm exec -- varlock run -- pulumi -C infrastructure/backup login 's3://jetersen-homelab-pulumi?endpoint=https://s3.de.io.cloud.ovh.net&region=de&s3ForcePathStyle=true&awssdk=v2'
npm exec -- varlock run -- pulumi -C infrastructure/backup stack migrate 'file://./.pulumi-state' homelab --secrets-provider passphrase
npm exec -- varlock run -- pulumi -C infrastructure/backup whoami -v
npm exec -- varlock run -- pulumi -C infrastructure/backup preview --stack homelab --refresh --expect-no-changes
```

The S3 backend uses `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` resolved by
Varlock from the dedicated state login. Remove inherited `AWS_SESSION_TOKEN` or
AWS credential overrides when using these long-lived OVH credentials. TLS stays
enabled with normal certificate verification.

Migration retains the local source, imports the latest checkpoint and configuration,
and re-encrypts secrets using the target passphrase provider. Verify resource URNs
and IDs, secret outputs, and a no-change refreshed preview before treating OVH as
authoritative. Then move the retired local backend to protected storage outside
the repository. Historical updates remain in that recovery copy. Credential
resource IDs contain access-key identifiers even though secret outputs are
encrypted. Never run updates against both copies.

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
password. Perform the transfer in your own terminal through Varlock with
`BACKUP_IAC_CONFIGURED=true`. Preserve existing logins and repository passwords;
resolve duplicate names or incompatible item types before storing credentials.

After storing the items, set `BACKUP_S3_CONFIGURED=true` in local Varlock overrides,
confirm `BACKUP_S3_BUCKET`, and validate Varlock. Use the existing application
Secret manifests as the schema for new connections. Resolve credentials through
Varlock and encrypt the payload with SOPS using the destination filename and the
repository's `.sops.yaml` rules. Keep plaintext in memory and verify that protected
values are encrypted before writing manifests. Review existing connections before
replacing them.
See [application backup setup](../../kubernetes/cluster/volsync/README.md) for
consistency, manual backup, and recovery procedures.

## Local validation

Run from this directory; these checks call no cloud APIs:

```bash
dotnet restore Homelab.Backup.csproj --locked-mode
dotnet build Homelab.Backup.csproj --no-restore
dotnet run --project tests/Backup.Tests.csproj
python -m unittest discover -s tests -p 'test_*.py'
```

References:

- [OVH Pulumi provider](https://www.pulumi.com/registry/packages/ovh/installation-configuration/)
- [OVH S3 authorization](https://docs.ovhcloud.com/en/guides/storage-and-backup/object-storage/s3-identity-and-access-management)
- [Pulumi state backends](https://www.pulumi.com/docs/iac/concepts/state-and-backends/)
- [Pulumi DIY backend permissions](https://www.pulumi.com/docs/iac/operations/stack-management/using-a-diy-backend/)
- [Pulumi secrets](https://www.pulumi.com/docs/iac/concepts/secrets/)
