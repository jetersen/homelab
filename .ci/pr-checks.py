"""Select applicable PR checks and reject unsuccessful aggregate results."""

import json
import subprocess
import sys
from pathlib import Path, PurePosixPath


def select_checks(paths, rules):
    run_all = any(
        path
        in {
            ".ci/pr-checks.py",
            ".ci/pr-checks.json",
            ".forgejo/workflows/pr-checks.yaml",
            ".ci/pr-checks-gate.mjs",
            ".ci/generate-pr-checks.mjs",
        }
        for path in paths
    )
    return {
        name: run_all
        or any(PurePosixPath(path).full_match(pattern) for path in paths for pattern in patterns)
        for name, patterns in rules.items()
    }


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
    else:
        raise ValueError("Expected select")
