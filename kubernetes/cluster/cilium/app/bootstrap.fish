#!/usr/bin/env fish

set DIR (dirname (status --current-filename))
set HELMRELEASE $DIR/helmrelease.yaml
set SOURCE $DIR/source.yaml

# Select kubernetes context
kubectx

# Extract version from OCIRepository
set VERSION (yq '.spec.ref.tag' $SOURCE)

# Extract values from HelmRelease and install
yq -o yaml '.spec.values' $HELMRELEASE | helm install cilium cilium/cilium \
    --namespace kube-system \
    --version $VERSION \
    -f -
