#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/compat" && pwd)
# Include the source and locked dependencies so stale bundled binaries are rebuilt.
fingerprint=$(cat "$source_dir/main.go" "$source_dir/go.mod" "$source_dir/go.sum" | sha256sum | cut -c1-16)
upstream_version=$(awk '$1 == "github.com/DNSControl/dnscontrol/v5" { print $2 }' "$source_dir/go.mod")
version="$upstream_version+technitium.$fingerprint"
bundled=/usr/local/bin/dnscontrol
needs_build=true
if [[ -x $bundled ]] && [[ $("$bundled" version) == "$version" ]]; then
  needs_build=false
fi
if [[ ${1:-} == --needs-build ]]; then
  printf '%s\n' "$needs_build"
  exit 0
fi
directory=${1:?Specify the tool installation directory}
mkdir -p "$directory"
directory=$(cd "$directory" && pwd)
if [[ $needs_build == false ]]; then
  if [[ $bundled != "$directory/dnscontrol" ]]; then
    cp "$bundled" "$directory/dnscontrol"
  fi
else
  CGO_ENABLED=0 go -C "$source_dir" build -mod=readonly -trimpath \
    -ldflags "-s -w -X github.com/DNSControl/dnscontrol/v5/pkg/version.version=$version" \
    -o "$directory/dnscontrol" .
fi
[[ $("$directory/dnscontrol" version) == "$version" ]]
"$directory/dnscontrol" version
