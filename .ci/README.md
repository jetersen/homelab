# OCI publication

The Forgejo and GitHub `publish-oci.yaml` workflows run on pushes to `main` and
manual dispatches from `main`. Both use the same local composite action and
publish these packages to their own registry:

| Package | Forgejo Packages | GitHub Container Registry |
| --- | --- | --- |
| Flux configuration | `forgejo.jetersen.dev/jetersen/homelab/flux` | `ghcr.io/jetersen/homelab/flux` |
| Forgejo staging image | `forgejo.jetersen.dev/jetersen/homelab/forgejo-staging` | `ghcr.io/jetersen/homelab/forgejo-staging` |

Each package gets a `sha-COMMIT_SHA` tag. The workflows advance `main` after the
image tests, runtime smoke test, Kustomize builds, and artifact upload/download
comparison pass. A superseded revision keeps its revision tags without advancing
`main`. Pin a revision tag or digest for recovery and rollback.

The artifact contains only Git-tracked `kubernetes/apps`, `kubernetes/cluster`,
`kubernetes/components`, and `kubernetes/flux`, retaining those paths. SOPS files
remain encrypted. Talos configurations, local credentials, and the separate
private secrets repository are outside the artifact. Both publishers use a common
source annotation and reproducible Flux packaging for the mirrored Git revision.

GitHub uses its workflow `GITHUB_TOKEN` with `packages: write`. Configure GHCR
package visibility or read-only pull credentials before bootstrap; packages do
not automatically become public because their source repository is public.

For Forgejo v16:

1. Enable Actions on the canonical `jetersen/homelab` repository and register an
   isolated Linux amd64 runner with the `ubuntu-24.04` label. Provide Node.js 24,
   Bash, Git, Docker with BuildKit, kubectl, curl, jq, and tar. The runner needs
   registry access and permission to build and run containers.
2. Create a Forgejo Actions (Local) Authorized Integration on the package owner's
   account. Restrict it to `jetersen/homelab`, workflow `publish-oci.yaml`,
   `refs/heads/main`, and the `push` and `workflow_dispatch` events. Grant package
   read/write access. The automatic workflow token does not grant this access.
3. Put the integration's non-secret audience in repository variable
   `FORGEJO_PACKAGES_AUDIENCE`. The workflow exchanges its OIDC identity for a
   short-lived credential and logs in with `--password-stdin`.
4. Push-mirror Forgejo `main` to GitHub so both workflows build the same commit.
   Keep GitHub read-only for source changes after establishing the mirror.

GHCR provides an independent bootstrap and recovery source when Forgejo is down.
Use Forgejo Packages for normal reconciliation once it is restored. Flux has one
configured source URL; changing registries is an explicit operation. During
bootstrap, keep the reconciled Flux Instance pointed at GHCR until Forgejo is
available, including any staging image references that must work before recovery.

Publication does not change the live Flux source or staging Job image. Before
switching to OCI, update the root and child Kustomization `sourceRef` kinds,
Flux Instance sync configuration, registry pull credentials, and notifications
together. Keep the private secrets source separate.

See [Forgejo v16 Authorized Integrations](https://forgejo.org/docs/v16.0/user/api/authorized-integrations/),
[GHCR authentication and visibility](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
and [Flux OCI artifacts](https://fluxcd.io/flux/cheatsheets/oci-artifacts/).
