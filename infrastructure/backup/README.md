# OVHcloud backup infrastructure

Pulumi C# manages a private Frankfurt One Zone bucket in a European OVHcloud
Public Cloud project. The account, payment method, project, and region activation
are prerequisites. The program creates the bucket, a separate owner without S3
credentials, a Kopia user, its bucket-scoped policy, and S3 credentials.

The provider uses `ovh-eu` and region `DE`. Kopia uses region `de` and endpoint
`s3.de.io.cloud.ovh.net`, where uploads default to Standard storage. Storage
class is an upload setting. Kopia manages retention; the stack configures no
lifecycle expiry, archive transitions, versioning, Object Lock, or replication.

All five OVH resources use `Protect` and `RetainOnDelete`. Removing protection
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

Provider inputs and credential outputs are secret in Pulumi. Never use
`--show-secrets` or export decrypted state into the repository.

## State and deployment

Use Pulumi CLI and .NET 10. `Pulumi.yaml` selects a local state backend; stack
settings, state, and build output are ignored by Git. Secret fields are encrypted,
but other state metadata is not. Keep recovery copies of state and stack settings
in protected storage outside the repository, with the passphrase stored separately.

Run from the repository root after configuring Proton Pass:

```bash
npm exec -- varlock load --agent
mkdir -p infrastructure/backup/.pulumi-state
npm exec -- varlock run -- pulumi -C infrastructure/backup stack init homelab --secrets-provider passphrase
pulumi -C infrastructure/backup config set projectId PROJECT_ID --stack homelab
pulumi -C infrastructure/backup config set bucketName BUCKET_NAME --stack homelab
npm exec -- varlock run -- pulumi -C infrastructure/backup preview --stack homelab --diff
```

For an existing stack, use `stack select homelab`. `projectId` is required;
`bucketName` has a default in `Pulumi.yaml`. Confirm both against local stack
settings. Import existing resources instead of creating duplicates. Bucket import
IDs are `PROJECT_ID/DE/BUCKET_NAME`; user import IDs are `PROJECT_ID/USER_ID`.
Review ownership before adopting a bucket.

Review the live preview before authorizing `pulumi up`. Code changes do not
authorize provisioning. Expected creates are the provider and five OVH resources,
with no project creation, compute, replica, or deletion.

## S3 credentials and Kubernetes connections

Run the transfer in your own terminal from the repository root:

```bash
BACKUP_IAC_CONFIGURED=true npm exec -- varlock run -- python infrastructure/backup/store-backup-secrets.py --store
```

The helper creates `Personal/OVHcloud Homelab S3` with the access key in username
and secret key in password, and `Personal/Homelab Kopia` with a separate generated
repository password. It passes values through memory and stdin, preserves existing
logins, and refuses duplicate names or incompatible item types. Without `--store`,
it checks item names without creating anything. Agents must not run storing mode.

After storing the items, set `BACKUP_S3_CONFIGURED=true` in local Varlock overrides,
confirm `BACKUP_S3_BUCKET`, and validate Varlock. Generate missing SOPS connections
only after reviewing the credential references:

```bash
BACKUP_S3_CONFIGURED=true npm exec -- varlock run -- python infrastructure/backup/prepare-kubernetes-secrets.py
```

The helper refuses existing manifests and does not write plaintext files.
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
- [Pulumi secrets](https://www.pulumi.com/docs/iac/concepts/secrets/)
