# AGENTS.md

## Kubernetes

- Use kube context `homelab` for cluster operations.

## GitOps

- Prefer updating manifests in this repo.
- Flux-managed Kubernetes resources live under `kubernetes/`.

## Git

- Use conventional commits.

## TrueNAS

- Use the JSON-RPC 2.0 API over encrypted WebSocket at `wss://<host>/api/current`. Do not use deprecated REST `/api/v2.0` endpoints or the legacy `/websocket` protocol.
- Verify the installed TrueNAS version and method schemas in the NAS's served `/api/docs/current/` documentation before calling APIs. On 25.10, `auth.login_with_api_key` is supported over JSON-RPC; follow the matching authentication schema after upgrades.
- Read the Varlock skill and inject `TRUENAS_HOST` and `TRUENAS_TOKEN` with `npm exec -- varlock run -- <command>`. Keep credentials out of command arguments, logs, and agent output; do not read secret environment files.
- Verify TLS using a trusted certificate and matching hostname. If the NAS has a self-signed certificate, inspect it first and keep any temporary verification bypass scoped to the specific client connection; report that limitation.
- Inspection is read-only. Do not start tests, scrubs, upgrades, or change NAS configuration without authorization for that action.
