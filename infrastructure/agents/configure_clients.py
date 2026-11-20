# /// script
# dependencies = ["tomlkit==0.14.0"]
# ///
"""Configure existing agent clients without changing credentials or restarting them."""

import argparse
import json
from pathlib import Path

import tomlkit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    endpoint = args.endpoint.rstrip("/")
    home = Path.home()
    codex = home / ".codex/config.toml"
    config = tomlkit.parse(codex.read_text())
    otel = config.setdefault("otel", tomlkit.table())
    otel.update(
        environment="homelab",
        log_user_prompt=False,
        log_agent_responses=False,
        log_sse_deltas=False,
    )
    for key, signal in [
        ("exporter", "logs"),
        ("trace_exporter", "traces"),
        ("metrics_exporter", "metrics"),
    ]:
        otel[key] = {"otlp-http": {"endpoint": endpoint + "/v1/" + signal, "protocol": "binary"}}
    codex.write_text(tomlkit.dumps(config))
    claude = home / ".claude/settings.json"
    config = json.loads(claude.read_text())
    config.setdefault("env", {}).update(
        CLAUDE_CODE_ENABLE_TELEMETRY="1",
        OTEL_METRICS_EXPORTER="otlp",
        OTEL_LOGS_EXPORTER="otlp",
        OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf",
        OTEL_EXPORTER_OTLP_ENDPOINT=endpoint,
        OTEL_RESOURCE_ATTRIBUTES="host.name=rocket",
        OTEL_METRICS_INCLUDE_SESSION_ID="false",
        OTEL_METRICS_INCLUDE_ACCOUNT_UUID="false",
        OTEL_LOG_USER_PROMPTS="false",
        OTEL_LOG_TOOL_DETAILS="false",
    )
    claude.write_text(json.dumps(config, indent=2) + "\n")
    t3 = home / ".t3/userdata/settings.json"
    config = json.loads(t3.read_text())
    config.setdefault("observability", {}).update(
        otlpMetricsUrl=endpoint + "/v1/metrics",
        otlpLogsUrl=endpoint + "/v1/logs",
        otlpTracesUrl=endpoint + "/v1/traces",
    )
    t3.write_text(json.dumps(config, indent=2) + "\n")
    print("Client telemetry configured; existing processes may require an idle restart")


if __name__ == "__main__":
    main()
