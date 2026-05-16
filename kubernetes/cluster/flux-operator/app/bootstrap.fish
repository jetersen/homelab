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
set DEFAULT_SOPS_KEY_PATH ~/.config/sops/age/keys.txt
set SOPS_KEY_PATH ""

if test -f $DEFAULT_SOPS_KEY_PATH
    read -P "Use default SOPS age key at $DEFAULT_SOPS_KEY_PATH? [Y/n]: " USE_DEFAULT_SOPS_KEY
    if test -z "$USE_DEFAULT_SOPS_KEY"; or string match -qr '^[Yy]' -- "$USE_DEFAULT_SOPS_KEY"
        set SOPS_KEY_PATH $DEFAULT_SOPS_KEY_PATH
    end
end

if test -z "$SOPS_KEY_PATH"
    set SOPS_KEY_CANDIDATES ~/.config/sops/age/keys.txt ~/.config/age/keys.txt ~/.config/sops/age/*.txt ~/.config/sops/age/*key* ~/.config/age/*.txt ~/.config/age/*key*
    set SOPS_KEY_CANDIDATES (for key_path in $SOPS_KEY_CANDIDATES; test -f $key_path; and realpath $key_path; end | sort -u)

    if test (count $SOPS_KEY_CANDIDATES) -gt 0
        echo "Available SOPS age key files:"
        for index in (seq (count $SOPS_KEY_CANDIDATES))
            echo "  [$index] $SOPS_KEY_CANDIDATES[$index]"
        end
        read -P "Pick key number or enter custom path: " SOPS_KEY_CHOICE

        if string match -qr '^[0-9]+$' -- "$SOPS_KEY_CHOICE"; and test $SOPS_KEY_CHOICE -ge 1; and test $SOPS_KEY_CHOICE -le (count $SOPS_KEY_CANDIDATES)
            set SOPS_KEY_PATH $SOPS_KEY_CANDIDATES[$SOPS_KEY_CHOICE]
        else
            set SOPS_KEY_PATH $SOPS_KEY_CHOICE
        end
    else
        read -P "Enter path to SOPS age key: " SOPS_KEY_PATH
    end
end

# Expand tilde if present
set SOPS_KEY_PATH (eval echo $SOPS_KEY_PATH)

if test -f "$SOPS_KEY_PATH"
    # Create SOPS age secret for Flux
    kubectl create secret generic sops-age \
        --namespace flux-system \
        --from-file=age.agekey="$SOPS_KEY_PATH" \
        --dry-run=client -o yaml | kubectl apply -f -
else
    echo "Skipping SOPS age secret; no valid key selected."
end

# Extract values from HelmRelease and install/upgrade
yq -o yaml '.spec.values' $HELMRELEASE | helm upgrade --install flux-operator $CHART \
    --namespace flux-system \
    --version $VERSION \
    -f -
