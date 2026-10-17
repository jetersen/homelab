#!/usr/bin/env bash
set -euo pipefail

# Renovate's NuGet restore discards local feeds. Use our verified release feed
# and restore the whole solution so project-reference lockfiles stay aligned.
sdk=$(node -p 'require("./global.json").sdk.version')
[[ $sdk =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
if [ "$(dotnet --version 2>/dev/null || true)" != "$sdk" ]; then
  # install-tool is provided by the pinned Renovate container (Containerbase).
  install-tool dotnet "$sdk"
fi
python3 infrastructure/truenas/restore-provider.py
dotnet restore Homelab.slnx --force-evaluate
