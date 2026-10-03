# Forgejo runners

The Kubernetes runner is always available. Rocket runs the same OCI jobs through
Docker Compose while the computer is online. Both advertise `oci-build`, have
capacity one, and use separate repository-scoped registrations. Manual OCI
publication can select `runner-kubernetes` or `runner-rocket` to check each host.

Each runner launches jobs through its own privileged Docker-in-Docker daemon.
Jobs have Docker access to that daemon. The host Docker socket, host directories,
and Kubernetes service-account credentials are not available to jobs. Only
trusted workflows from this repository should use these runners.

The dedicated `runner-job` image includes Node.js 24, Bash, Git, curl, jq,
kubectl, Docker CLI, and Buildx. Both registries publish it with the Flux artifact
and staging image. Runner labels pin the verified GHCR digest so jobs can start
when Forgejo Packages is unavailable. Update both runner profiles after verifying
a replacement digest.

For Rocket, create a mode-0700 registration directory outside the checkout with
mode-0600 `uuid` and `token` files from Forgejo v16's repository runner API. Keep
the files readable by UID 1000. Set `RUNNER_REGISTRATION_DIR` to that directory
and run `docker compose -f infrastructure/forgejo/runner/compose.yaml up -d`.
Docker's restart policy starts the containers after the Docker daemon returns.
Use the same file and registration directory for subsequent Compose commands.
The nested daemon uses the homelab's LAN DNS servers explicitly; Docker's outer
loopback resolver is not reachable from its build containers.

Kubernetes stores its registration in a SOPS-encrypted Secret. The privileged
namespace is dedicated to runners and denies incoming pod traffic. The runner
and its daemon share a pod; Docker's TCP port has no Service or host port.

See [Forgejo v16 runner registration](https://forgejo.org/docs/v16.0/admin/actions/registration/)
and [Docker access](https://forgejo.org/docs/v16.0/admin/actions/docker-access/).
