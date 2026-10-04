## Setup

Bootstrap the `homelab` Kubernetes context with Cilium CNI, Flux Operator, and Flux Instance:

```bash
fish kubernetes/cluster/bootstrap.fish
```

Bootstrap installs Gateway API and Envoy Gateway CRDs from the OCI chart pinned
in `cluster/envoy-gateway/app/source.yaml` before installing Cilium. It waits for
the CRDs to be established. All bootstrap charts are pulled from OCI registries.
