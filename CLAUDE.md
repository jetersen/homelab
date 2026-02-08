# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kubernetes homelab infrastructure managed via GitOps with Flux CD. Runs on Talos Linux (v1.11.5) with Kubernetes v1.34.1.

## Commands

### Bootstrap Cluster
```bash
fish kubernetes/cluster/bootstrap.fish
```
This installs Cilium CNI, Flux Operator, and Flux Instance in sequence.

### Talos Management
```bash
# Generate configs from talconfig.yaml
talosctl gen config <cluster> <endpoint> --config-patch @kubernetes/talos/talconfig.yaml

# Apply to nodes
talosctl apply-config -n <node-ip> -f kubernetes/talos/clusterconfig/<node>.yaml
```

## Architecture

### Directory Structure
- `kubernetes/talos/` - Talos Linux cluster definition and encrypted secrets
- `kubernetes/flux/` - Flux CD entry point (cluster.yaml defines what gets reconciled)
- `kubernetes/cluster/` - Core infrastructure (CNI, gateways, cert-manager, DNS)
- `kubernetes/apps/` - Application deployments

### GitOps Flow
1. Flux watches `kubernetes/flux/` on `main` branch
2. `cluster.yaml` defines Kustomizations pointing to `kubernetes/cluster/` and `kubernetes/apps/`
3. HelmReleases deploy workloads; Flux reconciles every 24h

### HelmRelease Pattern
Each component follows this structure:
```
component/
├── app/
│   ├── helmrelease.yaml    # HelmRelease CR with inline values
│   ├── source.yaml         # OCIRepository pointing to chart
│   ├── kustomization.yaml  # Lists the above files
│   └── bootstrap.fish      # Optional manual install script
└── flux-ks.yaml            # Flux Kustomization CR
```

### Adding a New Application
1. Create `kubernetes/cluster/<app>/app/` with helmrelease.yaml, source.yaml, kustomization.yaml
2. Create `kubernetes/cluster/<app>/flux-ks.yaml` with Kustomization CR
3. Add to `kubernetes/cluster/kustomization.yaml` resources list
4. For namespaced apps, add namespace to `kubernetes/flux/namespaces/`

### Kustomize Patch Convention
When patching resources from remote bases (e.g., GitHub URLs), strategic merge patches must reference the resource's **upstream namespace**, not the target namespace. The top-level `namespace` field in the kustomization handles namespace transformation after patches are matched.

### Secrets Management
- SOPS encryption with age keys (config in `.sops.yaml`)
- Encrypted files use `*.sops.yaml` naming
- Flux decrypts automatically via `sops-age` secret in flux-system

### Networking Stack
- **Cilium**: eBPF CNI replacing kube-proxy, L2 announcements for LoadBalancer
- **Envoy Gateway**: Kubernetes Gateway API v1 for ingress
- **External DNS**: Syncs HTTPRoutes to Cloudflare
- **Cert-manager**: Let's Encrypt certificates for jetersen.dev and lan.jetersen.dev

### Cluster Components
- **Metrics Server**: Cluster resource metrics for kubectl top and HPA (deployed to kube-system)
- **Local Path Provisioner**: Dynamic PV provisioner using local node storage (deployed to kube-system)
  - Default StorageClass for the cluster
  - Storage path: `/var/mnt/local-path-provisioner`

### Monitoring Stack
All monitoring components deploy to the `monitoring` namespace.

- **VictoriaMetrics**: Time-series metrics database (Prometheus-compatible)
  - 30-day retention, 20Gi storage
  - Built-in scraping via Prometheus annotations (`prometheus.io/scrape: "true"`)
  - Query endpoint: `http://victoria-metrics-server:8428`

- **VictoriaLogs**: Log storage backend
  - 7-day retention, 20Gi storage
  - Insert endpoint: `http://victoria-logs-server:9428`

- **VictoriaLogs Collector**: DaemonSet collecting container logs
  - Depends on: victoria-logs
  - Tolerates all nodes for full cluster coverage

- **Grafana**: Visualization and dashboards
  - Depends on: victoria-metrics, victoria-logs, victoria-logs-collector
  - Pre-configured datasources for VictoriaMetrics and VictoriaLogs
  - Dashboard sidecar enabled (label: `grafana_dashboard: "1"`)
  - Access: `kubectl port-forward svc/grafana 3000:80 -n monitoring`

## Maintenance

When adding new components to `kubernetes/cluster/` or `kubernetes/apps/`:
- Update this file to document what the component does and any non-obvious configuration or dependencies
- Update relevant README.md files (e.g., `kubernetes/README.md`) if the change affects setup or usage
