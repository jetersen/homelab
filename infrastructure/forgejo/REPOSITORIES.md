# Repository ownership

Forgejo is the primary source for `jetersen/homelab` and the private
`jetersen/homelab-secrets` repository. Make commits and pull requests in Forgejo.
Their GitHub repositories are push mirrors of `main` and tags. Mirroring uses
separate repository deploy keys and runs after commits; it can overwrite changes
made directly in GitHub. Keep dependency automation and source edits in Forgejo.

Renovate runs every three hours through Forgejo Actions. Its configuration is
`.forgejo/renovate.json`; the GitHub Renovate configuration disables the hosted
bot on the mirror. Forgejo v16 Authorized Integrations constrain its short-lived
credential to the Renovate workflow on `main`. The former Konflate GitHub App
supplies short-lived, read-only tokens for upstream dependency lookups. A manual
Renovate dispatch with `dry_run` enabled inspects updates without creating PRs.

Konflate reviews Forgejo pull requests and receives signed Forgejo webhooks.
Its read and write credentials belong to a dedicated collaborator with access
only to the public homelab repository.
Forgejo protects `main` with the required `Konflate` status check and permits
direct pushes only from the owner. Renovate can merge PRs after that check passes.

The secrets repository remains private on both services and has no OCI publisher.
Flux reads it independently through a read-only SSH deploy key. Application
Secret manifests may live in the public repository when their payloads are
SOPS-encrypted. Keep decryption keys, bootstrap credentials, recovery material,
and sensitive inventory in the private repository or protected local storage.
Moving an encrypted file into a public repository also publishes its metadata
and permanently retains its ciphertext in Git history.

GitHub Packages provide independent OCI bootstrap artifacts. The public OCI
publisher uses an explicit manifest-directory allowlist and does not include the
private secrets repository or Talos configuration. See [OCI publication](../../.ci/README.md).

To stop mirroring, remove the Forgejo push mirror or its GitHub deploy key before
editing GitHub. To use GitHub for recovery, change the local Git remote and the
Flux source URLs explicitly; retain its SSH host trust and read credentials.
