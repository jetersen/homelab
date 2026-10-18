"""Select applicable PR checks and reject unsuccessful aggregate results."""

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath


def select_checks(paths, rules):
    run_all = any(
        path in {".ci/pr-checks.py", ".ci/pr-checks.json", ".forgejo/workflows/pr-checks.yaml"}
        for path in paths
    )
    return {
        name: run_all
        or any(PurePosixPath(path).full_match(pattern) for path in paths for pattern in patterns)
        for name, patterns in rules.items()
    }


def verify_checks(results):
    if results.get("changes", {}).get("result") != "success":
        raise ValueError("PR check selection did not succeed")
    selected = results["changes"]["outputs"]
    for name, required in selected.items():
        expected = "success" if required == "true" else "skipped"
        if required not in {"true", "false"} or results.get(name, {}).get("result") != expected:
            raise ValueError(f"PR check {name} did not finish as {expected}")
    if set(results) != {"changes", *selected}:
        raise ValueError("PR check results do not match selected checks")


if __name__ == "__main__":
    if sys.argv[1] == "select":
        paths = (
            subprocess.check_output(
                ["git", "diff", "--name-only", "-z", f"{sys.argv[2]}...{sys.argv[3]}", "--"],
            )
            .decode()
            .split("\0")
        )
        rules = json.loads(Path(".ci/pr-checks.json").read_text())
        for name, selected in select_checks(paths, rules).items():
            print(f"{name}={str(selected).lower()}")
    elif sys.argv[1] == "verify":
        verify_checks(json.loads(os.environ["CHECK_RESULTS"]))
        print("Every applicable PR check passed")
    else:
        raise ValueError("Expected select or verify")
