#!/usr/bin/env fish

set DIR (dirname (status --current-filename))

echo "=== Cluster Bootstrap ==="

# Select kubernetes context
kubectx

echo ""
echo "=== Installing Cilium CNI ==="
fish $DIR/cilium/app/bootstrap.fish

echo ""
echo "=== Installing Flux Operator ==="
fish $DIR/flux-operator/app/bootstrap.fish

echo ""
echo "=== Installing Flux Instance ==="
fish $DIR/flux-instance/app/bootstrap.fish

echo ""
echo "=== Cluster Bootstrap Complete ==="
