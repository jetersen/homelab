#!/usr/bin/env bash
set -euo pipefail
if [[ -f /usr/local/etc/env && -z ${CONTAINERBASE_ENV+x} ]]; then
  source /usr/local/etc/env
fi
if [[ ! -d /tmp/containerbase ]]; then
  containerbase-cli init tool all
fi
# Use Renovate's source entrypoint so the adapter patch is generated from source.
exec /usr/local/renovate/node --use-openssl-ca /usr/local/renovate/lib/renovate.ts "$@"
