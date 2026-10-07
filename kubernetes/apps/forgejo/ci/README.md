# Forgejo CI workers

KEDA polls the `homelab` repository's job queue every ten seconds for
`ci-kubernetes` and starts at most two Kubernetes Jobs. Each worker runs
`forgejo-runner one-job` in the bundled tool image and exits after one job, or
immediately if another worker already claimed the queued work. Completed Jobs
expire after five minutes. Gradual rollouts let active jobs finish.

The pool uses a persistent repository-scoped runner registration shared by the
one-job processes. The worker pods are disposable; the registration is not an
ephemeral Forgejo registration. Keep registration and the scaler's read-only
repository API token in the SOPS-encrypted Secret. Only the runner credentials
are mounted in workers. The scaler credential stays with KEDA.

Workflows run directly inside the worker container using the `host` executor.
They have no Docker socket, privileged mode, or Kubernetes service-account token.
This pool is for trusted repository checks; its processes can read the shared
runner credential and dependency caches. Keep deployment and image-build jobs
on their existing runner labels.

Workspaces and temporary files use per-job `emptyDir` volumes. Go build/module
and NuGet caches share a local-path PVC, including NuGet's scratch directory for
cross-process locking. This pins workers to the cache's node. Local-path storage
does not enforce the PVC capacity; monitor disk use. Use a network cache service
before distributing this pool across nodes.

The KEDA release is reconciled before this pool. To stop new workers while
allowing active jobs to finish, set `autoscaling.keda.sh/paused: "true"` on the
ScaledJob through GitOps. To move checks back, change their `runs-on` label to
`runner-kubernetes`; keep the cache PVC for reuse.
