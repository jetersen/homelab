# Publication workflows

Forgejo and GitHub run three independent workflows on `main`:

| Workflow | Automatic trigger | Output |
| --- | --- | --- |
| `publish-oci.yaml` | Every push | Validated Kubernetes manifests in the `flux` OCI artifact |
| `publish-images.yaml` | Image source, Dockerfile, or image publication changes | `backup-helper` and `runner-job` container images |
| `check-go.yaml` | Backup helper source or Go workflow changes | Go tests and vet results |

All three support manual dispatch. Go checks do not gate either publisher.
The shared actions under `.ci/actions/` publish to the workflow's registry.

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
