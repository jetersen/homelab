# Pod DNS defaults

This component sets `ndots:1` for resources with a supported DNS profile.
Dotted hostnames resolve before Kubernetes and LAN search suffixes; short service
names still use the search domains. Existing nameservers and searches are retained.
The component supplies the DNS options list.

`helmrelease-defaults` includes this component, so HelmReleases only need a profile
label. For native workloads, include it directly in their `kustomization.yaml`:

```yaml
components:
  - ../../../components/dns-defaults
```

Select a supported profile with a label on the workload or HelmRelease:

```yaml
metadata:
  labels:
    homelab.jetersen.dev/dns-profile: app-template
```

| Profile | Chart settings |
| --- | --- |
| `app-template` | `values.defaultPodOptions.dnsConfig` |
| `pod` | Native Deployment, StatefulSet, or DaemonSet PodSpec; `values.dnsConfig` for Forgejo and Grafana |
| `victoria-metrics` | VMSingle, VMAgent, and VMAlert operator pod settings |
| `flux-instance` | Inserts a Deployment patch into the existing Flux operator patches |

Unlabelled resources are unaffected. The Flux instance profile requires
`values.instance.kustomize.patches` to exist.
For another chart or operator, verify its pod DNS settings before adding a profile.
Include the component in the Kustomization that builds the workload or HelmRelease;
including it beside Flux Kustomization resources does not affect their child builds.
