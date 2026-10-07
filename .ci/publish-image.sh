#!/usr/bin/env bash
set -euo pipefail

component=${1:?Expected image component}
source "$(dirname "${BASH_SOURCE[0]}")/image-inputs.sh" "$component"
prefix=${component^^}
prefix=${prefix//-/_}
version_var=${prefix}_VERSION
revision_var=${prefix}_REVISION
epoch_var=${prefix}_EPOCH
version=${!version_var:?}
revision=${!revision_var:?}
epoch=${!epoch_var:?}
image="${REGISTRY:?}/${REPOSITORY,,}/$component"
release="$image:$version"
directory=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/image-publish.XXXXXX")
trap 'rm -rf -- "$directory"' EXIT

# Do this before building: a published release is immutable, including on reruns
# and on a different runner with a different build cache.
if docker buildx imagetools inspect "$release" --format '{{json .Image}}' \
    > "$directory/config" 2> "$directory/error"; then
  if ! jq -e --arg revision "$revision" --arg version "$version" \
    '.config.Labels["org.opencontainers.image.revision"] == $revision and
     .config.Labels["org.opencontainers.image.version"] == $version' "$directory/config" > /dev/null; then
    echo "Refusing to replace $release: its revision or version label does not match this release." >&2
    exit 1
  fi
  echo "Reusing $release; skipping build and release push."
elif grep -Eqi 'manifest unknown|MANIFEST_UNKNOWN|: not found|no such manifest' "$directory/error"; then
  docker build -f "$dockerfile" --build-arg REVISION="$revision" \
    --build-arg VERSION="$version" --build-arg SOURCE_DATE_EPOCH="$epoch" \
    -t "$release" .
  if [ "$component" = backup-helper ]; then
    docker run --rm --network none --read-only --user 1000:1000 \
      --cap-drop ALL --security-opt no-new-privileges "$release" --help
  else
    docker run --rm -i --network none --read-only --cap-drop ALL \
      --security-opt no-new-privileges "$release" \
      bash -s < .ci/check-runner.sh
  fi
  docker push "$release"
else
  cat "$directory/error" >&2
  exit 1
fi

git fetch --no-tags origin refs/heads/main
if [ -n "$(git diff --name-only HEAD FETCH_HEAD -- "${paths[@]}")" ]; then
  echo "Newer $component inputs exist; leaving main unchanged."
  exit 0
fi
digest=$(docker buildx imagetools inspect "$release" --format '{{.Manifest.Digest}}')
if docker buildx imagetools inspect "$image:main" --format '{{.Manifest.Digest}}' \
    > "$directory/main-digest" 2> "$directory/error"; then
  if [ "$(cat "$directory/main-digest")" = "$digest" ]; then
    echo "$image:main already points to $version."
    exit 0
  fi
elif ! grep -Eqi 'manifest unknown|MANIFEST_UNKNOWN|: not found|no such manifest' "$directory/error"; then
  cat "$directory/error" >&2
  exit 1
fi
docker buildx imagetools create --prefer-index=false --tag "$image:main" "$image@$digest"
test "$(docker buildx imagetools inspect "$image:main" --format '{{.Manifest.Digest}}')" = "$digest"
