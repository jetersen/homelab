#!/usr/bin/env bash
set -euo pipefail
source /etc/os-release
test "$VERSION_CODENAME" = trixie
node --version
git --version
docker --version
docker buildx version
kubectl version --client
curl --version
jq --version
python3 --version
dnscontrol version
go version
dotnet --version
ruff --version
biome --version
gcc --version
pulumi version
command -v pulumi-language-dotnet
flux --version
git-cliff --version
