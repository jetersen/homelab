# Nix binary cache

Attic stores prebuilt workstation systems published by Forgejo Actions. Access
requires a cache token and is restricted to the same private networks as Forgejo.
The laptop trusts the cache's Nix signing key and uses a read-only token;
CI receives a separate token with push access to the `workstations` cache.

The retained PVC contains both the object store and SQLite database. The database
also contains the cache's signing key. Preserve it when restoring the service;
recreating the cache generates a different key and requires updating clients.
JWT signing credentials are encrypted in `app/credentials.sops.yaml`. Rotate
client tokens before expiry and update the corresponding Forgejo secret or
workstation sops secret. Retention removes unused cached objects; installed NixOS
generations remain on each workstation independently.
