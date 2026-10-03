#!/usr/bin/env bash
set -euo pipefail

paths=(
  ':(glob)infrastructure/backup/image/*.go'
  ':(exclude,glob)infrastructure/backup/image/*_test.go'
  infrastructure/backup/image/go.mod
  infrastructure/backup/image/go.sum
  infrastructure/backup/image/Dockerfile
  infrastructure/backup/image/Dockerfile.dockerignore
)
revision=$(git log -1 --format=%H -- "${paths[@]}")
release_tag() {
  git tag --points-at "$revision" --list 'backup-helper/v*' | sort -V | tail -1
}

if [ "${RELEASE_AUTHORITY:?}" = forgejo ]; then
  tag=$(release_tag)
  if [ -z "$tag" ]; then
    tag=$(git-cliff --config .ci/backup-helper-cliff.toml --bumped-version --use-branch-tags \
      --include-path 'infrastructure/backup/image/*.go' \
      --exclude-path 'infrastructure/backup/image/*_test.go' \
      --include-path 'infrastructure/backup/image/go.*' \
      --include-path 'infrastructure/backup/image/Dockerfile*')
    [[ "$tag" =~ ^backup-helper/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
    git tag --no-sign "$tag" "$revision"
  fi
else
  # Forgejo allocates versions and pushes its tags to GitHub. Hosted runners
  # consume those local tags without needing access to the homelab network.
  tag=''
  for attempt in {1..30}; do
    git fetch --no-tags origin \
      'refs/tags/backup-helper/*:refs/tags/backup-helper/*'
    tag=$(release_tag)
    [ -n "$tag" ] && break
    sleep 5
  done
  if [ -z "$tag" ]; then
    echo "No Forgejo backup-helper release exists for $revision" >&2
    exit 1
  fi
fi

[[ "$tag" =~ ^backup-helper/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
test "$(git rev-parse "$tag^{commit}")" = "$revision"
if [ "$RELEASE_AUTHORITY" = forgejo ]; then
  git push origin "refs/tags/$tag"
fi
{
  echo "BACKUP_HELPER_VERSION=${tag#backup-helper/v}"
  echo "BACKUP_HELPER_REVISION=$revision"
  echo "BACKUP_HELPER_EPOCH=$(git show -s --format=%ct "$revision")"
  echo "BACKUP_HELPER_TAG=$tag"
} >> "$GITHUB_ENV"
echo "Backup helper release: ${tag#backup-helper/v} ($revision)"
