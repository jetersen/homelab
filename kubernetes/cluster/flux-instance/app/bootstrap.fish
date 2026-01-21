#!/usr/bin/env fish

set DIR (dirname (status --current-filename))
set HELMRELEASE $DIR/helmrelease.yaml
set SOURCE $DIR/source.yaml

# Extract version from OCIRepository
set VERSION (yq '.spec.ref.tag' $SOURCE)
set CHART (yq '.spec.url' $SOURCE)

# Wait for flux-operator to be ready
echo "Waiting for flux-operator to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=flux-operator -n flux-system --timeout=300s

# Extract values from HelmRelease and install
yq -o yaml '.spec.values' $HELMRELEASE | helm install flux-instance $CHART \
    --namespace flux-system \
    --version $VERSION \
    -f -
