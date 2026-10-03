# Forgejo staging image

The dedicated image packages the backup staging helper on distroless Python.
It runs as UID/GID 1000, needs no shell or installed Python packages, and runs
the staging and recovery tests during the build. The Dockerfile-specific ignore
file permits only the helper, tests, and build definition into the build context.

Build from the repository root:

```bash
docker build -f infrastructure/forgejo/Dockerfile \
  --build-arg REVISION="$(git rev-parse HEAD)" \
  -t forgejo-staging:local .
docker run --rm --network none --read-only --user 1000:1000 \
  --cap-drop ALL --security-opt no-new-privileges \
  forgejo-staging:local --help
```

The entrypoint runs the staging helper. Pass `--recover` for the pause watchdog.
Staging still needs the source and destination volumes, writable `/cache` and
`/tmp`, and the scoped Kubernetes service account used by the backup Job.

See [Forgejo v16 container registry documentation](https://forgejo.org/docs/v16.0/user/packages/container/)
and [application backup procedures](/kubernetes/apps/forgejo/README.md#backup-and-recovery).
