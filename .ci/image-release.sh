#!/usr/bin/env bash
set -euo pipefail

component=${1:?Expected image component}
source "$(dirname "${BASH_SOURCE[0]}")/image-inputs.sh" "$component"
revision=$(git log -1 --format=%H -- "${paths[@]}")
test -n "$revision"
release_tag() {
  git tag --points-at "$revision" --list "$component/v*" | sort -V | tail -1
}

tag=$(release_tag)
if [ -z "$tag" ]; then
  latest=$(git tag --list "$component/v*" | sort -V | tail -1)
  if [ -n "$latest" ] && ! git merge-base --is-ancestor "$latest" HEAD; then
    echo "Latest $component release $latest is outside this history; reconcile release history before allocating another version." >&2
    exit 1
  fi
  tag=$(git-cliff --config ".ci/$component-cliff.toml" --bumped-version \
    --use-branch-tags "${cliff_paths[@]}")
  [[ "$tag" =~ ^$component/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
  git tag --no-sign "$tag" "$revision"
fi

[[ "$tag" =~ ^$component/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
test "$(git rev-parse "$tag^{commit}")" = "$revision"
git push origin "refs/tags/$tag"
prefix=${component^^}
prefix=${prefix//-/_}
{
  echo "${prefix}_VERSION=${tag#"$component/v"}"
  echo "${prefix}_REVISION=$revision"
  echo "${prefix}_EPOCH=$(git show -s --format=%ct "$revision")"
  echo "${prefix}_TAG=$tag"
} >> "${GITHUB_ENV:?}"
echo "$component release: ${tag#"$component/v"} ($revision)"
