# AGENTS.md

## Kubernetes

- Use kube context `homelab` for cluster operations.
- Size Kubernetes CPU requests for measured normal demand, including init containers and sidecars, and omit CPU limits. Prefer CPU overcommit for homelab capacity while retaining control-plane and latency-sensitive reservations. Check chart and operator defaults so quotas are not reintroduced. Omit Docker CPU quotas too; preserve intentional memory limits and CPU scheduling weights.

## GitOps

- Prefer GitOps through this repo's `kubernetes/` manifests.
- Routine homelab deployments, commits, and Flux pushes need no separate approval when completing a requested task.
- Ask before destructive, data-affecting, broad, or hard-to-reverse changes; explain impact and rollback.

## Image and chart upgrades

- Apply application, chart, and image upgrades one at a time. After each upgrade, verify affected workloads are ready, nodes remain `Ready=True` with `DiskPressure=False`, and image-filesystem free space can accommodate the next planned pulls before proceeding. Treat CI render success as manifest validation only, not proof of live readiness.

## ExternalDNS

- Do not assume `--dry-run` suppresses writes through webhook providers. Never simulate changed or empty desired record sets against a live webhook unless write suppression is independently verified. Use saved records and offline comparisons for ownership audits.

## Git

- Use conventional commits.
- Keep history linear: rebase onto upstream and never create merge commits.
- Amending local commits and force-pushing amended or rebased commits are permitted. Fetch and inspect remote changes first, preserve unrelated work, and use `--force-with-lease` for force pushes.
- Keep one-off setup, migration, inspection, and recovery helpers outside the repository. Commit scripts only when maintained automation or deployed workloads require them.

## Documentation and operational records

- Keep live operational audits, inventory, credential-rotation records, backup locations, recovery artifacts, and incident details in protected private local storage outside the repository. Public documentation, including `AGENTS.md`, should contain only durable procedures and reusable rules.
- Keep READMEs focused on purpose, setup, and non-obvious constraints. Link to code or manifests for exact settings instead of restating them. Preserve essential recovery requirements and design rationale, but keep session reasoning, progress, validation results, personal workflows, and migration status in the conversation or private records.
- Check documentation claims against current sources. Describe configured behavior without implying verified live operation, security, or recoverability. Update existing guidance rather than appending a task summary.

## Talos

- Machine configurations contain bootstrap tokens, CA private keys, service-account signing keys, and the encryption secret. Capture raw configuration and diff output privately; never print them in agent output.
- `talosctl get machineconfig` can return its `spec` as serialized multi-document YAML. Decode that value, assert the expected mapping types, and print only explicitly selected non-secret fields. Never stringify an unknown structure or convert it to a list for debugging.
- `talosctl rotate-ca` can print newly generated private keys, including during dry-run. Capture its entire output privately and report only verified non-secret results.
- Rotate credentials using focused patches and supported trust transitions. Do not apply a full regenerated configuration as part of rotation. Synchronize the encrypted generator secrets and local client configurations afterward.
- After Kubernetes CA rotation, prune retired certificates from both CA bundles in `kube-system/extension-apiserver-authentication` and verify they stay absent. Kubernetes merges existing, nonexpired certificates into published authentication trust.
- Before retiring an encryption key, retain decryption overlap, rewrite the affected resources, and verify the stored ciphertext uses the replacement key. Keep encrypted recovery copies needed by older backups.
- Encryption rewrites must force storage updates; identical resource replacements can be skipped. Remove temporary metadata after verifying the replacement ciphertext.
- Keep interactive enrollment URLs out of terminal output and repository files.

## TrueNAS

- Use the JSON-RPC 2.0 API over encrypted WebSocket at `wss://<host>/api/current`. Do not use deprecated REST `/api/v2.0` endpoints or the legacy `/websocket` protocol.
- Verify the installed TrueNAS version and method schemas in the NAS's served `/api/docs/current/` documentation before calling APIs. On 25.10, `auth.login_with_api_key` is supported over JSON-RPC; follow the matching authentication schema after upgrades.
- Read the Varlock skill and inject `TRUENAS_HOST` and `TRUENAS_TOKEN` with `npm exec -- varlock run -- <command>`. Keep credentials out of command arguments, logs, and agent output; do not read secret environment files.
- Verify TLS using a trusted certificate and matching hostname. If the NAS has a self-signed certificate, inspect it first and keep any temporary verification bypass scoped to the specific client connection; report that limitation.
- Inspection is read-only. Do not start tests, scrubs, upgrades, or change NAS configuration without authorization for that action.
