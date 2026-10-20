import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manage
import settings_fix as fix

PROFILE = json.loads((Path(__file__).parent / "profile.json").read_text())
IDENTITY = {"serial": "test-device", "build": "test-build"}


class FakeDevice:
    config_package = fix.ORIGINAL

    def __init__(self, sha):
        self.installed = {fix.ORIGINAL}
        self.retained = set()
        self.configs = {fix.ORIGINAL: b"# keep exact original\r\naccent=violet\r\n"}
        self.hashes = {fix.ORIGINAL: PROFILE["launcher"]["sha256"], fix.PACKAGE: sha}
        self.current_home = PROFILE["launcher"]["component"]
        self.events = []
        self.reject_install = False
        self.ignore_home = False
        self.other_profile = False

    def packages(self, *flags):
        return (
            self.installed
            | {"com.google.android.youtube.tv"}
            | (self.retained if "-u" in flags else set())
        )

    def activities(self, category, include_disabled=False):
        return {p + "/.Home" for p in self.packages()}

    def installed_digest(self, package):
        return self.hashes[package]

    def require_private_launcher(self, package):
        manage.require(not self.other_profile, "Installed for another user.")

    def home(self):
        return self.current_home

    def set_home(self, component):
        self.events.append(("home", component))
        if not self.ignore_home or not component.startswith(fix.PACKAGE + "/"):
            self.current_home = component

    def read_config(self):
        content = self.configs.get(self.config_package)
        return base64.b64encode(content).decode() if content is not None else None

    def write_config(self, content):
        self.events.append(("config", self.config_package))
        self.configs[self.config_package] = content

    def run(self, *args):
        self.events.append(tuple(args))
        if args[0] == "install":
            manage.require(not self.reject_install, "Install rejected.")
            self.installed.add(fix.PACKAGE)
        elif args[0] == "uninstall":
            self.installed.remove(args[1])
        else:
            raise AssertionError(args)
        return "Success"

    def shell(self, *args):
        if args == ("input", "keyevent", "KEYCODE_HOME"):
            return ""
        if args == ("dumpsys", "activity", "activities"):
            return "mResumedActivity " + self.current_home
        raise AssertionError(args)


class SettingsFixTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.apk = self.directory / "built.apk"
        self.apk.write_bytes(b"test patched APK")
        self.device = FakeDevice(manage.digest(self.apk))
        self.effective = json.loads(json.dumps(PROFILE))
        self.effective.pop("home_fallback", None)
        self.effective["launcher"].update(
            package=fix.PACKAGE,
            component=fix.PACKAGE + "/.Home",
            sha256=manage.digest(self.apk),
            local_artifact=str(self.apk),
        )
        self.original = {
            "schema": 2,
            "identity": IDENTITY,
            "launcher": PROFILE["launcher"],
            "home": "vendor/.Home",
            "installed_before": False,
            "config_before": None,
            "status": "applied",
        }
        manage.save(self.directory / "state.json", self.original)
        self.path = fix.state_path(self.directory)
        self.profile_patch = patch.object(fix, "patched_profile", return_value=self.effective)
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)

    def command(self, action):
        with contextlib.redirect_stdout(io.StringIO()):
            fix.command(action, self.device, PROFILE, IDENTITY, self.directory)

    def test_apply_reapply_and_restore_keep_original_installation_and_config(self):
        original_bytes = self.device.configs[fix.ORIGINAL]
        original_record = (self.directory / "state.json").read_bytes()
        self.command("settings-plan")
        self.assertEqual(self.device.events, [])
        self.assertFalse(self.path.exists())
        self.command("settings-apply")
        first = self.path.read_bytes()
        self.assertEqual(self.device.current_home, fix.PACKAGE + "/.Home")
        self.command("settings-apply")
        self.assertEqual(self.path.read_bytes(), first)
        self.command("settings-verify")
        self.command("settings-restore")
        self.assertEqual(self.device.installed, {fix.ORIGINAL})
        self.assertEqual(self.device.current_home, PROFILE["launcher"]["component"])
        self.assertEqual(self.device.configs[fix.ORIGINAL], original_bytes)
        self.assertEqual((self.directory / "state.json").read_bytes(), original_record)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.device.config_package, fix.ORIGINAL)

    def test_install_rejection_leaves_recoverable_pending_record(self):
        self.device.reject_install = True
        with self.assertRaisesRegex(RuntimeError, "Install rejected"):
            self.command("settings-apply")
        self.assertEqual(fix.load(self.path, IDENTITY)["status"], "pending")
        self.command("settings-restore")
        self.assertEqual(self.device.installed, {fix.ORIGINAL})
        self.assertEqual(fix.load(self.path, IDENTITY)["status"], "restored")

    def test_failed_home_verification_removes_only_introduced_copy(self):
        self.device.ignore_home = True
        with patch.object(manage.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "HOME still resolves"):
                self.command("settings-apply")
        self.assertEqual(self.device.installed, {fix.ORIGINAL})
        self.assertEqual(fix.load(self.path, IDENTITY)["status"], "restored")
        self.assertEqual(self.device.config_package, fix.ORIGINAL)

    def test_existing_or_retained_copy_and_other_user_are_refused(self):
        self.device.retained.add(fix.PACKAGE)
        with self.assertRaisesRegex(RuntimeError, "existing or retained"):
            self.command("settings-apply")
        self.device.retained.clear()
        self.device.other_profile = True
        with self.assertRaisesRegex(RuntimeError, "another user"):
            self.command("settings-apply")
        self.assertEqual(self.device.events, [])

    def test_changed_original_or_device_is_refused(self):
        self.device.hashes[fix.ORIGINAL] = "changed"
        with self.assertRaisesRegex(RuntimeError, "Original launcher APK changed"):
            self.command("settings-apply")
        self.assertEqual(self.device.events, [])
        self.device.hashes[fix.ORIGINAL] = PROFILE["launcher"]["sha256"]
        self.command("settings-apply")
        with self.assertRaisesRegex(RuntimeError, "Device or firmware differs"):
            fix.load(self.path, {**IDENTITY, "build": "changed"})

    def test_full_restore_returns_through_original_before_removing_it(self):
        self.command("settings-apply")
        self.device.events.clear()
        manage.restore(self.device, self.original, self.directory / "state.json")
        self.assertEqual(self.device.installed, set())
        self.assertLess(
            self.device.events.index(("home", PROFILE["launcher"]["component"])),
            self.device.events.index(("uninstall", fix.PACKAGE)),
        )
        self.assertLess(
            self.device.events.index(("uninstall", fix.PACKAGE)),
            self.device.events.index(("home", "vendor/.Home")),
        )

    def test_patch_blocks_underlying_launcher_mutation_until_restored(self):
        self.command("settings-apply")
        before = list(self.device.events)
        with self.assertRaisesRegex(RuntimeError, "settings-restore"):
            manage.apply(self.device, PROFILE, IDENTITY, b"", self.directory / "state.json")
        self.assertEqual(self.device.events, before)
        self.command("settings-restore")
        fix.require_inactive(self.directory, IDENTITY)

    def test_local_apk_tampering_is_refused_before_install(self):
        self.apk.write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "checksum differs"):
            self.command("settings-apply")
        self.assertEqual(self.device.events, [])
        self.assertFalse(self.path.exists())

    def test_source_patch_requires_exact_single_original_method(self):
        root = self.directory / "launcher"
        java = root / "src/tv/dumbtv/home/Home.java"
        java.parent.mkdir(parents=True)
        java.write_text("package tv.dumbtv.home;\n" + fix.OLD)
        fix.patch_source(root)
        self.assertIn(fix.NEW, java.read_text())
        self.assertNotIn("LEANBACK_SETTINGS", java.read_text())
        self.assertIn("package tv.homelab.home;", java.read_text())
        before = java.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "Pinned Settings method differs"):
            fix.patch_source(root)
        self.assertEqual(java.read_bytes(), before)

    def test_config_paths_follow_the_selected_package(self):
        device = object.__new__(manage.Device)
        self.assertEqual(device.config_path, manage.CONFIG)
        with fix.route(device):
            self.assertIn("/tv.homelab.home/", device.config_path)
        self.assertEqual(device.config_path, manage.CONFIG)

    def test_cached_build_does_not_regenerate_the_apk_or_signing_key(self):
        with patch.object(fix, "built_apk", return_value=self.apk), patch.object(fix, "run") as run:
            with contextlib.redirect_stdout(io.StringIO()):
                fix.build(None, None)
        run.assert_not_called()

    def test_shortcut_verification_follows_the_active_patched_launcher(self):
        import youtube_shortcut

        self.command("settings-apply")
        manage.save(
            self.directory / "youtube.json",
            {
                "schema": 1,
                "identity": IDENTITY,
                "package": youtube_shortcut.PACKAGE,
                "status": "applied",
            },
        )

        def verify(device, state, expected):
            self.assertEqual(device.config_package, fix.PACKAGE)
            self.assertIn(b"name.tv.homelab.youtube=YouTube", expected)
            hidden = next(line for line in expected.splitlines() if line.startswith(b"apps.hide="))
            self.assertIn(fix.ORIGINAL.encode(), hidden)

        with (
            patch("sys.argv", ["manage.py", "youtube-verify", "--state-dir", str(self.directory)]),
            patch.object(manage, "Device", return_value=self.device),
            patch.object(self.device, "identity", return_value=IDENTITY, create=True),
            patch.object(youtube_shortcut, "verify", side_effect=verify) as verified,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            manage.main()
        verified.assert_called_once()
        self.assertEqual(self.device.config_package, fix.ORIGINAL)


if __name__ == "__main__":
    unittest.main()
