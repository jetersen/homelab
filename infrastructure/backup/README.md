# OVHcloud backup infrastructure

Pulumi C# manages the Frankfurt 1-AZ backup bucket in a European OVHcloud account.
European Public Cloud project `8f573109804548c5acd72a72af919479` is configured
in the local `homelab` stack; `projectId` remains required stack config.
The bucket and all five OVH resources were provisioned on 2026-10-03. The account, payment method,
and Public Cloud project are bootstrap prerequisites and are not managed by this stack.

On 2026-10-03, Varlock resolved the updated Proton Pass credentials and read-only
checks authenticated against `ovh-eu`, verified the project is active and Frankfurt
(`DE`) is `UP`, and found no Frankfurt buckets or project users. The API token has
GET, POST, and PUT rights on this project and its child paths, with no account-wide
or DELETE rights. The live `pulumi preview --stack homelab --diff --non-interactive`
passed and built with zero warnings/errors. After user approval, `pulumi up`
created the stack, OVH provider, and five protected OVH resources. The bucket owner
is user `825482`; Kopia is user `825483`, with one S3 credential. A refreshed update
then reported all seven resources unchanged. OVH strips the policy's `Version`
field on read, so the code omits it and a regression check covers that behavior.

Live S3 checks passed for list, region `de`, upload/download, Standard-class upload,
object deletion, multipart creation/upload/list/abort, denied anonymous reads, and
denied object ACL changes. All temporary test objects and multipart uploads were
removed. The first anonymous check through boto3 returned `InvalidRequest`; a raw
unsigned GET to the virtual-host endpoint correctly returned `403 AccessDenied`.
No Kopia repository or application backups exist yet.

The previous project `f2d4d802d8834a48819bd7828694f56c` belongs to the Canadian
control platform. On 2026-10-03, the user chose to switch to a European account.
The old project remains untouched and must not be used for this stack.
The replacement account and API credentials have now been verified against the
European API. OVH's [account FAQ](https://docs.ovhcloud.com/en/guides/account-and-service-management/account-information/faq-account-management)
requires a different contact email for a new subsidiary account and says Canadian
services cannot be moved between accounts. Canadian keys do not authenticate
against `ovh-eu`.

The program creates one private bucket, a separate bucket owner without S3
credentials, a Kopia user, its bucket-scoped S3 policy, and its S3 credentials.
The region is `DE`; Kopia uses `de` and `s3.de.io.cloud.ovh.net`. Uploads default
to Standard on that endpoint. Storage class is set per object by the uploading
client, not by a bucket-level storage-class setting in this provider.

No lifecycle expiry, archive transitions, versioning, Object Lock, or replication
is configured. Kopia manages repository retention. All five managed resources
use `Protect` and `RetainOnDelete`. The provider's bucket deletion implementation
can empty the bucket, so deliberately removing protection requires a separate
recovery and deletion review. Retained resources remain billable and need import
if removed from state and managed again.

## Credentials

The repo uses the Varlock skill for secret handling. Keep values out of chat,
source files, command arguments, and logs. API credentials below are for Pulumi's
OVH control plane; they are separate from the S3 key generated for Kopia.

