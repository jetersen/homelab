# Forgejo CI workers

KEDA starts disposable Docker workers for `linux-docker` jobs. Rocket accepts the
same label, so workflows can run on either pool; `runner-rocket` selects Rocket
explicitly. `runner-kubernetes` selects only the Kubernetes pool. Combine it after
`linux-docker` in `runs-on` so Docker remains the selected executor. A worker that finds its
task already claimed by Rocket exits successfully. The [ScaledJob](scaledjob.yaml)
and [dotfiles ScaledJob](dotfiles-scaledjob.yaml) define polling, concurrency,
job lifetime, and rollout behavior;
[runner.yaml](runner.yaml) and [dotfiles-runner.yaml](dotfiles-runner.yaml) define
the executors.

Select `runner-rocket` for full Nix builds and `runner-kubernetes` for lightweight
checks. Nix workflows must request their sandbox namespace permissions in the
job's container options; lightweight workers do not grant those permissions.

The KEDA Forgejo query lists `linux-docker,runner-kubernetes`. Forgejo returns a
waiting job when every label requested by the job is present in the query, so this
matches both ordinary `linux-docker` jobs and jobs requiring the Kubernetes label.

Each repository uses its own persistent runner registration shared by its
one-job processes. Keep registration and the scaler's read-only repository API
token in the SOPS-encrypted Secret. Only runner credentials are mounted in
workers. The scaler credential stays with KEDA.

Workers connect to a shared [Docker backend](docker-backend.yaml), which retains
image layers on a persistent PVC. Only worker pods can reach its Docker API. The backend has no runner registration, Kubernetes token, host
socket, or node containerd socket mounted. Its privileged daemon has a configured
memory limit; CPU quotas remain omitted.

Size the backend's aggregate memory ceiling to leave headroom for cluster
services, including when both worker pools are busy. Nested builds count toward
that ceiling. Runner capacity is per worker; use each ScaledJob's replica limit
to control the number of simultaneous jobs.

This pool is for trusted repository workflows. Jobs share a Docker engine and can
inspect or control each other's CI containers. They retain separate job networks
and workspaces, but the shared engine is not an isolation boundary between jobs.
Nested containers use cluster DNS; `docker` resolves to their daemon gateway.
Docker allocates /24 networks inside 172.28.0.0/16 to avoid the Kubernetes pod
and service ranges.
The backend network policy preserves access to the same registries and deployment
endpoints used by the workers.

The PVC survives backend pod replacement. Never mount its Docker data directory
into multiple daemons. [Startup](docker-entrypoint.sh) removes stale stopped
containers, networks, and job volumes before becoming ready, while retaining image
layers and volumes labelled `ci.persistent=true`. Cache budgets are defined in the
backend configuration; startup and periodic cleanup are defined in the entrypoint. Monitor PVC and thin-pool capacity.

The backend uses `OnDelete` updates to avoid restarting the shared engine during
CI. For an engine or configuration update, pause KEDA, let active Kubernetes jobs
finish, then replace the backend pod and verify it is ready before unpausing KEDA.
The PVC and image cache remain. Never restart it while CI jobs are active. Ordinary
job-image updates need no backend restart; the daemon pulls the new pinned image
and retains reusable layers. Clearing Docker storage requires stopping the pool
and explicit approval. A cache miss or cleanup can still require a cold pull.

Both backends retain Docker image layers. Rocket permits the `dotfiles-nix-cache`
named volume for serialized Nix jobs. That volume holds the Nix store, its
database, and fetched inputs. The Debian job image includes Nix outside
the store, so it can mount either a fresh or retained store directly. Job
credentials must stay outside this shared volume. Serialize jobs that mount it.
The runner's [Compose configuration](../../../../infrastructure/forgejo/runner/compose.yaml)
also mounts the NAS Nix binary cache at `/var/cache/nix-nas` inside the nested
Docker daemon. Jobs may bind that path to refill their working store and retain
build inputs and outputs. Pulumi manages its quota-limited dataset and NFS export
in [Storage.cs](../../../../infrastructure/truenas/Storage.cs). The cache is
disposable; stop Nix jobs before clearing it. Attic independently retains signed
workstation closures for deployment.

Rocket's nested containers use Tailscale's DNS resolver for MagicDNS, with LAN
resolvers for other names. Use fully qualified Tailscale names in repository
variables because job DNS searches are disabled. The NFS cache uses LAN DNS
names to keep cache transfers on the local network.

The KEDA release is reconciled before this pool. To stop new workers while
allowing active jobs to finish, set `autoscaling.keda.sh/paused: "true"` on the
ScaledJob through GitOps.
