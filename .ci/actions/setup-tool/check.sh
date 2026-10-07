#!/usr/bin/env bash
set -euo pipefail
case "${TOOL:?}" in
  pulumi) args=(version) ;;
  flux|git-cliff) args=(--version) ;;
  *) echo "Unsupported runner tool: $TOOL" >&2; exit 1 ;;
esac

# Image stages are also the version source for runners awaiting an image update.
version=$(awk -v tool="$TOOL" '$1 == "FROM" && $3 == "AS" && $4 == tool {
  split($2, image, "@"); sub(/^.*:/, "", image[1]); sub(/^v/, "", image[1]); print image[1]
}' infrastructure/forgejo/runner/Dockerfile)
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
installed=false
if command -v "$TOOL" > /dev/null; then
  current=$("$TOOL" "${args[@]}")
  current=${current##* }
  [[ ${current#v} != "$version" ]] || installed=true
fi
printf 'version=%s\ninstalled=%s\n' "$version" "$installed" >> "$GITHUB_OUTPUT"
