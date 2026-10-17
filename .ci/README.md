# CI

Forgejo publishes workload images and deploys DNS and TrueNAS changes. Forgejo
and GitHub both publish the Flux OCI artifact and run Go checks. See the
[Forgejo workflows](../.forgejo/workflows) for triggers and runner selection.

Jobs use Forgejo secrets or short-lived Authorized Integration tokens directly.
Varlock resolves credentials for local commands.

## Publication

The Flux publisher validates manifests, retains `sha-<commit>` tags, and advances
`main` only at the current branch head. Remote Kustomize dependencies must be
bundled during publication so Flux can build without network access. Helm charts
and container images are fetched separately.

Workload images publish only to Forgejo. Public packages allow anonymous pulls
from the LAN and tailnet; GitHub-hosted runners cannot reach the registry. The
Flux artifact also publishes to GHCR for bootstrap recovery.

`backup-helper` and `runner-job` have independent SemVer releases. `git-cliff`
uses conventional commits affecting each component's selected inputs: `feat`
bumps minor, breaking changes bump major, and other changes bump patch.
[image-inputs.sh](image-inputs.sh) defines those inputs: backup-helper excludes
its Go tests, while runner-job includes the DNS compatibility tests. Keep workflow
path filters in sync with that script.

A `<component>/vX.Y.Z` Git tag reserves each release before building. Reruns reuse
it and preserve published image digests. Kubernetes pins versions and digests;
Renovate updates them. The `main` image tag advances only while component inputs
are still current.

After image publication, [image retention](image-retention.mjs) keeps the newest
three stable releases of each workload image, `main` and `keep-*` tags, and versions
under 30 days old. It protects version and digest pins in Kubernetes manifests and
the Rocket runner configuration and running CI containers, including child manifests
of retained OCI indexes.
Cleanup refuses stale checkouts and changing inventories. The native Forgejo Flux
cleanup rule remains separate. Retention runs after publication or a manual rerun
of the image publication workflow; it does not run on a daily timer.

Preview workload image retention locally with `npm exec -- varlock run -- node
.ci/image-retention.mjs`. Add `--apply` to delete eligible versions from a checkout
at `origin/main`. Rebuild deleted releases from their source tags when needed;
rebuilt digests may differ.

The [runner image](../infrastructure/forgejo/runner/Dockerfile) bundles build and
style tools, Pulumi, Flux, and git-cliff. `setup-tool` reads versions from its
Dockerfile and uses upstream setup actions only when the bundled version differs.
This lets workflows run before a new runner image reaches both runners.

Code-style workflows use the [CI worker pool](../kubernetes/apps/forgejo/ci/README.md).
They run the tools bundled in the published runner image, so changes that only bump
tool versions skip them; the runner image check builds and validates those. Branches
are checked through pull requests, and only `main` pushes run checks directly.
Docker builds and deployment workflows use the persistent runners. See the
[shared actions](actions/) and workflow path filters for checks and publication
triggers.

## Forgejo integrations

Configure Authorized Integrations with these repository variables:

| Audience variable | Permission | Workflow |
| --- | --- | --- |
| `OCI_PACKAGES_AUDIENCE` | `write:package` | `publish-oci.yaml`, `publish-images.yaml` |
| `IMAGE_RELEASE_AUDIENCE` | `write:repository` | `publish-images.yaml` |
| `RENOVATE_AUDIENCE` | Repository updates as the Renovate bot | `renovate.yaml` |
| `RENOVATE_PACKAGES_AUDIENCE` | `read:package`, owned by the package owner | `renovate.yaml` |

Restrict claims to this repository, `refs/heads/main`, and the listed workflows.
Publishers need `push` and `workflow_dispatch`; Renovate needs `schedule` and
`workflow_dispatch`. Renovate's Forgejo API token does not authenticate Docker
lookups, which use the separate package integration through `hostRules`.
Homelab [update rules](../.renovate/autoMerge.json5) prefer the newest eligible
release instead of competing major, minor, and patch PRs. Talos and Kubernetes
retain separate patch PRs so reviewed minor upgrades do not block maintenance
of the running minor. Compatibility constraints and approval gates still apply. Sonarr's
numeric image tags do not identify prereleases, so the policy generator restricts
them to the latest stable GitHub release; major migrations still require review.

The scheduled Renovate run scans both repositories. Manual runs can select one
repository with the `repository` input; `all` keeps the shared run. Use `dry_run`
to inspect updates without writing branches or PRs.
Token requests use `actions/github-script` with `core.getIDToken(audience)`, which
also masks the token in runner logs.

The Renovate job also updates `jetersen/dotfiles`. Its identity belongs to the
Renovate bot and is limited to this main-branch workflow; repository collaborator
permissions control which repositories it can change. Allowed post-upgrade
commands refresh Claude Code's upstream manifest and regenerate `flake.lock`
after a pinned upstream release tag changes.

GitHub dependency lookups use a separate metadata-read-only GitHub App installed
on a public repository. Set `GH_READ_APP_CLIENT_ID` and
`GH_READ_APP_PRIVATE_KEY` in this repository's Forgejo Actions settings. The job
requests short-lived installation tokens; it does not write to GitHub.

See [DNS setup](../infrastructure/dns/README.md) and
[TrueNAS setup](../infrastructure/truenas/README.md) for their deployment credentials.

## Flux webhook

Link the `jetersen/homelab/flux` package to the `homelab` repository and configure
a JSON webhook for package events. Use `flux-system/webhook-token`'s `token` as
the secret. The target is `https://webhook.jetersen.dev/flux` followed by the
`forgejo-oci-receiver` Receiver's `status.webhookPath`. Keep TLS verification
enabled and the hostname in Forgejo's webhook allowlist.

The [receiver](../kubernetes/cluster/flux-instance/app/forgejo-oci-receiver.yaml)
validates signatures and filters package events. Source polling remains the
fallback; Git push events can arrive before the artifact is published.

## Live upgrade policy

Renovate reads deployed versions from Kromgo and support matrices from the
[kubernetes-compatibility cache](https://forgejo.jetersen.dev/jetersen/kubernetes-compatibility).
The [policy generator](renovate-upgrade-policy.mjs) defines the version endpoint,
validation, and freshness limits. The runner needs LAN or tailnet access to that
endpoint. Missing, ambiguous, or stale inputs stop the workflow.

Kubernetes upgrades must satisfy the deployed Cilium, Envoy Gateway, Flux,
cert-manager, and Talos matrices. Talos minor upgrades must support the running
Kubernetes minor. Proposals cannot downgrade or skip a minor. Only patches on
the live minor auto-merge, subject to the
[release-age rules](../.renovate/autoMerge.json5); minor upgrades require dashboard
approval and manual merge. Do not override the generated version bounds or patch
automerge rules in repository presets.

## Local checks

```sh
node --test .ci/renovate-upgrade-policy.test.mjs .ci/setup-tool.test.mjs
node --test .ci/image-publishing.test.mjs .ci/image-retention.test.mjs
go -C infrastructure/backup/image test -race ./...
go -C infrastructure/backup/image vet ./...
```

Image publication tests need Git, git-cliff, Bash, and jq.

To inspect the live upgrade policy without changing the cluster or Renovate:

```sh
npm exec -- varlock run -- node .ci/renovate-upgrade-policy.mjs
```
