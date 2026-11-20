# Agent session search and backups

AgentsView provides local keyword and semantic search over supported agent
transcripts. Embeddings use the local shared Nomic model; no embedding API key
is required. The archive retains conversation text but omits tool payloads.

Run `python3 install.py` to install the pinned AgentsView release and Kopia under
`~/.local/share/agent-observability/bin`. Verify release checksums before use.
The installer also copies the user units and initial configuration. Enable the
search service, HTTPS route, and refresh timer with `systemctl --user enable --now
agentsview.service agent-session-route.service t3-search.timer`. The data filesystem must be mounted before
starting the services. Keep it private to the service user.

`t3_search.py` reads the T3 SQLite database without modifying it and imports
conversations through AgentsView's supported ChatGPT exchange API. These appear
as ChatGPT imports with a T3 title prefix and a link to the original thread.
The importer excludes streaming messages and advances its cursor only after all
imports succeed. A copied completion marker is informational; review and mark
threads settled in T3. A completed agent run does not establish task completion.

For subpath hosting, use AgentsView's `--base-path` and an origin-only
`--public-url`. The proxy must preserve the prefix upstream. Network grants do
not distinguish URL paths; use application authentication if services need
different audiences.

The backup service resolves existing S3 credentials and the repository password
through Varlock. Initialize a separate Kopia repository prefix before enabling
the timer. Retain the repository password and S3 access independently of the
machine. The service takes an online SQLite backup within a read transaction,
checks it, and snapshots it alongside original transcript and attachment roots.
It excludes working trees, repository contents, and unrelated application state.

For recovery, stop T3 before replacing its database. Restore the T3 snapshot and
attachments using Kopia, run SQLite `PRAGMA quick_check`, and preserve the matching
environment ID. Restore transcripts to their original agent roots. The search
index is disposable and can be rebuilt. Restore tests must use a separate
scratch directory and must never overwrite live data.

Configure OTLP clients with `uv run configure_clients.py --endpoint COLLECTOR_URL`.
Existing client processes retain their startup configuration; restart them only
when idle. The collector accepts OTLP/HTTP and forwards filtered metrics, events,
and traces to the configured Victoria backends. Review its attribute allowlists
when upgrading clients. Conversation search is separate from telemetry filtering.
