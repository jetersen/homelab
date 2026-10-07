# Kubernetes

Bootstrap the `homelab` Kubernetes context with Cilium CNI, Flux Operator, and Flux Instance:

```bash
fish kubernetes/cluster/bootstrap.fish
```

Bootstrap installs Gateway API and Envoy Gateway CRDs before Cilium. See
[Talos setup](talos/README.md) for networking and access requirements.

See the [networking overview](../NETWORKING.md) for network boundaries, DNS,
remote access, and discovery constraints.
