# TrueNAS configuration

Pulumi manages the NAS Technitium Compose app and the Syncthing and Tailscale
catalog apps. Flux manages Kubernetes Technitium independently. DNSControl writes
records to the primary, which replicates to the NAS through Technitium's catalog.
Pulumi also manages the NFS service, its configuration, and exports in
[`Storage.cs`](Storage.cs). Datasets and pools have separate lifecycles.

The `homelab-truenas/homelab` stack uses the shared OVH Pulumi state bucket with
its own project namespace and the same passphrase provider. Do not initialize
it against local state.

## Local use

Run from the repository root:

```sh
python3 infrastructure/truenas/restore-provider.py
dotnet restore infrastructure/truenas/Homelab.TrueNas.csproj --locked-mode
dotnet build infrastructure/truenas/Homelab.TrueNas.csproj --no-restore
npm exec -- varlock run -- pulumi -C infrastructure/truenas preview --stack homelab --refresh
npm exec -- varlock run -- pulumi -C infrastructure/truenas up --stack homelab
```

Varlock resolves local credentials. `TRUENAS_HOST` must use
HTTPS with a trusted hostname; the provider connects over `wss://HOST/api/current`.

The [provider](https://github.com/jetersen/pulumi-truenas) is restored from a
checksum-verified release asset, avoiding a GitHub Packages credential. To upgrade
it, update the package reference, rerun `restore-provider.py`, and restore without
locked mode to refresh the lockfile. Renovate manages application versions;
provider upgrades need a reviewed lockfile update.

## Forgejo deployment

The workflow previews same-repository PRs and applies changes on `main`. Set the
`TRUENAS_HOST` repository variable and these secrets:

- `TRUENAS_TOKEN`
- `PULUMI_STATE_ACCESS_KEY_ID`
- `PULUMI_STATE_SECRET_ACCESS_KEY`
- `PULUMI_CONFIG_PASSPHRASE`

Forgejo injects these directly into Pulumi. Keep them synchronized with local
credentials. Runs are serialized and deploy independently of Flux.

## Adopting existing configuration

Import existing resources locally into this stack before pushing their declarations.
Use the existing `nas` provider: NFS shares import by their numeric share ID, the
NFS configuration by `nfs_config`, and the service by `nfs`. Require a refreshed
preview with no NAS changes before publishing an adoption.

Preserve export paths, allowed clients, and user/group mappings during adoption.
Use both `Protect` and `RetainOnDelete` for exports and services; removing an
unretained service resource can stop the service and disable autostart.
Keep import manifests and state recovery copies outside the repository.

## Managing apps

Import existing apps by name before enabling deployment. Preserve app names and
Compose volume keys to retain storage. Resources use `Protect` and `RetainOnDelete`.

Declare empty Compose volumes as `{}`; Pulumi omits null map entries. Keep
credentials out of catalog JSON files and inject them through Pulumi secrets.
Catalog values remain secret in previews and state. The create-only `catalogApp`
selector is ignored after import because upstream does not return it; other
settings remain managed. Catalog versions select their own container images.
