import contextlib
import io
import json
import unittest
from unittest.mock import patch

import manage
import settings_fix
import smarttube
import smarttube_tile
import test_smarttube
from test_smarttube import IDENTITY, ORIGINAL


class SmartTubeTileTests(unittest.TestCase):
    effective = test_smarttube.SmartTubeTests.effective

    def setUp(self):
        test_smarttube.SmartTubeTests.setUp(self)
        with contextlib.redirect_stdout(io.StringIO()):
            smarttube.command(
                "smarttube-apply", self.device, self.profile, IDENTITY, self.directory
            )
        self.native_record = self.path.read_bytes()
        self.native_config = self.device.configs[settings_fix.PACKAGE]
        self.device.data["account"] = "local-account-state"
        self.path = self.directory / "smarttube_tile.json"
        self.apk = self.directory / "tile.apk"
        self.apk.write_bytes(b"permission-free tile APK")
        self.device.hashes[smarttube.TILE_PACKAGE] = manage.digest(self.apk)
        patch.object(smarttube_tile, "artifact", return_value=self.apk).start()

    def command(self, action):
        with contextlib.redirect_stdout(io.StringIO()):
            smarttube_tile.command(action, self.device, self.profile, IDENTITY, self.directory)

    def test_tile_round_trip_retains_native_accounts_and_first_baseline(self):
        self.command("smarttube-tile-plan")
        self.assertFalse(self.path.exists())
        self.command("smarttube-tile-apply")
        self.assertIn(
            b"apps.order=tv.homelab.smarttube,", self.device.configs[settings_fix.PACKAGE]
        )
        self.command("smarttube-tile-verify")
        self.command("smarttube-tile-restore")
        self.assertNotIn(smarttube.TILE_PACKAGE, self.device.installed)
        self.assertIn(smarttube.PACKAGE, self.device.installed)
        self.assertEqual(self.device.data["account"], "local-account-state")
        self.assertEqual(self.device.configs[settings_fix.PACKAGE], self.native_config)
        self.assertEqual((self.directory / "smarttube.json").read_bytes(), self.native_record)

    def test_native_restore_undoes_tile_before_native_app(self):
        self.command("smarttube-tile-apply")
        path = self.directory / "smarttube.json"
        smarttube.restore(self.device, smarttube.load(path, IDENTITY), path)
        removals = [e for e in self.device.events if e[0] == "uninstall"]
        self.assertEqual(
            removals, [("uninstall", smarttube.TILE_PACKAGE), ("uninstall", smarttube.PACKAGE)]
        )
        self.assertEqual(self.device.configs[settings_fix.PACKAGE], ORIGINAL)

    def test_failed_tile_install_keeps_native_app_and_accounts(self):
        self.device.fail_config = True
        with self.assertRaisesRegex(RuntimeError, "write refused"):
            self.command("smarttube-tile-apply")
        self.assertNotIn(smarttube.TILE_PACKAGE, self.device.installed)
        self.assertIn(smarttube.PACKAGE, self.device.installed)
        self.assertEqual(self.device.data["account"], "local-account-state")
        self.assertEqual(self.device.configs[settings_fix.PACKAGE], self.native_config)

    def test_failed_reapply_keeps_last_tile_baseline_and_native_accounts(self):
        self.command("smarttube-tile-apply")
        baseline = self.path.read_bytes()
        before = self.device.configs[settings_fix.PACKAGE]
        self.profile["appearance"]["accent"] = "cyan"
        self.device.fail_config = True
        with self.assertRaisesRegex(RuntimeError, "write refused"):
            self.command("smarttube-tile-apply")
        self.assertEqual(self.path.read_bytes(), baseline)
        self.assertEqual(self.device.configs[settings_fix.PACKAGE], before)
        self.assertEqual(self.device.data["account"], "local-account-state")

    def test_tile_reapply_preserves_baseline(self):
        self.command("smarttube-tile-apply")
        baseline = self.path.read_bytes()
        self.command("smarttube-tile-apply")
        self.assertEqual(self.path.read_bytes(), baseline)

    def test_existing_retained_other_user_or_changed_native_apk_are_refused(self):
        self.device.retained.add(smarttube.TILE_PACKAGE)
        with self.assertRaisesRegex(RuntimeError, "existing or retained"):
            self.command("smarttube-tile-apply")
        self.device.retained.clear()
        self.device.other_user = True
        with self.assertRaisesRegex(RuntimeError, "Another user"):
            self.command("smarttube-tile-apply")
        self.device.other_user = False
        self.device.hashes[smarttube.PACKAGE] = "unreviewed-update"
        with self.assertRaisesRegex(RuntimeError, "Installed SmartTube changed"):
            self.command("smarttube-tile-apply")
        self.assertFalse(self.path.exists())

    def test_restore_does_not_require_profile_build_cache_or_native_account_access(self):
        self.command("smarttube-tile-apply")
        self.profile.clear()
        self.command("smarttube-tile-restore")
        self.assertEqual(self.device.configs[settings_fix.PACKAGE], self.native_config)
        self.assertEqual(self.device.data["account"], "local-account-state")

    def test_cli_follows_tile_and_blocks_incomplete_transactions(self):
        self.command("smarttube-tile-apply")
        profile = self.directory / "profile.json"
        profile.write_text(json.dumps(self.profile))
        with (
            patch.object(manage, "Device", return_value=self.device),
            patch.object(self.device, "identity", return_value=IDENTITY, create=True),
        ):
            for action in (
                "verify",
                "youtube-verify",
                "smarttube-verify",
                "smarttube-plan",
                "apply",
            ):
                with (
                    self.subTest(action=action),
                    patch(
                        "sys.argv",
                        [
                            "manage.py",
                            action,
                            "--profile",
                            str(profile),
                            "--state-dir",
                            str(self.directory),
                        ],
                    ),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    manage.main()
            state = smarttube.load(self.path, IDENTITY)
            state["status"] = "pending"
            manage.save(self.path, state)
            before = list(self.device.events)
            with patch(
                "sys.argv", ["manage.py", "privacy-apply", "--state-dir", str(self.directory)]
            ):
                with self.assertRaisesRegex(RuntimeError, "interrupted SmartTube"):
                    manage.main()
            self.assertEqual(self.device.events, before)

    def test_external_tile_update_cannot_be_removed(self):
        self.command("smarttube-tile-apply")
        self.device.hashes[smarttube.TILE_PACKAGE] = "external-update"
        before = self.device.configs[settings_fix.PACKAGE]
        with self.assertRaisesRegex(RuntimeError, "APK changed"):
            self.command("smarttube-tile-restore")
        self.assertEqual(self.device.configs[settings_fix.PACKAGE], before)
        self.assertEqual(self.device.data["account"], "local-account-state")


if __name__ == "__main__":
    unittest.main()
