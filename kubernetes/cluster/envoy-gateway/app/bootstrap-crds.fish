#!/usr/bin/env fish

set DIR (dirname (status --current-filename))
set SOURCE $DIR/source.yaml
set VERSION (yq -e '.spec.ref.tag' $SOURCE); or exit 1
set CHART (yq -e '.spec.url' $SOURCE); or exit 1

set CRDS (mktemp); or exit 1
function cleanup --on-event fish_exit
    rm -f -- $CRDS
end

# Finish the OCI download before applying anything to the cluster.
helm show crds $CHART --version $VERSION >$CRDS
or exit 1
test -s $CRDS
or exit 1

kubectl --context homelab apply --server-side --force-conflicts -f $CRDS
or exit 1
kubectl --context homelab wait --for=condition=Established --timeout=60s -f $CRDS
or exit 1
