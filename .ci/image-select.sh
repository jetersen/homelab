#!/usr/bin/env bash
set -euo pipefail
for component in backup-helper runner-job renovate-operator renovate-worker; do
  source "$(dirname "${BASH_SOURCE[0]}")/image-inputs.sh" "$component"
  if [ "${EVENT_NAME:-}" = workflow_dispatch ] || [ -z "${BEFORE:-}" ] || \
    [ -z "$(git tag --list "$component/v*")" ] || \
    ! git diff --quiet "$BEFORE" HEAD -- "${paths[@]}"; then
    echo "$component"
  fi
done
