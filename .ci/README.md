# OCI publication

`publish-oci.yaml` publishes the committed manifests and images to Forgejo
Packages and GHCR. It runs on `main` pushes or manual dispatch.

Packages use `main` and `sha-COMMIT_SHA` tags. Flux pulls from Forgejo;
`kubernetes/flux/instance-setup.yaml` uses GHCR for bootstrap.
