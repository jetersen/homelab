import base64
import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manage
import settings_fix
import smarttube

IDENTITY = {"serial": "test-device", "build": "test-build"}
ORIGINAL = b"# exact previous bytes\r\napps.order=tv.homelab.youtube\r\n"


class FakeDevice:
    config_package = "tv.dumbtv.home"

    def __init__(self, profile):
        self.installed = {
            "tv.dumbtv.home",
            settings_fix.PACKAGE,
            "tv.homelab.youtube",
            "com.google.android.youtube.tv",
            "org.jellyfin.androidtv",
            "ch.protonvpn.android",
        }
        self.retained = set()
        self.configs = {
            "tv.dumbtv.home": b"original upstream config",
            settings_fix.PACKAGE: ORIGINAL,
        }
        self.hashes = {
            "tv.dumbtv.home": profile["launcher"]["sha256"],
            settings_fix.PACKAGE: "patched-sha",
            smarttube.PACKAGE: profile["smarttube"]["sha256"],
        }
        self.current_home = settings_fix.PACKAGE + "/.Home"
        self.events = []
        self.other_user = False
        self.fail_config = False
        self.interrupt_install = False
        self.reject_install = False
        self.data = {}

    def packages(self, *flags):
        return self.installed | (self.retained if "-u" in flags else set())

    def activities(self, category, include_disabled=False):
        return {p + "/.Activity" for p in self.installed}

    def require_private_launcher(self, package):
        manage.require(not self.other_user, "Another user owns the package.")

    def home(self):
        return self.current_home

    def installed_digest(self, package):
        manage.require(package in self.installed, "APK is missing.")
        return self.hashes[package]

    def read_config(self):
        return base64.b64encode(self.configs[self.config_package]).decode()

    def write_config(self, content):
        if self.fail_config:
            self.fail_config = False
            raise RuntimeError("Configuration write refused.")
        self.events.append(("config", self.config_package))
        self.configs[self.config_package] = content

    def run(self, *args):
        self.events.append(args)
        if args[0] == "install":
            manage.require(not self.reject_install, "Install rejected.")
            package = (
                smarttube.TILE_PACKAGE if Path(args[-1]).name == "tile.apk" else smarttube.PACKAGE
            )
            self.installed.add(package)
            if self.interrupt_install:
                raise KeyboardInterrupt
        elif args[0] == "uninstall" and args[1] in smarttube.PACKAGES.values():
            self.installed.remove(args[1])
            if args[1] == smarttube.PACKAGE:
                self.data.clear()
        else:
            raise AssertionError(args)
        return "Success"

    def shell(self, *args):
        if args == ("input", "keyevent", "KEYCODE_HOME"):
            return ""
        if args == ("dumpsys", "activity", "activities"):
            return "mResumedActivity " + self.current_home
        raise AssertionError(args)


class SmartTubeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.profile = json.loads((Path(__file__).parent / "profile.json").read_text())
        self.apk = self.directory / "app.apk"
        self.apk.write_bytes(b"test reviewed APK")
        self.profile["smarttube"]["sha256"] = manage.digest(self.apk)
        self.device = FakeDevice(self.profile)
        self.path = self.directory / "smarttube.json"
        self.base = {
            "schema": 2,
            "identity": IDENTITY,
            "launcher": self.profile["launcher"],
            "status": "applied",
        }
        manage.save(self.directory / "state.json", self.base)
        settings_fix.state_path(self.directory).parent.mkdir()
        effective = self.effective(self.profile)
        manage.save(
            settings_fix.state_path(self.directory),
            {
                "schema": 2,
                "identity": IDENTITY,
                "launcher": effective["launcher"],
                "status": "applied",
            },
        )
        self.addCleanup(patch.stopall)
        patch.object(settings_fix, "patched_profile", side_effect=self.effective).start()
        patch.object(smarttube, "artifact", return_value=self.apk).start()

    def effective(self, profile):
        result = copy.deepcopy(profile)
        result["launcher"].update(
            package=settings_fix.PACKAGE,
            component=settings_fix.PACKAGE + "/.Home",
            sha256="patched-sha",
        )
        result.pop("home_fallback", None)
        return result

    def command(self, action):
        with contextlib.redirect_stdout(io.StringIO()):
            smarttube.command(action, self.device, self.profile, IDENTITY, self.directory)

    def test_plan_does_not_mutate_tv_or_write_a_baseline(self):
        self.command("smarttube-plan")
        self.assertEqual(self.device.events, [])
        self.assertFalse(self.path.exists())

    def test_round_trip_keeps_prior_apps_configs_and_recovery_records(self):
        before = set(self.device.installed)
        records = {p: p.read_bytes() for p in self.directory.rglob("*.json")}
        self.command("smarttube-apply")
        install = next(e for e in self.device.events if e[0] == "install")
        self.assertEqual(install, ("install", "--user", "0", str(self.apk)))
        self.assertIn(
            b"apps.order=app.smarttube.fdroid,", self.device.configs[settings_fix.PACKAGE]
        )
        self.assertEqual(self.device.configs["tv.dumbtv.home"], b"original upstream config")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.command("smarttube-verify")
        self.command("smarttube-restore")
        self.assertEqual(self.device.installed, before)
        self.assertEqual(self.device.configs[settings_fix.PACKAGE], ORIGINAL)
        self.assertEqual(self.device.current_home, settings_fix.PACKAGE + "/.Home")
        self.assertEqual(self.device.config_package, "tv.dumbtv.home")
        for path, content in records.items():
            self.assertEqual(path.read_bytes(), content)

    def test_reapply_preserves_first_baseline_and_account_data(self):
        self.command("smarttube-apply")
        baseline = self.path.read_bytes()
        self.device.data["account"] = "test-local-account-state"
        self.command("smarttube-apply")
        self.assertEqual(self.path.read_bytes(), baseline)
        self.assertEqual(len([e for e in self.device.events if e[0] == "install"]), 1)
        self.assertEqual(self.device.data["account"], "test-local-account-state")

    def test_failed_reapply_restores_last_config_without_removing_account_data(self):
        self.command("smarttube-apply")
        baseline = self.path.read_bytes()
        before = self.device.configs[settings_fix.PACKAGE]
        self.device.data["account"] = "test-local-account-state"
        self.profile["appearance"]["accent"] = "cyan"
        self.device.fail_config = True
        with self.assertRaisesRegex(RuntimeError, "write refused"):
            self.command("smarttube-apply")
        self.assertEqual(self.path.read_bytes(), baseline)
        self.assertEqual(self.device.configs[settings_fix.PACKAGE], before)
        self.assertEqual(self.device.data["account"], "test-local-account-state")
        self.assertNotIn(("uninstall", smarttube.PACKAGE), self.device.events)

    def test_fresh_config_failure_and_interrupted_install_remove_only_new_app(self):
        before = set(self.device.installed)
        for failure in ("fail_config", "interrupt_install", "reject_install"):
            with self.subTest(failure=failure):
                setattr(self.device, failure, True)
                with self.assertRaises((RuntimeError, KeyboardInterrupt)):
                    self.command("smarttube-apply")
                self.assertEqual(self.device.installed, before)
                self.assertEqual(self.device.configs[settings_fix.PACKAGE], ORIGINAL)
                self.assertEqual(smarttube.load(self.path, IDENTITY)["status"], "restored")
                self.path.unlink()
                setattr(self.device, failure, False)

    def test_existing_retained_or_other_user_installations_are_refused(self):
        self.device.retained.add(smarttube.PACKAGE)
        with self.assertRaisesRegex(RuntimeError, "existing or retained"):
            self.command("smarttube-apply")
        self.device.retained.clear()
        self.device.other_user = True
        with self.assertRaisesRegex(RuntimeError, "Another user"):
            self.command("smarttube-apply")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.device.events, [])

    def test_external_apk_update_cannot_be_removed_by_restore(self):
        self.command("smarttube-apply")
        self.device.hashes[smarttube.PACKAGE] = "externally-updated"
        before = list(self.device.events)
        with self.assertRaisesRegex(RuntimeError, "APK changed"):
            self.command("smarttube-restore")
        self.assertEqual(self.device.events, before)

    def test_full_restore_undoes_smarttube_before_removing_the_settings_patch(self):
        self.command("smarttube-apply")

        def restore_patch(*args):
            self.assertNotIn(smarttube.PACKAGE, self.device.installed)
            self.assertEqual(self.device.configs[settings_fix.PACKAGE], ORIGINAL)
            self.assertEqual(smarttube.load(self.path, IDENTITY)["status"], "restored")
            raise RuntimeError("checked restore ordering")

        with patch.object(settings_fix, "restore", side_effect=restore_patch):
            with self.assertRaisesRegex(RuntimeError, "checked restore ordering"):
                manage.restore(self.device, self.base, self.directory / "state.json")

    def test_changed_device_or_pin_cannot_reuse_first_baseline(self):
        self.command("smarttube-apply")
        with self.assertRaisesRegex(RuntimeError, "Device or firmware differs"):
            smarttube.load(self.path, {**IDENTITY, "build": "changed"})
        self.profile["smarttube"]["version_code"] += 1
        before = list(self.device.events)
        with self.assertRaisesRegex(RuntimeError, "before changing"):
            self.command("smarttube-apply")
        self.assertEqual(self.device.events, before)

    def test_pending_baseline_blocks_launcher_and_new_applies(self):
        self.command("smarttube-apply")
        state = smarttube.load(self.path, IDENTITY)
        state["status"] = "pending"
        manage.save(self.path, state)
        before = list(self.device.events)
        with self.assertRaisesRegex(RuntimeError, "smarttube-restore"):
            manage.apply(self.device, self.profile, IDENTITY, b"", self.directory / "state.json")
        with self.assertRaisesRegex(RuntimeError, "previous SmartTube transaction"):
            self.command("smarttube-apply")
        self.assertEqual(self.device.events, before)

    def test_restore_remains_available_without_the_current_profile_or_cache(self):
        self.command("smarttube-apply")
        self.profile.clear()
        self.command("smarttube-restore")
        self.assertEqual(self.device.configs[settings_fix.PACKAGE], ORIGINAL)

    def test_legacy_adapter_keeps_the_existing_helper_workflow(self):
        before = copy.deepcopy(self.profile)
        legacy = smarttube.legacy_profile(self.profile)
        self.assertEqual(legacy["apps"][0]["candidates"][0], "tv.homelab.youtube")
        self.assertEqual(self.profile, before)

    def test_tampered_download_is_refused_before_install_or_baseline(self):
        self.apk.write_bytes(b"changed APK")
        with self.assertRaisesRegex(RuntimeError, "download changed"):
            self.command("smarttube-apply")
        self.assertEqual(self.device.events, [])
        self.assertFalse(self.path.exists())

    def test_home_verification_retries_a_consumed_first_event(self):
        foreground = "com.android.tv.settings/.MainSettings"
        homes = 0

        def shell(*args):
            nonlocal foreground, homes
            if args == ("input", "keyevent", "KEYCODE_HOME"):
                homes += 1
                if homes == 2:
                    foreground = self.device.current_home
                return ""
            if args == ("dumpsys", "activity", "activities"):
                return "mResumedActivity " + foreground
            raise AssertionError(args)

        profile = self.effective(self.profile)
        with (
            patch.object(self.device, "shell", side_effect=shell),
            patch.object(manage.time, "sleep"),
        ):
            with smarttube.route(self.device, settings_fix.PACKAGE):
                manage.verify(self.device, profile, ORIGINAL)
        self.assertEqual(homes, 2)

    def test_cli_verifies_active_smarttube_and_blocks_underlying_changes(self):
        self.command("smarttube-apply")
        profile_path = self.directory / "profile.json"
        profile_path.write_text(json.dumps(self.profile))
        with (
            patch.object(manage, "Device", return_value=self.device),
            patch.object(self.device, "identity", return_value=IDENTITY, create=True),
        ):
            for action in ("verify", "youtube-verify", "settings-restore", "youtube-restore"):
                with (
                    self.subTest(action=action),
                    patch(
                        "sys.argv",
                        [
                            "manage.py",
                            action,
                            "--profile",
                            str(profile_path),
                            "--state-dir",
                            str(self.directory),
                        ],
                    ),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    if action.endswith("restore"):
                        with self.assertRaisesRegex(RuntimeError, "smarttube-restore"):
                            manage.main()
                    else:
                        manage.main()

    def test_cli_blocks_privacy_apply_during_an_interrupted_smarttube_transaction(self):
        self.command("smarttube-apply")
        state = smarttube.load(self.path, IDENTITY)
        state["status"] = "pending"
        manage.save(self.path, state)
        before = list(self.device.events)
        with (
            patch.object(manage, "Device", return_value=self.device),
            patch.object(self.device, "identity", return_value=IDENTITY, create=True),
            patch("sys.argv", ["manage.py", "privacy-apply", "--state-dir", str(self.directory)]),
        ):
            with self.assertRaisesRegex(RuntimeError, "interrupted SmartTube"):
                manage.main()
        self.assertEqual(self.device.events, before)

    def test_fetch_refuses_wrong_certificate_or_manifest_before_trusting_cache(self):
        for signer, manifest in (
            ("wrong", "unused"),
            (self.profile["smarttube"]["signer_sha256"], "wrong manifest"),
        ):
            with self.subTest(signer=signer):
                results = [
                    subprocess.CompletedProcess(
                        [], 0, "Signer #1 certificate SHA-256 digest: " + signer, ""
                    ),
                    subprocess.CompletedProcess([], 0, manifest, ""),
                ]
                with (
                    patch.object(manage, "artifact", return_value=self.apk),
                    patch.object(smarttube.subprocess, "run", side_effect=results),
                ):
                    with self.assertRaisesRegex(RuntimeError, "differs"):
                        smarttube.fetch(self.profile, self.directory)
                self.assertFalse(self.apk.with_suffix(".verified.json").exists())


if __name__ == "__main__":
    unittest.main()
