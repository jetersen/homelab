#!/usr/bin/env bash
set -euo pipefail

component=${1:?Expected image component}
source "$(dirname "${BASH_SOURCE[0]}")/image-inputs.sh" "$component"
revision=$(git log -1 --format=%H -- "${paths[@]}")
test -n "$revision"
release_tag() {
  git tag --points-at "$revision" --list "$component/v*" | sort -V | tail -1
}

# A rewritten commit can reuse an immutable release only when its identity and
# every selected build input still match the original release commit.
rewritten_release_base() {
  local original metadata candidate
  original=$(git rev-parse "$1^{commit}")
  git merge-base "$original" HEAD > /dev/null || return 1
  metadata=$(git show -s --format='%an%n%ae%n%aI%n%cn%n%ce%n%cI%n%B' "$original")
  while read -r candidate; do
    if [ "$(git show -s --format='%an%n%ae%n%aI%n%cn%n%ce%n%cI%n%B' "$candidate")" = "$metadata" ] \
      && git diff --quiet "$original" "$candidate" -- "${paths[@]}"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(git log --format=%H "$revision" -- "${paths[@]}")
  return 1
}

tag=$(release_tag)
if [ -z "$tag" ]; then
  latest=$(git tag --list "$component/v*" | sort -V | tail -1)
  rewritten_base=''
  if [ -n "$latest" ] && ! git merge-base --is-ancestor "$latest" HEAD; then
    if ! rewritten_base=$(rewritten_release_base "$latest"); then
      echo "Latest $component release $latest is outside this history without an identical rewritten build; reconcile release history before allocating another version." >&2
      exit 1
    fi
  fi
  if [ -n "$rewritten_base" ] && [ "$revision" = "$rewritten_base" ]; then
    tag=$latest
    revision=$(git rev-parse "$tag^{commit}")
  else
    if [ -n "$rewritten_base" ]; then
      tag=$(git-cliff --config ".ci/$component-cliff.toml" --context --unreleased \
        --use-branch-tags "${cliff_paths[@]}" "$rewritten_base..HEAD" \
        | jq --arg previous "$latest" '
          if length == 1 and .[0].version == null then
            .[0].previous = (.[0] | .version = $previous | .commits = [] | .previous = null)
          else error("Expected one unreleased version") end' \
        | git-cliff --config ".ci/$component-cliff.toml" --from-context - --bumped-version)
    else
      tag=$(git-cliff --config ".ci/$component-cliff.toml" --bumped-version \
        --use-branch-tags "${cliff_paths[@]}")
    fi
    [[ "$tag" =~ ^$component/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
    git tag --no-sign "$tag" "$revision"
  fi
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
