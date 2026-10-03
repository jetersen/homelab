import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


path = Path(__file__).resolve().parents[1] / "store-backup-secrets.py"
spec = importlib.util.spec_from_file_location("store_backup_secrets", path)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class SecretTransferTests(unittest.TestCase):
    def run_helper(self, items, password="K" * 64):
        created = []
        commands = []

        def capture(command, payload=None, label=None):
            commands.append(command)
            if command[:3] == ["pass-cli", "item", "list"]:
                return json.dumps({"items": items})
            if command[:3] == ["pass-cli", "password", "generate"]:
                return json.dumps({"password": password})
            if command[:3] == ["pass-cli", "item", "create"]:
                created.append(json.loads(payload))
                return ""
            raise AssertionError("Existing credentials must not be read on resume")

        output = io.StringIO()
        with patch.object(helper, "capture", side_effect=capture), \
                patch("sys.argv", ["helper", "--store"]), \
                patch.dict("os.environ", {}, clear=True), contextlib.redirect_stdout(output):
            helper.main()
        self.assertNotIn(password, output.getvalue())
        return created, commands

    def test_resume_preserves_s3_and_creates_only_kopia(self):
        created, commands = self.run_helper([
            {"title": "OVHcloud Homelab S3", "item_type": "login"},
        ])
        self.assertEqual([item["title"] for item in created], ["Homelab Kopia"])
        self.assertEqual(len(created[0]["password"]), 64)
        self.assertTrue(all("K" * 64 not in argument for command in commands for argument in command))

    def test_completed_setup_does_not_rotate_repository_password(self):
        created, commands = self.run_helper([
            {"title": title, "item_type": "login"}
            for title in ["OVHcloud Homelab S3", "Homelab Kopia"]
        ])
        self.assertEqual(created, [])
        self.assertEqual(len(commands), 1)

    def test_ambiguous_item_names_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "at most one login"):
            self.run_helper([
                {"title": "OVHcloud Homelab S3", "item_type": "login"},
                {"title": "OVHcloud Homelab S3", "item_type": "login"},
            ])

    def test_failed_cli_output_is_withheld(self):
        result = subprocess.CompletedProcess([], 1, stdout="secret-value", stderr="secret-value")
        with patch.object(helper.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "Create Kopia login failed") as error:
                helper.capture(["pass-cli"], label="Create Kopia login")
        self.assertNotIn("secret-value", str(error.exception))


if __name__ == "__main__":
    unittest.main()
