#!/bin/bash
set -euo pipefail
test ! -e /data/.kopiaignore
test ! -e /data/backups/.kopiaignore
file=/data/backups/sonarr.zip
test -f "$file" && test ! -L "$file" && test -s "$file"
age="$(( $(date +%s) - $(stat -c %Y "$file") ))"
test "$age" -ge 0 && test "$age" -le 3600
python3 -c 'import runpy; runpy.run_path("/kopia-config/export-sonarr.py")["validate_archive"]("/data/backups/sonarr.zip")' >/dev/null 2>&1
config="${KOPIA_CACHE_DIR}/kopia.config"
policy="${KOPIA_CONFIG_PATH}/policy.json"
kopia --config-file="$config" --disable-file-logging policy import --global --from-file="$policy" >/dev/null
kopia --config-file="$config" --disable-file-logging policy show /data --json |
  jq -e --slurpfile expected "$policy" '
    .files == $expected[0]["(global)"].files and
    .retention == $expected[0]["(global)"].retention and
    .errorHandling == $expected[0]["(global)"].errorHandling' >/dev/null
