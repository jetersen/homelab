#!/usr/bin/env python3
"""Regenerate bounded homelab overrides from pinned upstream dashboards."""

import argparse
import copy
import json
import urllib.request
from pathlib import Path

import yaml

DOTDC = "e4faf59e017a18e1b06fa64f11623bef15ce7507"
MIXINS = "97c701c0918b211a1d33791cf9d70c4fdb57a2cb"
KUBE_PROMETHEUS = "799f3d73b5adf5758c3119c9201d9f417accb6d0"
DATASOURCE = "P4169E866C3094E38"
ROOT = Path(__file__).parent


def fetch(repo, commit, path):
    url = f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode()


def panels(dashboard):
    for panel in dashboard.get("panels", []):
        yield panel
        yield from panels(panel)


def one_panel(dashboard, title):
    matches = [p for p in panels(dashboard) if p.get("title") == title]
    if len(matches) != 1:
        raise ValueError(f"Expected one {title!r} panel, found {len(matches)}")
    return matches[0]


def expressions(dashboard):
    for panel in panels(dashboard):
        for target in panel.get("targets", []):
            if "expr" in target:
                yield target


def replace_exact(dashboard, old, new, expected):
    targets = [t for t in expressions(dashboard) if old in t["expr"]]
    if len(targets) != expected:
        raise ValueError(f"Expected {expected} uses of {old!r}, found {len(targets)}")
    for target in targets:
        target["expr"] = target["expr"].replace(old, new)


def set_expression(dashboard, title, old_metric, expression, new_title=None):
    panel = one_panel(dashboard, title)
    targets = panel.get("targets", [])
    if len(targets) != 1 or old_metric not in targets[0].get("expr", ""):
        raise ValueError(f"Unexpected query shape for {title!r}")
    targets[0]["expr"] = expression
    if new_title:
        panel["title"] = new_title


def normalize(value):
    if isinstance(value, str):
        # The etcd mixin calls its job selector "cluster"; use the real label.
        return (
            value.replace('cluster="$cluster"', 'cluster=~"$cluster"')
            .replace('job="$cluster"', 'cluster=~"$cluster"')
            .replace('job="$job"', 'job=~"$job"')
        )
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    return value


def prepare(dashboard):
    dashboard = normalize(copy.deepcopy(dashboard))
    dashboard.pop("__inputs", None)
    for variable in dashboard["templating"]["list"]:
        if variable["name"] == "datasource":
            variable["current"] = {"text": "VictoriaMetrics", "value": DATASOURCE}
        elif variable["name"] == "cluster":
            # This cluster has no cluster label. .* also matches an absent label.
            variable.clear()
            variable.update(
                name="cluster",
                type="constant",
                query=".*",
                hide=2,
                current={"text": ".*", "value": ".*"},
            )
    dashboard["version"] = 1
    dashboard["editable"] = False
    return dashboard


