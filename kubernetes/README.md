TODO

## Setup

```bash
kubectl create ns flux-system
kubectl -n flux-system create secret generic sops-age --from-file=age.agekey=$HOME/.config/sops/age/keys.txt

helm install flux-operator oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator --namespace flux-system
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=flux-operator -n flux-system --timeout=300s
kubectl apply -f kubernetes/flux/instance-setup.yaml
```
