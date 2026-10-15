# Forgejo CI workers

KEDA starts disposable Docker workers for `linux-docker` jobs. Rocket accepts the
same label, so workflows can run on either pool; `runner-rocket` selects Rocket
explicitly. `runner-kubernetes` selects only the Kubernetes pool and is reserved
for jobs that need Kubernetes source addresses. Combine it after `linux-docker`
in `runs-on` so Docker remains the selected executor. A worker that finds its
task already claimed by Rocket exits successfully. The [ScaledJob](scaledjob.yaml)
defines polling, concurrency, job lifetime, and rollout behavior;
[runner.yaml](runner.yaml) defines the executor.

The KEDA Forgejo query lists `linux-docker,runner-kubernetes`. Forgejo returns a
waiting job when every label requested by the job is present in the query, so this
matches both ordinary `linux-docker` jobs and jobs requiring the Kubernetes label.

The pool uses a persistent repository-scoped runner registration shared by the
one-job processes. Keep registration and the scaler's read-only repository API
token in the SOPS-encrypted Secret. Only runner credentials are mounted in
workers. The scaler credential stays with KEDA.

Each worker has a privileged Docker-in-Docker restartable init sidecar. Workflow
containers run without privileged mode, host sockets, or Kubernetes
service-account tokens. Docker actions, services, image builds, and job container
overrides use the worker's isolated daemon. This pool is for trusted repository
workflows: Docker access can control that daemon and its containers.

The [network policy](networkpolicy.yaml) allows DNS, public package and image
registries, the shared Envoy listener, and the internal deployment endpoints.
The Envoy exception cannot distinguish HTTPS hostnames. Nested containers use
cluster DNS; `docker` resolves to their daemon gateway for Docker CLI access.

Docker workspaces and image layers use a per-worker generic ephemeral PVC from
`openebs-lvm-ephemeral`. Kubernetes deletes its PVC with the worker Pod, and the
storage class deletes its volume. Workers bind to a node with that local thin
pool. Monitor thin-pool data and metadata capacity as well as each PVC's capacity.
The daemon puts nested containers under its own cgroup so its memory limit covers
the entire job. The Docker sidecar stops automatically after the one-job runner
exits.

New Kubernetes workers download dependencies and images into their isolated
store. Rocket retains Docker image layers and permits the `dotfiles-nix-cache`
named volume for serialized Nix jobs. That volume holds the Nix store, its
database, and fetched inputs. The shared Debian job image includes Nix outside
the store, so it can mount either a fresh or retained store directly. Job
credentials must stay outside this shared volume. The volume belongs to Rocket's nested Docker daemon
and survives runner and daemon restarts through its persistent Docker data.
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
