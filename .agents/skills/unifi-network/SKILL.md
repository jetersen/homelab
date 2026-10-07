---
name: unifi-network
description: Inspect and manage homelab UniFi Network through its local API and discover supported operations from the controller's version-matched OpenAPI specification.
---

# UniFi Network

Prefer the local Network integration API. Read [the Varlock skill](../varlock/SKILL.md) before handling credentials; the bundled helper loads `UNIFI_HOST` and `UNIFI_TOKEN` through Varlock. Run it from the repository root. Keep credentials out of arguments and output.

## Discover version and capabilities

```bash
node .agents/skills/unifi-network/scripts/request.mjs GET /v1/info
node .agents/skills/unifi-network/scripts/request.mjs --openapi
```

The helper probes `/proxy/network/integration` and `/integration`, then reports the working base and Network `applicationVersion`. This is the Network application version, distinct from UniFi OS, device firmware, and the `/v1` API prefix. A failed probe does not prove the API is unsupported; check reachability, credentials, and deployment type.

Use the exact application version to find the contract:

1. Controller-local OpenAPI: `--openapi` fetches `/proxy/network/api-docs/integration.json` (or `/api-docs/integration.json` for the direct application base). It verifies the Network title, OpenAPI structure, and exact version against `/v1/info` before emitting JSON. This uses the installed controller's own contract, without a published-version dependency.
2. If local documentation is unavailable, use `https://developer.ui.com/network/v<version>/openapi.json` or the controller's Network > Integrations page. For readable endpoint discovery, use the versioned sibling `llms.txt`; [the root index](https://developer.ui.com/llms.txt) lists published versions. Do not substitute the latest version for the installed one.

Fetch the specification once per task; use a temporary file outside the repository for repeated inspection and remove it when finished. For fallback downloads, validate OpenAPI JSON, Network title, exact `info.version`, and populated `paths`. Require dotted numeric version text before interpolating paths or URLs. Inspect the requested method, parameters, request schema, and referenced components. Documentation establishes the contract; read-only calls confirm permissions and device support. If neither a matching spec nor installed documentation establishes a mutation, stop before that write.

## Call the API

```bash
node .agents/skills/unifi-network/scripts/request.mjs GET '/v1/sites?offset=0&limit=25'
```

Use returned site UUIDs for integration paths, not legacy names such as `default`. Follow documented pagination before concluding an object is absent. Filter responses to the fields needed; configuration responses may contain secrets.

Use `scripts/request.mjs` for integration calls. GET/HEAD need no flag; POST/PATCH/PUT/DELETE require `--write`. Stream JSON bodies on stdin, keeping secret values out of command text. The flag permits the HTTP method; it does not establish user authorization or validate the schema.

## Make changes

- Identify the site and target by stable ID or active interface MAC. Read current state and preserve unrelated fields. Use the smallest documented PATCH, or construct the required PUT from its request schema without response-only fields.
- For firewall edits, inspect zones, traffic matching lists, policies, and ordering together. Verify direction, action, source/destination, and precedence afterward; never delete or disable a rule to make an update succeed.
- For reservations, verify that the operation exists in this version, the IP belongs to the client's network, and no enabled reservation conflicts. Wired and WiFi interfaces can have different MACs.
- Apply one logical change, then re-read it. After an ambiguous write failure, inspect state before retrying. Report the version, non-secret before/after changes, and verification.
