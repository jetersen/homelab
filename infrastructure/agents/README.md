# Agent telemetry integration

Kubernetes receiver, privacy filters, alert rules, and storage configuration live
in [agent-telemetry](../../kubernetes/cluster/agent-telemetry/).

NixOS/Home Manager owns the host services and packages. See the dotfiles
[agent session setup and recovery guide](https://github.com/jetersen/dotfiles/blob/main/docs/agent-sessions.md).

Configure existing OTLP clients with
`uv run configure_clients.py --endpoint COLLECTOR_URL`. Existing processes retain
their startup settings; restart them only when idle. Review the collector's
attribute allowlists when upgrading clients. Conversation search is separate
from telemetry filtering.

The backup service uses this checkout's Varlock schema and secret-provider
integration. Keep those available when moving the checkout or changing how
credentials are resolved.
