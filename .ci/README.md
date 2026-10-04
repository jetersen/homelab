# Publication workflows

Forgejo and GitHub run three independent workflows on `main`:

| Workflow | Automatic trigger | Output |
| --- | --- | --- |
| `publish-oci.yaml` | Every push | Validated Kubernetes manifests in the `flux` OCI artifact |
| `publish-images.yaml` | Image source, Dockerfile, or image publication changes | `backup-helper` and `runner-job` container images |
| `check-go.yaml` | Backup helper source or Go workflow changes | Go tests and vet results |

All three support manual dispatch. Go checks do not gate either publisher.
The shared actions under `.ci/actions/` publish to the workflow's registry.

Forgejo also runs `truenas.yaml` for the [TrueNAS Pulumi project](../infrastructure/truenas/README.md):
PRs receive a preview, and changes on `main` are applied using the shared S3 state
backend. It deploys independently of Flux.

Publishers retain immutable `sha-<commit>` tags and advance `main` after
verification. Flux requires the current branch head. Images allow newer commits
that leave image inputs unchanged, because unrelated commits do not trigger a
replacement image build. Keep the image workflow path filters and the shared
action's input comparison in sync.

Forgejo uses an Authorized Integration with `write:package` permission and the
audience stored in `OCI_PACKAGES_AUDIENCE`. Its claim rules must allow the
`workflow` values `publish-oci.yaml` and `publish-images.yaml`, restricted to this
repository, `refs/heads/main`, and the `push` and `workflow_dispatch` events.

Run the Go checks locally with:

```sh
docker build --target check -f infrastructure/backup/image/Dockerfile .
```

The default Dockerfile target builds the runtime image without running tests or
vet. Go module and compiler caches persist in BuildKit on each runner; separate
runners do not share those caches.

## Backup helper releases

The backup helper stays in this repository and publishes independent SemVer
image tags to Forgejo and GHCR. Kubernetes references use `version@sha256:digest`;
Renovate tracks newer versions. The `main` tag remains available for development.

Forgejo uses `git-cliff` with `.ci/backup-helper-cliff.toml` to calculate releases
from conventional commits affecting the helper's runtime inputs. `feat` bumps
minor; `feat!`, `feat(scope)!`, and `BREAKING CHANGE` footers bump major. Other
runtime changes, including dependency updates, bump patch. Test-only and
unrelated homelab changes do not create releases. The first release is `0.1.0`.

Forgejo reserves a `backup-helper/vX.Y.Z` Git tag before building. Reruns reuse
that tag and preserve an already published image's digest. The helper's revision,
version, and source timestamp come from its component commit, so unrelated
commits do not change release metadata or invalidate compilation.

Forgejo mirrors release tags to GitHub using the repository deploy key stored in
its `GH_RELEASE_DEPLOY_KEY` Actions secret. Tag pushes trigger GHCR publication;
GitHub main builds wait for the corresponding tag. Hosted runners never need
access to the internal Forgejo hostname. Both registries use the same version
when jobs are delayed or retried.

The Forgejo image workflow also uses a repository-scoped Authorized Integration
with `write:repository` for release tags, referenced by `IMAGE_RELEASE_AUDIENCE`.
Restrict it to `publish-images.yaml`, this repository, `refs/heads/main`, and
`push`/`workflow_dispatch`. The GitHub deploy key has write access only to this
repository; its publisher needs `contents: read` and `packages: write`.

## Renovate registry authentication

Forgejo Renovate uses its bot integration for repository updates and a separate
Authorized Integration owned by `jetersen` for private registry lookups. The
package integration grants only `read:package`; store its audience in the
repository variable `RENOVATE_PACKAGES_AUDIENCE`. Restrict its claims to
`renovate.yaml`, repository ID `1`, owner ID `1`, `refs/heads/main`, and the
`schedule` and `workflow_dispatch` events.

The workflow supplies this short-lived token through a Docker `hostRules` entry
for `forgejo.jetersen.dev`. Forgejo API authentication alone does not authenticate
Docker lookups. Use the workflow's `dry_run` input to verify dependency lookups
without creating branches or pull requests. Scheduled runs and manual runs with
`dry_run` disabled leave `RENOVATE_DRY_RUN` unset so Renovate can apply updates.
