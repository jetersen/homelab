# Forgejo CI workers

KEDA starts disposable workers for repository checks using `ci-kubernetes`.
Each worker runs `forgejo-runner one-job` in the bundled tool image. The
[ScaledJob](scaledjob.yaml) defines polling, concurrency, job lifetime, and rollout
behavior; [runner.yaml](runner.yaml) defines the executor and cache paths.

The pool uses a persistent repository-scoped runner registration shared by the
one-job processes. The worker pods are disposable; the registration is not an
ephemeral Forgejo registration. Keep registration and the scaler's read-only
repository API token in the SOPS-encrypted Secret. Only the runner credentials
are mounted in workers. The scaler credential stays with KEDA.

Workflows run directly inside the worker container using the `host` executor.
They have no Docker socket, privileged mode, or Kubernetes service-account token.
This pool is for trusted repository checks; its processes can read the shared
runner credential and dependency caches. Keep deployment and image-build jobs
on `oci-build`, provided by the Rocket Docker runner.

The [network policy](networkpolicy.yaml) restricts worker traffic. Its shared
Envoy exception also allows access to other applications on that listener;
it cannot distinguish HTTPS hostnames. Internal deployment API exceptions belong
only to the separate deployment/build runner.

Workspaces and temporary files use per-job `emptyDir` volumes. Go build/module
and NuGet caches share an OpenEBS LocalPV LVM thin PVC, including NuGet's scratch
directory for cross-process locking. This pins workers to the cache's node.
PVC capacity is enforced and supports expansion; monitor the thin pool's data
and metadata capacity too. Use a network cache service
before distributing this pool across nodes.

The [cleanup CronJob](cache-cleanup.yaml) runs the
[cache cleanup script](cache-cleanup.sh), which defines the retention interval.
Cleanup preserves the PVC and uses an exclusive filesystem lock so active
workers can finish. Builds refill the caches afterward.

The KEDA release is reconciled before this pool. To stop new workers while
allowing active jobs to finish, set `autoscaling.keda.sh/paused: "true"` on the
ScaledJob through GitOps. Go checks and style checks use `ci-kubernetes`. Deployment and image-build
workflows use `oci-build`; `runner-rocket` remains available for explicit Docker
runner selection. Preserve cache PVCs when removing worker workloads until
data disposal is separately authorized.
