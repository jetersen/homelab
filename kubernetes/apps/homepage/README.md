# Homepage

Internal dashboard at https://home.jetersen.dev through Envoy Gateway. The route
opts out of public DNS publishing and uses the existing internal DNS providers.

Edit `app/config/services.yaml` for links and Kubernetes pod associations,
`settings.yaml` for layout, and `widgets.yaml` for the cluster summary.
Kustomize generates a content-hashed ConfigMap, so configuration changes roll
out a new pod. Runtime files use ephemeral storage; no PVC is needed.

The service account can only read nodes, namespaces, pods, and metrics. Service
links are explicit; ingress and Gateway discovery are disabled. Keep access
internal; dashboard authentication is not configured.

The TrueNAS widget uses the WebSocket API (`version: 2`) and shows pool storage
used, total capacity, usage percentage, and health. Load, uptime, and alert blocks
are hidden. Its existing API key from Proton Pass is stored in the SOPS-encrypted
`app/secret.sops.yaml` Secret and injected as `HOMEPAGE_VAR_TRUENAS_KEY`; the
ConfigMap contains only a placeholder. Other service API widgets are not configured.

TrueNAS connects directly at `https://truenas.lan.jetersen.dev`, independent of
Envoy. Its certificate is issued and renewed by TrueNAS using Let's Encrypt and
Cloudflare DNS validation. The DNS token must allow the NAS's outbound IP addresses.

Validate locally with:

```sh
kustomize build kubernetes/apps/homepage/app
kustomize build kubernetes/apps
kustomize build kubernetes/flux/namespaces
```

Deploy through the repository's normal Flux workflow after publishing the change.