1. Create an OVH API credential at [the EU token page](https://api.ovh.com/createToken/).
   Scope GET, POST, and PUT rights to `/cloud/project/8f573109804548c5acd72a72af919479`
   and `/cloud/project/8f573109804548c5acd72a72af919479/*`.
   The current retained-resource setup does not need DELETE
   rights. Avoid the account-wide `/*` rights shown in generic provider examples.
2. Store its three values in custom fields `application-key`, `application-secret`,
   and `consumer-key` in Proton Pass item `Personal/OVHcloud Homelab API`.
3. Store a separate generated Pulumi encryption passphrase in the password field
   of `Personal/Homelab Pulumi`. Keep it separate from the Kopia repository password.
4. Set `BACKUP_IAC_CONFIGURED=true` in your local Varlock overrides once those
   items exist. Keep `BACKUP_S3_CONFIGURED=false` until the generated S3 keys have
   been saved in Proton Pass. Agents may edit `.env.schema`, but do not edit your
   secret value files or fill secret values for you.

The `.env.schema` resolves all four fields only when IaC is enabled. Provider
inputs and S3 outputs are marked secret in Pulumi. User passwords are also secret
outputs in the official provider. Never use `--show-secrets` in agent-visible
commands or export decrypted state into the repository.

## State and preview

Use Pulumi CLI and .NET 10. The local backend is explicitly configured in
`Pulumi.yaml`; no Pulumi Cloud account is needed. It stores state under
`infrastructure/backup/.pulumi-state/`. Pulumi encrypts secret fields with the
passphrase; other state metadata is not encrypted. State, build output, and local
stack settings are ignored by Git.

Run from the repo root after filling the Proton Pass items:

```bash
npm exec -- varlock load --agent
mkdir -p infrastructure/backup/.pulumi-state
npm exec -- varlock run -- pulumi -C infrastructure/backup stack init homelab --secrets-provider passphrase
pulumi -C infrastructure/backup config set projectId 8f573109804548c5acd72a72af919479 --stack homelab
npm exec -- varlock run -- pulumi -C infrastructure/backup preview --stack homelab --diff
```

For an existing local stack, use `stack select homelab` instead of `stack init`.
Set the new European project ID explicitly; there is no project ID default.
The proposed bucket name `jetersen-homelab-kopia` is a project config default.
Choose a different bucket name before deployment if it is unavailable:

```bash
pulumi -C infrastructure/backup config set bucketName YOUR_BUCKET_NAME --stack homelab
```

Ensure the Frankfurt region is activated in this OVH project. If a bucket or user
has already been created manually, import it rather than trying to create a
duplicate. Bucket import IDs are `PROJECT_ID/DE/BUCKET_NAME`; user import IDs are
`PROJECT_ID/USER_ID`. Existing bucket ownership needs review before adoption.

Review the live preview before authorizing `pulumi up`. Preparing this code does
not authorize cloud provisioning. Expected creates are the provider and five OVH
resources; there should be no project creation, compute, replica, or deletion.

Run the prepared transfer in **your own terminal** from the repo root:

```bash
BACKUP_IAC_CONFIGURED=true npm exec -- varlock run -- python infrastructure/backup/store-backup-secrets.py --store
```

It creates `Personal/OVHcloud Homelab S3` with the generated access key in username
and secret key in password, plus `Personal/Homelab Kopia` with a separate generated
64-character repository password. It passes S3 credentials through process memory
and stdin, never through files, command arguments, or terminal output. CLI output
is withheld on failures, with the failed operation identified. It preserves existing
logins and creates only missing items, so rerunning after a partial failure is safe.
It rejects duplicate names or existing items of the wrong type. Password generation
uses the standalone CLI generator and passes its result to login creation through
stdin. The user has now created both logins. Varlock validated both and the separate
Pulumi passphrase on 2026-10-03. The agent has not executed storing mode.

Without `--store`, the helper checks item names only and creates nothing.
The Varlock skill requires users to fill their secret provider themselves; agents
must not execute the storing mode. After storing both items, set
`BACKUP_S3_CONFIGURED=true` in your local overrides and validate Varlock.
`BACKUP_S3_BUCKET` now defaults to the provisioned bucket name. Do not paste
credentials or the repository password into chat. Kopia backups and a pilot restore
are still required before creating schedules.

Back up the entire local state directory and the local `Pulumi.homelab.yaml`
settings independently of the cluster and retain the passphrase in Proton Pass.
Git contains the program, not its state. A future remote backend should use a
separate state bucket outside the Kopia repository, with its own access and
recovery plan. Credentials in encrypted state require both the state and passphrase
for recovery.

SOPS-encrypted connections for the paused Home Assistant and Zigbee pilots have been
prepared and decrypted in memory to verify they match Proton Pass. To regenerate
missing manifests after explicit credential review, use:

```bash
BACKUP_S3_CONFIGURED=true npm exec -- varlock run -- python infrastructure/backup/prepare-kubernetes-secrets.py
```

The helper refuses to overwrite existing manifests and never writes plaintext files.

Application backup and restore steps remain in
[the VolSync setup guide](../../kubernetes/cluster/volsync/README.md).

## Validation

Run from this directory:

```bash
dotnet restore Homelab.Backup.csproj --locked-mode
dotnet build Homelab.Backup.csproj --no-restore
dotnet run --project tests/Backup.Tests.csproj
python -m unittest discover -s tests -p 'test_*.py'
```

The mock checks validate regional placement, separate ownership, bucket-scoped
access with repository deletion and multipart support, secret credentials, and
deletion protection and the OVH policy format. They call no cloud APIs. Provisioning
and the live S3 permission checks passed; a Kopia pilot backup and restore are still
required. S3 checks do not prove application consistency or Kopia mover compatibility.

References:

- [Official OVH Pulumi provider and C# installation](https://www.pulumi.com/registry/packages/ovh/installation-configuration/)
- [OVH S3 authorization and owner ACL behavior](https://docs.ovhcloud.com/en/guides/storage-and-backup/object-storage/s3-identity-and-access-management)
- [Pulumi state backends](https://www.pulumi.com/docs/iac/concepts/state-and-backends/)
- [Pulumi secrets](https://www.pulumi.com/docs/iac/concepts/secrets/)
