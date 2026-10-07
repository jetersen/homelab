import secrets
import stat
import tempfile
import unittest
from pathlib import Path

import yaml
from configure import configure


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Path(self.directory.name) / "settings.yml"
        self.template = Path(__file__).with_name("settings.yml")

    def test_first_boot_leaves_secret_generation_to_upstream(self):
        configure(self.settings, self.template)
        self.assertFalse(self.settings.exists())

    def test_updates_preserve_secret_and_are_idempotent(self):
        secret = secrets.token_hex(32)
        self.settings.write_text(yaml.safe_dump({"server": {"secret_key": secret}}))
        configure(self.settings, self.template)
        actual = yaml.safe_load(self.settings.read_text())
        self.assertTrue(actual["server"]["secret_key"] == secret)
        self.assertEqual(actual["search"]["autocomplete"], "")
        self.assertEqual(actual["search"]["suspended_times"]["SearxEngineTooManyRequests"], 3600)
        self.assertTrue(actual["use_default_settings"])
        self.assertNotIn("engines", actual)
        self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o600)
        modified = self.settings.stat().st_mtime_ns
        configure(self.settings, self.template)
        self.assertEqual(self.settings.stat().st_mtime_ns, modified)

    def test_invalid_secret_does_not_overwrite_existing_settings(self):
        for secret in (None, "", "ultrasecretkey"):
            with self.subTest(secret=secret):
                original = yaml.safe_dump({"server": {"secret_key": secret}})
                self.settings.write_text(original)
                with self.assertRaises(ValueError):
                    configure(self.settings, self.template)
                self.assertTrue(self.settings.read_text() == original)


if __name__ == "__main__":
    unittest.main()
