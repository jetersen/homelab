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
uses conventional commits affecting each component's runtime inputs: `feat`
bumps minor, breaking changes bump major, and other changes bump patch. Test-only
changes do not create releases. Keep workflow path filters and
[image-inputs.sh](image-inputs.sh) in sync.

A `<component>/vX.Y.Z` Git tag reserves each release before building. Reruns reuse
it and preserve published image digests. Kubernetes pins versions and digests;
Renovate updates them. The `main` image tag advances only while component inputs
are still current.

The [runner image](../infrastructure/forgejo/runner/Dockerfile) bundles build and
style tools, Pulumi, Flux, and git-cliff. `setup-tool` reads versions from its
Dockerfile and uses upstream setup actions only when the bundled version differs.
This lets workflows run before a new runner image reaches both runners.

Go checks run directly through the shared `check-go` action. Renovate runs in its
own pinned job container. Docker builds and smoke tests remain for published
images; runner validation has its own workflow so unrelated code changes do not
rebuild it. Registry login and logout use `docker/login-action` in each publisher.

Code-style workflows have separate language path filters and use `ci-kubernetes`.
KEDA scales that repository-scoped pool from zero to two one-job workers. Each
worker runs in the bundled tool image without Docker or Kubernetes API access;
Docker builds and deployment workflows continue to use the persistent runners.
See the [CI worker configuration](../kubernetes/apps/forgejo/ci/README.md).

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
Use Renovate's `dry_run` input to inspect updates without writing branches or PRs.
Token requests use `actions/github-script` with `core.getIDToken(audience)`, which
also masks the token in runner logs.

See [DNS setup](../infrastructure/dns/README.md) and
[TrueNAS setup](../infrastructure/truenas/README.md) for their deployment credentials.

## Flux webhook

Link the `jetersen/homelab/flux` package to the `homelab` repository and configure
a JSON webhook for package events. Use `flux-system/webhook-token`'s `token` as
the secret. The target is `https://webhook.jetersen.dev/flux` followed by the
`forgejo-oci-receiver` Receiver's `status.webhookPath`. Keep TLS verification
enabled and the hostname in Forgejo's webhook allowlist.

The receiver accepts signed `created` events for the `main` tag, including
overwrites. It also accepts an empty `X-GitHub-Event` header because Forgejo sends
one for package events. Source polling remains the fallback; Git push events
can arrive before the artifact is published.

## Live upgrade policy

Renovate reads deployed versions from Kromgo and support matrices from the
[kubernetes-compatibility cache](https://forgejo.jetersen.dev/jetersen/kubernetes-compatibility).
The runner needs LAN or tailnet access to `upgrade-versions.lan.jetersen.dev`.
Missing or ambiguous metrics, metrics older than two minutes, invalid matrices,
or a cache older than 45 days stop the workflow.

Kubernetes upgrades must satisfy the deployed Cilium, Envoy Gateway, Flux,
cert-manager, and Talos matrices. Talos minor upgrades must support the running
Kubernetes minor. Proposals cannot downgrade or skip a minor. Only patches on
the live minor auto-merge, after a three-day release age; minor upgrades require
dashboard approval and manual merge. Do not override the generated version bounds
or patch automerge rules in repository presets.

## Local checks

```sh
node --test .ci/renovate-upgrade-policy.test.mjs .ci/setup-tool.test.mjs
node --test .ci/image-publishing.test.mjs
go -C infrastructure/backup/image test -race ./...
go -C infrastructure/backup/image vet ./...
```

Image publication tests need Git, git-cliff, Bash, and jq.

To inspect the live upgrade policy without changing the cluster or Renovate:

```sh
npm exec -- varlock run -- node .ci/renovate-upgrade-policy.mjs
```
