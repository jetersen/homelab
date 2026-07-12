---
name: unifi-network
description: Safely inspect and modify a homelab UniFi Network application through its versioned integration API using Varlock-managed credentials and matching local OpenAPI specifications. Use for UniFi clients, IP reservations, networks, WiFi, firewall policies and zones, traffic matching lists, ACLs, or API-version discovery.
---

# UniFi Network

Use the local integration API with credentials injected by Varlock. Never read `.env` or `.env.local`, print tokens, enable shell tracing, or place secrets in command arguments, files, logs, patches, or chat.

## Request helper

Use the bundled JavaScript helper for every integration API call. It loads credentials through `varlock/auto-load`, uses normal system DNS, discovers the supported API base and controller version, requires trusted TLS verification, keeps the token inside the process, and returns the API response on stdout. Never add custom DNS or insecure TLS fallbacks merely because the execution sandbox blocks network access; request escalation and rerun instead.

```bash
# Read and filter JSON
node .agents/skills/unifi-network/scripts/request.mjs GET /v1/info
node .agents/skills/unifi-network/scripts/request.mjs GET '/v1/sites?offset=0&limit=25' | jq

# Mutate only after following the write workflow; stream JSON on stdin
jq -n '{example: "value"}' |
  node .agents/skills/unifi-network/scripts/request.mjs --write PATCH /v1/example
```

GET and HEAD are allowed directly. POST, PATCH, PUT, and DELETE require `--write`; this guard does not replace the schema and safety checks below. Supply request bodies through stdin, never as arguments. The helper prints version, base path, and TLS status on stderr. Require `tls=verified` for HTTPS calls.

## Workflow

1. Work from the repository root and read `AGENTS.md`.
2. Read `.agents/skills/varlock/SKILL.md` before handling credentials.
3. Run `scripts/request.mjs` for access verification, discovery, and mutations; do not reconstruct Varlock or HTTP commands. If sandboxed DNS blocks Proton Pass, request escalation and rerun the helper.
4. Retain the helper's controller version, API base, and TLS status. If credential resolution needs separate diagnosis, run `npm exec varlock load -- --agent`; sensitive values remain masked.
5. Keep secrets out of paths and command arguments. Pipe request bodies into the helper so sensitive fields are not recorded in shell history or process listings.
6. Select the exact matching specification from `../unifi-apis/unifi-network/<version>.json` when available, otherwise fetch `https://raw.githubusercontent.com/beezly/unifi-apis/main/unifi-network/<version>.json`. Cache it under this skill's ignored `cache/` directory. Validate the version as dotted numeric text before constructing a path or URL. Download through a temporary file, require `.openapi`, `.info.title`, and an `.info.version` exactly matching the controller, then move it atomically into the cache. Revalidate cached files before reuse. Stop before writes if the exact specification is unavailable or invalid.
7. Inspect request and response schemas for every intended endpoint with `jq`.
8. Discover the site and current objects with read-only calls. Capture only the minimum non-secret fields needed to identify the target. Prefer stable UUIDs and MAC addresses over display names alone.
9. Before any write, read the full target object, derive the smallest valid PATCH when supported, and preserve unrelated fields and ordering. Avoid PUT unless the specification requires it.
10. For firewall changes, inspect policies, zones, traffic matching lists, and policy ordering together. Confirm that the rule still has the intended direction, action, source/destination, and precedence after the edit.
11. For an IP reservation, use only a mutation documented by the running version's exact specification. Confirm the IP belongs to the client's network and has no conflicting enabled reservation. Bind it to the active interface MAC; devices may expose different wired and WiFi MAC addresses.
12. Apply one logical change at a time, check the HTTP status and response against the selected schema, then re-read the modified object and dependent firewall objects.
13. Report the API version, object names, non-sensitive before/after summary, verification results, and any ambiguity. Do not report tokens or secret-bearing command lines.

## Inspect the specification

Resolve `skill_dir` as the directory containing this `SKILL.md`, then inspect the cached exact-version file:

```bash
spec="$skill_dir/cache/<version>.json"
jq -r '.info.version, .servers, (.paths | keys[])' "$spec"
jq '.paths["/v1/sites/{siteId}/firewall/policies/{firewallPolicyId}"]' "$spec"
jq '.components.schemas["Patch firewall policy"]' "$spec"
```

Inspect pagination and filter parameters on list operations and retrieve every page before concluding that an object is absent. For updates, follow the operation's request-body schema. Prefer the smallest accepted PATCH; when only PUT exists, map the current representation to the create/update schema without response-only fields. Use only operations documented by the exact specification.

## Safety

- Treat firewall and DHCP writes as live production changes. Require clear target identity; stop if multiple plausible clients or rules remain.
- Prefer GitOps manifests under `kubernetes/` when a Flux-managed resource exists. UniFi controller state is otherwise changed through the integration API.
- Use kube context `homelab` for any Kubernetes operations.
- Never disable or delete a rule merely to make an update succeed.
- Do not assume an IP reservation endpoint exists in every version; verify it in the exact OpenAPI document.
- Re-read policy ordering after firewall changes because a correct rule at the wrong priority can change connectivity.
