# Homepage

Internal dashboard at https://home.jetersen.dev through Envoy Gateway. The route
opts out of public DNS publishing and uses the existing internal DNS providers.

Edit `app/config/services.yaml` for links and Kubernetes pod associations,
`settings.yaml` for layout, and `widgets.yaml` for the cluster summary.
Kustomize generates a content-hashed ConfigMap, so configuration changes roll
out a new pod. Runtime files use ephemeral storage; no PVC is needed.

The service account can only read nodes, namespaces, pods, and metrics. Service
links are explicit; ingress and Gateway discovery are disabled. Service API
widgets and authentication are not configured. Keep access internal.

Validate locally with:

```sh
kustomize build kubernetes/apps/homepage/app
kustomize build kubernetes/apps
kustomize build kubernetes/flux/namespaces
```

Deploy through the repository's normal Flux workflow after publishing the change.