def patched_dashboards():
    dotdc = "dotdc/grafana-dashboards-kubernetes"
    global_view = json.loads(fetch(dotdc, DOTDC, "dashboards/k8s-views-global.json"))
    namespaces = json.loads(fetch(dotdc, DOTDC, "dashboards/k8s-views-namespaces.json"))
    etcd = json.loads(
        fetch("monitoring-mixins/website", MIXINS, "assets/etcd/dashboards/etcd.json")
    )
    definitions = yaml.safe_load(
        fetch(
            "prometheus-operator/kube-prometheus",
            KUBE_PROMETHEUS,
            "manifests/grafana-dashboardDefinitions.yaml",
        )
    )
    embedded = {
        name: json.loads(value)
        for item in definitions["items"]
        for name, value in item.get("data", {}).items()
    }
    kubelet = embedded["kubelet.json"]
    apiserver = embedded["apiserver.json"]
    for resource in ["namespace", "deployment", "statefulset", "daemonset", "networkpolicy"]:
        # Count objects directly; label allowlists are unnecessary for this panel.
        old = f"sum(kube_{resource}_labels"
        new = f"count(kube_{resource}_created"
        replace_exact(global_view, old, new, 1)
        if resource != "namespace":
            replace_exact(namespaces, old, new, 1)
    # Current Kubernetes/KSM exposes EndpointSlices rather than legacy Endpoints.
    replace_exact(global_view, "sum(kube_endpoint_info", "count(kube_endpointslice_info", 1)
    for target in expressions(global_view):
        if "kube_endpointslice_info" in target["expr"]:
            target["legendFormat"] = "EndpointSlices"
    for dashboard in [global_view, namespaces]:
        replace_exact(
            dashboard, "sum(kube_hpa_labels", "count(kube_horizontalpodautoscaler_info", 1
        )
    set_expression(
        etcd,
        "Raft proposals",
        "etcd_server_leader_changes_seen_total",
        'sum(rate(etcd_server_proposals_committed_total{job=~".*etcd.*",cluster=~"$cluster"}[$__rate_interval])) by(cluster)',
        "Committed Raft proposals / second",
    )
    set_expression(
        apiserver,
        "Work Queue Depth",
        "rate(workqueue_depth",
        'sum(workqueue_depth{job="apiserver",instance=~"$instance",cluster=~"$cluster"}) by(instance,name,cluster)',
    )
    set_expression(
        kubelet,
        "Config Error Count",
        "kubelet_node_config_error",
        'sum(increase(prober_probe_total{job="kubelet",metrics_path="/metrics/probes",instance=~"$instance",cluster=~"$cluster",result="failed"}[5m])) or vector(0)',
        "Failed container probes (5m)",
    )
    set_expression(
        kubelet,
        "Storage Operation Error Rate",
        "storage_operation_errors_total",
        'sum(rate(storage_operation_duration_seconds_count{job="kubelet",metrics_path="/metrics",instance=~"$instance",cluster=~"$cluster",status!="success"}[$__rate_interval])) by(instance,operation_name,volume_plugin,cluster)',
    )
    set_expression(
        kubelet,
        "Request duration 99th quantile",
        "rest_client_request_duration_seconds_bucket",
        'sum(rate(rest_client_requests_total{job="kubelet",metrics_path="/metrics",instance=~"$instance",cluster=~"$cluster"}[$__rate_interval])) by(instance,code,method,cluster)',
        "API client requests / second by status",
    )
    one_panel(kubelet, "API client requests / second by status")["targets"][0]["legendFormat"] = (
        "{{instance}} {{method}} {{code}}"
    )
    result = {
        "global": global_view,
        "namespaces": namespaces,
        "etcd": etcd,
        "kubelet": kubelet,
        "apiserver": apiserver,
    }
    uids = {
        "global": "k8s_views_global",
        "namespaces": "k8s_views_ns",
        "etcd": "c2f4e12cdf69feb95caa41a5a1b423d9",
        "kubelet": "3138fa155d5915769fbded898ac09fd9",
        "apiserver": "09ec8aa1e996d6ffcd6817bbaff4db1b",
    }
    for name, dashboard in result.items():
        if dashboard["uid"] != uids[name]:
            raise ValueError(f"Upstream UID changed for {name}")
        result[name] = prepare(dashboard)
    return result


def diagnostics():
    datasource = {"type": "prometheus", "uid": DATASOURCE}
    specs = [
        ("API server storage call mean latency", "etcd_request_duration_seconds", "s"),
        ("Watch-list mean latency", "apiserver_watch_list_duration_seconds", "s"),
        ("Watch-cache freshness wait mean", "apiserver_watch_cache_read_wait_seconds", "s"),
        ("Mean request body size", "apiserver_request_body_size_bytes", "bytes"),
        ("Mean response size", "apiserver_response_sizes", "bytes"),
        ("Mean watch event size", "apiserver_watch_events_sizes", "bytes"),
    ]
    output = []
    for i, (title, metric, unit) in enumerate(specs):
        expression = (
            f'sum(rate({metric}_sum{{job="apiserver"}}[$__rate_interval])) / '
            f'sum(rate({metric}_count{{job="apiserver"}}[$__rate_interval]))'
        )
        output.append(
            {
                "id": i + 1,
                "title": title,
                "type": "timeseries",
                "description": "Average per observation; no observations yields no data. Percentiles require histogram buckets.",
                "datasource": datasource,
                "gridPos": {"x": i % 2 * 12, "y": i // 2 * 8, "w": 12, "h": 8},
                "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
                "targets": [{"refId": "A", "expr": expression}],
            }
        )
    output.append(
        {
            "id": 7,
            "title": "Failed container probes (rolling 5m)",
            "description": "Readiness and startup failures can be expected during startup or rollouts. Inspect sustained failures and service impact.",
            "type": "timeseries",
            "datasource": datasource,
            "gridPos": {"x": 0, "y": 24, "w": 24, "h": 10},
            "fieldConfig": {"defaults": {"unit": "short", "min": 0}, "overrides": []},
            "targets": [
                {
                    "refId": "A",
                    "expr": 'sum(increase(prober_probe_total{result="failed"}[5m])) by(namespace,pod,container,probe_type)',
                    "legendFormat": "{{namespace}}/{{pod}} {{container}} {{probe_type}}",
                }
            ],
        }
    )
    return {
        "uid": "homelab-control-plane-diagnostics",
        "title": "Homelab / Control plane diagnostics",
        "schemaVersion": 39,
        "version": 1,
        "tags": ["homelab"],
        "timezone": "browser",
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "panels": output,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Verify generated files without writing"
    )
    args = parser.parse_args()
    dashboards = patched_dashboards()
    dashboards["diagnostics"] = diagnostics()
    # Build all outputs before writes, so a changed upstream shape cannot partly regenerate.
    outputs = {
        ROOT / f"{name}.json": json.dumps(d, indent=2, ensure_ascii=False) + "\n"
        for name, d in dashboards.items()
    }
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f"Regenerate {path.name}")
        else:
            path.write_text(content)


if __name__ == "__main__":
    main()
