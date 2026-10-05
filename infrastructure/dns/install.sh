#!/usr/bin/env bash
set -euo pipefail
directory=${1:?Specify the tool installation directory}
mkdir -p "$directory"
archive=$(mktemp)
trap 'rm -f "$archive"' EXIT
curl --fail --silent --show-error --location \
  https://github.com/DNSControl/dnscontrol/releases/download/v4.46.0/dnscontrol_4.46.0_linux_amd64.tar.gz \
  --output "$archive"
printf '5dc969acec7ae5867ee8a6b6e08827c2144eef6767a219cff612f84416ca58c1  %s\n' "$archive" | sha256sum --check --status
tar -xzf "$archive" -C "$directory" dnscontrol
"$directory/dnscontrol" version
