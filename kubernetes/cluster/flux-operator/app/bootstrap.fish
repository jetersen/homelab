#!/usr/bin/env fish

set DIR (dirname (status --current-filename))
set HELMRELEASE $DIR/helmrelease.yaml
set SOURCE $DIR/source.yaml

# Extract version from OCIRepository
set VERSION (yq '.spec.ref.tag' $SOURCE)
set CHART (yq '.spec.url' $SOURCE)

# Create namespace if it doesn't exist
kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -

# Prompt for SOPS age key path
read -P "Enter path to SOPS age key: " SOPS_KEY_PATH

# Expand tilde if present
set SOPS_KEY_PATH (eval echo $SOPS_KEY_PATH)

if not test -f "$SOPS_KEY_PATH"
    echo "Error: SOPS key file not found at $SOPS_KEY_PATH"
    exit 1
end

# Create SOPS age secret for Flux
kubectl create secret generic sops-age \
    --namespace flux-system \
    --from-file=age.agekey="$SOPS_KEY_PATH" \
    --dry-run=client -o yaml | kubectl apply -f -

# Extract values from HelmRelease and install
yq -o yaml '.spec.values' $HELMRELEASE | helm install flux-operator $CHART \
    --namespace flux-system \
    --version $VERSION \
    -f -
