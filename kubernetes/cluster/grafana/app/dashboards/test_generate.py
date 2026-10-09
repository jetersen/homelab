"""Regression checks for dashboard patch guards and collection compatibility."""

import json
import re
import unittest
from pathlib import Path

import generate
import yaml

ROOT = Path(__file__).parent
VALUES = yaml.safe_load((ROOT.parents[2] / "victoria-metrics/app/helmrelease.yaml").read_text())[
    "spec"
]["values"]


class DashboardTests(unittest.TestCase):
    def test_changed_upstream_query_aborts_patch(self):
        dashboard = {"panels": [{"title": "Depth", "targets": [{"expr": "new_metric"}]}]}
        with self.assertRaises(ValueError):
            generate.set_expression(dashboard, "Depth", "old_metric", "replacement")
        self.assertEqual(dashboard["panels"][0]["targets"][0]["expr"], "new_metric")

    def test_duplicate_upstream_panels_abort_patch(self):
        with self.assertRaises(ValueError):
            generate.one_panel({"panels": [{"title": "Depth"}] * 2}, "Depth")

    def test_dashboard_selectors_match_unlabelled_homelab(self):
        for path in ROOT.glob("*.json"):
            dashboard = json.loads(path.read_text())
            for target in generate.expressions(dashboard):
                self.assertNotIn('job="$cluster"', target["expr"])
                self.assertNotIn('cluster="$cluster"', target["expr"])
                self.assertNotIn('job="$job"', target["expr"])
            for variable in dashboard.get("templating", {}).get("list", []):
                if variable["name"] == "cluster":
                    self.assertEqual(variable["current"]["value"], ".*")

    def test_query_fixes_use_existing_metrics_and_correct_gauge_semantics(self):
        apiserver = json.loads((ROOT / "apiserver.json").read_text())
        target = generate.one_panel(apiserver, "Work Queue Depth")["targets"][0]
        self.assertNotIn("rate(", target["expr"])
        for name in ["global", "namespaces"]:
            dashboard = json.loads((ROOT / f"{name}.json").read_text())
            for target in generate.expressions(dashboard):
                self.assertNotRegex(
                    target["expr"],
                    r"kube_(namespace|deployment|statefulset|daemonset|networkpolicy)_labels",
                )

    def test_api_filter_preserves_alert_histograms_and_diagnostic_means(self):
        regex = VALUES["kubeApiServer"]["vmScrape"]["spec"]["endpoints"][0]["metricRelabelConfigs"][
            0
        ]["regex"]
        for metric in [
            "etcd_request_duration_seconds",
            "apiserver_request_body_size_bytes",
            "apiserver_watch_list_duration_seconds",
            "apiserver_watch_cache_read_wait_seconds",
            "apiserver_response_sizes",
            "apiserver_watch_events_sizes",
        ]:
            self.assertIsNotNone(re.fullmatch(regex, metric + "_bucket"))
            for suffix in ["_sum", "_count"]:
                self.assertIsNone(re.fullmatch(regex, metric + suffix))
        for metric in [
            "apiserver_request_sli_duration_seconds_bucket",
            "apiserver_client_certificate_expiration_seconds_bucket",
            "apiserver_request_duration_seconds_bucket",
        ]:
            self.assertIsNone(re.fullmatch(regex, metric))

    def test_probe_filter_preserves_failure_history(self):
        filters = VALUES["kubelet"]["vmScrapes"]["probes"]["spec"]["metricRelabelConfigs"]
        regex = next(rule["regex"] for rule in filters if rule["action"] == "drop")
        self.assertIsNone(re.fullmatch(regex, "prober_probe_total"))
        for suffix in ["bucket", "sum", "count"]:
            self.assertIsNotNone(re.fullmatch(regex, "prober_probe_duration_seconds_" + suffix))

    def test_default_dashboard_replacements_are_disabled(self):
        expected = {
            "apiserver",
            "kubelet",
            "etcd",
            "kubernetes-views-global",
            "kubernetes-views-namespaces",
        }
        disabled = {
            name
            for name, config in VALUES["defaultDashboards"]["dashboards"].items()
            if config.get("enabled") is False
        }
        self.assertEqual(disabled, expected)
        dashboards = [json.loads(path.read_text()) for path in ROOT.glob("*.json")]
        self.assertEqual(len(dashboards), 6)
        self.assertEqual(len({dashboard["uid"] for dashboard in dashboards}), 6)


if __name__ == "__main__":
    unittest.main()
