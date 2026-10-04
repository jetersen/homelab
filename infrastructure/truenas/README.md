# TrueNAS applications

Pulumi manages the NAS Technitium custom Compose app. Flux manages the Kubernetes
instance. Renovate groups their container image updates; deployments run
independently. DNS settings continue to replicate through Technitium's existing
cluster configuration, and ExternalDNS retains ownership of service records.

The `homelab-truenas/homelab` stack shares the existing OVH Pulumi state bucket
with the backup project, using a separate project namespace and the same
passphrase secret provider. Do not initialize this project against local state.

The provider is maintained at [jetersen/pulumi-truenas](https://github.com/jetersen/pulumi-truenas).
`restore-provider.py` downloads its NuGet release asset and verifies the published
checksum. The same package is published to GitHub Packages. Using release assets
avoids an additional package registry credential. NuGet source mapping restricts
this package to the downloaded feed, preventing fallback to nuget.org.
To upgrade the provider, update its project package reference, download that
release, and run `dotnet restore` without locked mode to refresh the lockfile.
Renovate's automatic updates cover the Technitium images; provider SDK upgrades
require this reviewed lockfile update.

From the repository root:

```sh
python3 infrastructure/truenas/restore-provider.py
dotnet restore infrastructure/truenas/Homelab.TrueNas.csproj --locked-mode
dotnet build infrastructure/truenas/Homelab.TrueNas.csproj --no-restore
npm exec -- varlock run -- pulumi -C infrastructure/truenas preview --stack homelab --refresh
npm exec -- varlock run -- pulumi -C infrastructure/truenas up --stack homelab
```

Local credentials come from the root Varlock schema. `TRUENAS_HOST` must use
HTTPS with a trusted hostname. Pulumi connects over `wss://HOST/api/current`.
The project schema validates credentials injected by Forgejo Actions.

The Forgejo workflow previews same-repository PRs and applies changes to `main`.
It requires the `TRUENAS_HOST` repository variable and these Actions secrets:
`TRUENAS_TOKEN`, `PULUMI_STATE_ACCESS_KEY_ID`, `PULUMI_STATE_SECRET_ACCESS_KEY`,
and `PULUMI_CONFIG_PASSPHRASE`. Keep them synchronized with the corresponding
Proton Pass items. Runs are serialized; there is no cross-platform deployment
sequencing or post-deployment health check.

Adopt existing apps by name with Pulumi import before enabling deployment. Keep
the existing app name and Compose volume keys to retain storage. The resource
uses `Protect` and `RetainOnDelete`; removing it requires explicit review.
Upstream does not read custom Compose configuration back into state, so refresh
does not detect manual edits to that document. Make app changes here.
