import base64
import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import manage
import youtube_shortcut as shortcut

IDENTITY = {"serial": "test-device", "build": "test-build"}
PROFILE = json.loads((Path(__file__).parent / "profile.json").read_text())
ORIGINAL = b"# exact configuration\r\napps.order=com.google.android.youtube.tv\r\n"


class FakeDevice:
    def __init__(self, apk):
        self.installed = {shortcut.TARGET, "tv.dumbtv.home", "org.jellyfin.androidtv"}
        self.config = ORIGINAL
        self.retained = False
        self.other_user = False
        self.sha256 = manage.digest(apk)
        self.events = []
        self.fail_config = False
        self.interrupt_install = False
        self.current_home = "tv.dumbtv.home/.Home"

    def packages(self, *flags):
        return self.installed | ({shortcut.PACKAGE} if self.retained and "-u" in flags else set())

    def activities(self, category, include_disabled=False):
        return {package + "/.Activity" for package in self.installed}

    def require_private_launcher(self, package):
        manage.require(not self.other_user, "Another user installed the shortcut.")

    def home(self):
        return self.current_home

    def set_home(self, component):
        self.events.append(("home", component))
        self.current_home = component

    def installed_digest(self, package):
        if package == "tv.dumbtv.home":
            return PROFILE["launcher"]["sha256"]
        return self.sha256

    def shell(self, *args):
        if args[:2] == ("input", "keyevent"):
            return ""
        raise AssertionError(args)

    def read_config(self):
        return base64.b64encode(self.config).decode() if self.config is not None else None

    def write_config(self, content):
        if self.fail_config:
            self.fail_config = False
            raise RuntimeError("Configuration push failed")
        self.events.append(("config", content))
        self.config = content

    def run(self, *args):
        self.events.append(args)
        if args[0] == "install":
            self.installed.add(shortcut.PACKAGE)
            if self.interrupt_install:
                raise KeyboardInterrupt
        elif args[0] == "uninstall":
            self.installed.remove(args[1])
        else:
            raise AssertionError(args)
        return "Success"


