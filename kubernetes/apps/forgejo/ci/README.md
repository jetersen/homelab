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

Network policy denies inbound connections and permits outbound DNS through
CoreDNS, public HTTP/HTTPS for source and dependencies, and Envoy HTTPS for
Forgejo and its registry. It excludes private networks and the homelab's public
IPv6 allocation. The shared Envoy listener serves other applications too;
this is not a Forgejo-only hostname restriction. Internal deployment API
exceptions belong only to the separate deployment/build runner.

Workspaces and temporary files use per-job `emptyDir` volumes. Go build/module
and NuGet caches share an OpenEBS LocalPV LVM thin PVC, including NuGet's scratch
directory for cross-process locking. This pins workers to the cache's node.
PVC capacity is enforced and supports expansion; monitor the thin pool's data
and metadata capacity too. Use a network cache service
before distributing this pool across nodes.

A cleanup CronJob checks at 03:30 Europe/Copenhagen each day. It clears Go and
NuGet caches after 90 days, keeping the PVC. The first check initializes the
interval without deleting existing caches. Workers hold a shared filesystem lock;
cleanup takes an exclusive lock and skips busy periods until the next daily check.
Only successful cleanup resets the interval. Builds refill the caches afterward.

The KEDA release is reconciled before this pool. To stop new workers while
allowing active jobs to finish, set `autoscaling.keda.sh/paused: "true"` on the
ScaledJob through GitOps. To move checks back, change their `runs-on` label to
`runner-kubernetes`; keep the cache PVC for reuse.
