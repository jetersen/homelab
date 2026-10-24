"""Regression tests for required PR check selection and aggregation."""

import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("pr_checks", Path(__file__).with_name("pr-checks.py"))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
RULES = json.loads(Path(__file__).with_name("pr-checks.json").read_text())


class PrChecksTests(unittest.TestCase):
    def test_cluster_route_changes_validate_dns(self):
        path = "kubernetes/apps/renovate/app/httproute.yaml"
        self.assertTrue(checks.select_checks([path], RULES)["dns"])

    def test_truenas_checks_include_hidden_workflows_and_root_sources(self):
        for path in ["infrastructure/truenas/Program.cs", ".forgejo/workflows/truenas.yaml"]:
            self.assertTrue(checks.select_checks([path], RULES)["truenas"])
        self.assertTrue(checks.select_checks(["global.json"], RULES)["csharp"])
        self.assertTrue(checks.select_checks([".ci/tool.mjs"], RULES)["javascript"])

    def test_docs_skip_and_gate_changes_run_every_check(self):
        self.assertFalse(any(checks.select_checks(["README.md"], RULES).values()))
        self.assertTrue(all(checks.select_checks([".ci/pr-checks.py"], RULES).values()))

    def test_media_scanner_changes_validate_rust(self):
        for path in [
            "infrastructure/media-scan/src/engine.rs",
            "infrastructure/media-scan/Cargo.lock",
            ".forgejo/workflows/check-rust.yaml",
        ]:
            self.assertTrue(checks.select_checks([path], RULES)["rust"])


if __name__ == "__main__":
    unittest.main()
