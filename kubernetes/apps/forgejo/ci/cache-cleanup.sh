#!/usr/bin/env bash
set -euo pipefail

# Workers hold shared locks for their entire lifetime. Keep this file outside
# the cache directories so clearing them cannot replace the locked inode.
exec 9>/cache/.cleanup.lock
if ! flock --exclusive --nonblock 9; then
  echo 'CI workers are active; deferring cache cleanup.'
  exit 0
fi

now=$(date +%s)
stamp=/cache/.last-clean
if [[ ! -e $stamp ]]; then
  printf '%s\n' "$now" > "$stamp.tmp"
  mv "$stamp.tmp" "$stamp"
  echo 'Initialized the 90-day cache cleanup interval.'
  exit 0
fi
last_clean=$(cat "$stamp")
if [[ ! $last_clean =~ ^[0-9]+$ ]]; then
  echo 'Invalid cache cleanup timestamp; refusing to clear caches.' >&2
  exit 1
fi
if (( now - last_clean < 90 * 24 * 60 * 60 )); then
  echo 'Caches are less than 90 days old; keeping them.'
  exit 0
fi

export GOCACHE=/cache/go/build GOMODCACHE=/cache/go/mod
export NUGET_PACKAGES=/cache/nuget/packages
export NUGET_HTTP_CACHE_PATH=/cache/nuget/http NUGET_SCRATCH=/cache/nuget/scratch
export DOTNET_CLI_HOME=/tmp/dotnet GOTOOLCHAIN=local
# Use the tools' cleanup commands, including Go's read-only module directories.
go clean -cache -modcache
dotnet nuget locals all --clear --force-english-output
printf '%s\n' "$(date +%s)" > "$stamp.tmp"
mv "$stamp.tmp" "$stamp"
echo 'Cleared Go and NuGet caches; the next cleanup is due in 90 days.'