class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "youtube.json"
        self.apk = self.path.with_name("shortcut.apk")
        self.apk.write_bytes(b"test apk")
        self.device = FakeDevice(self.apk)

    def apply(self):
        with contextlib.redirect_stdout(io.StringIO()):
            shortcut.apply(self.device, PROFILE, IDENTITY, self.path, self.apk)

    def restore(self):
        shortcut.restore(self.device, shortcut.load(self.path, IDENTITY), self.path)

    def test_round_trip_restores_exact_config_and_only_removes_introduced_app(self):
        before = set(self.device.installed)
        self.apply()
        self.assertIn(b"apps.order=tv.homelab.youtube,", self.device.config)
        self.assertIn(shortcut.TARGET, self.device.installed)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.restore()
        self.assertEqual(self.device.installed, before)
        self.assertEqual(self.device.config, ORIGINAL)
        self.assertEqual(
            self.device.events[-2:], [("config", ORIGINAL), ("uninstall", shortcut.PACKAGE)]
        )

    def test_reapply_preserves_first_baseline(self):
        self.apply()
        before = self.path.read_bytes()
        self.apply()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sum(e[0] == "install" for e in self.device.events), 1)

    def test_config_failure_rolls_back_app_and_configuration(self):
        self.device.fail_config = True
        with self.assertRaisesRegex(RuntimeError, "Configuration push failed"):
            self.apply()
        self.assertNotIn(shortcut.PACKAGE, self.device.installed)
        self.assertEqual(self.device.config, ORIGINAL)
        self.assertEqual(shortcut.load(self.path, IDENTITY)["status"], "restored")

    def test_interrupted_install_rolls_back_even_if_package_was_created(self):
        self.device.interrupt_install = True
        with self.assertRaises(KeyboardInterrupt):
            self.apply()
        self.assertNotIn(shortcut.PACKAGE, self.device.installed)
        self.assertEqual(self.device.config, ORIGINAL)

    def test_existing_and_retained_packages_are_refused(self):
        for installed in (True, False):
            with self.subTest(installed=installed):
                self.device.retained = not installed
                if installed:
                    self.device.installed.add(shortcut.PACKAGE)
                else:
                    self.device.installed.discard(shortcut.PACKAGE)
                with self.assertRaisesRegex(RuntimeError, "existing or retained"):
                    self.apply()
                self.assertFalse(self.path.exists())
                self.assertEqual(self.device.events, [])

    def test_changed_apk_refused_on_apply_and_restore_before_mutations(self):
        self.apply()
        self.device.sha256 = "external update"
        before = list(self.device.events)
        for action in (self.apply, self.restore):
            with self.assertRaisesRegex(RuntimeError, "changed outside"):
                action()
        self.assertEqual(self.device.events, before)

    def test_other_user_refuses_restore_without_changing_config(self):
        self.apply()
        self.device.other_user = True
        before = list(self.device.events)
        with self.assertRaisesRegex(RuntimeError, "Another user"):
            self.restore()
        self.assertEqual(self.device.events, before)

    def test_changed_launcher_refuses_tile_restoration_before_mutations(self):
        self.apply()
        before = list(self.device.events)
        with patch.object(
            self.device,
            "installed_digest",
            side_effect=lambda package: (
                self.device.sha256 if package == shortcut.PACKAGE else "external launcher update"
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Launcher APK changed"):
                self.restore()
        self.assertEqual(self.device.events, before)

    def test_build_update_requires_restoration(self):
        self.apply()
        self.apk.write_bytes(b"new version")
        before = list(self.device.events)
        with self.assertRaisesRegex(RuntimeError, "before updating"):
            self.apply()
        self.assertEqual(self.device.events, before)

    def test_different_device_refused(self):
        self.apply()
        with self.assertRaisesRegex(RuntimeError, "Device or firmware"):
            shortcut.load(self.path, {**IDENTITY, "serial": "another-device"})

    def test_pending_or_restored_transaction_cannot_be_reapplied(self):
        self.apply()
        for status in ("pending", "restored"):
            state = shortcut.load(self.path, IDENTITY)
            state["status"] = status
            manage.save(self.path, state)
            before = list(self.device.events)
            with self.assertRaisesRegex(RuntimeError, "previous shortcut transaction"):
                self.apply()
            self.assertEqual(self.device.events, before)

    def test_missing_youtube_refused(self):
        self.device.installed.remove(shortcut.TARGET)
        with self.assertRaisesRegex(RuntimeError, "enable YouTube"):
            self.apply()
        self.assertEqual(self.device.events, [])

    def test_full_restore_restores_home_then_shortcut_before_removing_launcher(self):
        self.apply()
        launcher_path = self.path.with_name("state.json")
        state = {
            "identity": IDENTITY,
            "launcher": PROFILE["launcher"],
            "home": "vendor/.Home",
            "installed_before": False,
        }
        manage.restore(self.device, state, launcher_path)
        events = self.device.events
        self.assertLess(
            events.index(("home", "vendor/.Home")), events.index(("uninstall", shortcut.PACKAGE))
        )
        self.assertLess(
            events.index(("uninstall", shortcut.PACKAGE)),
            events.index(("uninstall", "tv.dumbtv.home")),
        )
        self.assertEqual(shortcut.load(self.path, IDENTITY)["status"], "restored")

    def test_full_restore_keeps_functional_shortcut_if_original_home_fails(self):
        self.apply()
        state = {"identity": IDENTITY, "launcher": PROFILE["launcher"], "home": "vendor/.Home"}
        with patch.object(self.device, "set_home"):
            with self.assertRaisesRegex(RuntimeError, "Original HOME did not restore"):
                manage.restore(self.device, state, self.path.with_name("state.json"))
        self.assertIn(shortcut.PACKAGE, self.device.installed)
        self.assertEqual(shortcut.load(self.path, IDENTITY)["status"], "applied")

    def test_full_restore_removes_helper_if_introduced_launcher_is_already_absent(self):
        self.apply()
        self.device.installed.remove("tv.dumbtv.home")
        before = list(self.device.events)
        state = {
            "identity": IDENTITY,
            "launcher": PROFILE["launcher"],
            "home": "vendor/.Home",
            "installed_before": False,
        }
        manage.restore(self.device, state, self.path.with_name("state.json"))
        self.assertNotIn(shortcut.PACKAGE, self.device.installed)
        self.assertFalse(any(e[0] == "config" for e in self.device.events[len(before) :]))

    def test_artifact_tampering_is_rejected(self):
        directory = self.path.parent
        apk = directory / "youtube.apk"
        apk.write_bytes(b"original")
        manage.save(directory / "artifact.json", {"source": "source", "sha256": manage.digest(apk)})
        with (
            patch.object(shortcut, "cache", return_value=directory),
            patch.object(shortcut, "source_digest", return_value="source"),
        ):
            self.assertEqual(shortcut.artifact(), apk)
            apk.write_bytes(b"tampered")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                shortcut.artifact()

    def test_artwork_copies_only_the_original_pngs_without_retaining_the_apk(self):
        directory = self.path.parent / "cache"
        directory.mkdir()
        banner = b"\x89PNG\r\n\x1a\noriginal banner"
        icon = b"\x89PNG\r\n\x1a\noriginal icon"

        def pull(*args):
            with zipfile.ZipFile(args[2], "w") as apk:
                apk.writestr("res/banner.png", banner)
                apk.writestr("res/icon.png", icon)
                apk.writestr("unneeded", b"not copied")

        badging = (
            f"package: name='{shortcut.TARGET}'\n"
            "application-icon-320:'res/icon.png'\n"
            "application: label='YouTube' icon='res/icon.png' banner='res/banner.png'\n"
        )
        with (
            patch.object(shortcut, "cache", return_value=directory),
            patch.object(shortcut, "run", return_value=badging),
            patch.object(self.device, "shell", return_value="package:/app/base.apk"),
            patch.object(self.device, "run", side_effect=pull),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            shortcut.artwork(self.device, Path("/sdk"))
        self.assertEqual((directory / "artwork/banner.png").read_bytes(), banner)
        self.assertEqual((directory / "artwork/icon.png").read_bytes(), icon)
        self.assertEqual(
            {p.name for p in directory.rglob("*") if p.is_file()}, {"banner.png", "icon.png"}
        )


if __name__ == "__main__":
    unittest.main()
