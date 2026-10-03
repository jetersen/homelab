#!/bin/bash
set -euo pipefail

# Do not let local ignore files override the reviewed archive selection.
test ! -e /data/.kopiaignore
test ! -e /data/backups/.kopiaignore

config="${KOPIA_CACHE_DIR}/kopia.config"
policy="${KOPIA_CONFIG_PATH}/policy.json"

case "$1" in
  home-assistant)
    shopt -s nullglob
    files=(/data/backups/*.tar)
    ((${#files[@]} > 0))
    # Native retention must bound the input too. Never delete manual archives here.
    ((${#files[@]} <= 3))
    latest="${files[0]}"
    for file in "${files[@]}"; do
      test -f "$file" && test ! -L "$file" && test -s "$file"
      # Avoid archives still being produced. Never copy the live recorder database.
      test "$(( $(date +%s) - $(stat -c %Y "$file") ))" -ge 300
      tar -tf "$file" >/dev/null
      if [[ "$file" -nt "$latest" ]]; then latest="$file"; fi
    done
    test "$(( $(date +%s) - $(stat -c %Y "$latest") ))" -le 108000
    name="$(basename "$latest")"
    [[ "$name" =~ ^[a-zA-Z0-9_-]+\.tar$ ]]
    effective="${KOPIA_CACHE_DIR}/effective-policy.json"
    jq --arg archive "/backups/$name" '."(global)".files.ignore[-1] = ("!" + $archive)' "$policy" >"$effective"
    policy="$effective"
    ;;
  zigbee2mqtt)
    test -f /data/backups/zigbee2mqtt.zip
    test ! -L /data/backups/zigbee2mqtt.zip
    test -s /data/backups/zigbee2mqtt.zip
    # An old staging export must not count as a fresh network backup.
    test "$(( $(date +%s) - $(stat -c %Y /data/backups/zigbee2mqtt.zip) ))" -le 3600
    ;;
  *) exit 1 ;;
esac
# Import retains ignore-rule order. CLI ignore flags sort these rules.
kopia --config-file="$config" --disable-file-logging policy import --global --from-file="$policy" >/dev/null
kopia --config-file="$config" --disable-file-logging policy show /data --json |
  jq -e --slurpfile expected "$policy" '
    .files == $expected[0]["(global)"].files and
    .retention == $expected[0]["(global)"].retention and
    .errorHandling == $expected[0]["(global)"].errorHandling' >/dev/null
