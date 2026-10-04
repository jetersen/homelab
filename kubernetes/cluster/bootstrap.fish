#!/usr/bin/env fish

set DIR (dirname (status --current-filename))

function _abort --on-signal INT --on-signal TERM
    echo ""
    echo "Aborted."
    exit 130
end

function run
    $argv
    or begin
        echo "Step failed: $argv" >&2
        exit 1
    end
end

echo "=== Cluster Bootstrap ==="

# Select kubernetes context
run kubectx homelab

echo ""
echo "=== Installing Gateway API and Envoy Gateway CRDs ==="
run fish $DIR/envoy-gateway/app/bootstrap-crds.fish

echo ""
echo "=== Installing Cilium CNI ==="
run fish $DIR/cilium/app/bootstrap.fish

echo ""
echo "=== Installing Flux Operator ==="
run fish $DIR/flux-operator/app/bootstrap.fish

echo ""
echo "=== Installing Flux Instance ==="
run fish $DIR/flux-instance/app/bootstrap.fish

echo ""
echo "=== Cluster Bootstrap Complete ==="
