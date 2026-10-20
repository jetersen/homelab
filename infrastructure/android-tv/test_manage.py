import base64
import contextlib
import io
import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manage

PROFILE = json.loads((Path(__file__).parent / "profile.json").read_text())
PROFILE.pop("home_fallback", None)
PACKAGE = PROFILE["launcher"]["package"]
IDENTITY = {"serial": "test-device", "build": "test-build"}
ORIGINAL_HOME = "example.vendor/.Home"
CONTENT = b"accent=violet\n"


class FakeDevice:
    def __init__(self, installed=False):
        self.installed = installed
        self.config = b"# exact original bytes\r\naccent=cyan\r\n" if installed else None
        self.current_home = ORIGINAL_HOME
        self.sha256 = PROFILE["launcher"]["sha256"]
        self.ignore_home_change = False
        self.interrupt_install = False
        self.fail_config_write = False
        self.events = []
        self.unrelated_packages = {"example.vendor", "example.player"}
        self.other_user_launcher = False
        self.enabled_state = "enabled"
        self.ignore_disabled_home_change = False
        self.secondary_states = {}

    def package_state(self, package):
        if package == ORIGINAL_HOME.split("/")[0]:
            return self.enabled_state
        return self.secondary_states[package]

    def set_package_state(self, package, state):
        self.events.append(("package", package, state))
        if package == ORIGINAL_HOME.split("/")[0]:
            self.enabled_state = state
        else:
            self.secondary_states[package] = state

    def activities(self, category, include_disabled=False):
        return {ORIGINAL_HOME}

    def require_private_launcher(self, package):
        manage.require(not self.other_user_launcher, "dumbtv is installed for another user")

    def packages(self, *flags):
        return self.unrelated_packages | ({PACKAGE} if self.installed else set())

    def home(self):
        return self.current_home

    def set_home(self, component):
        self.events.append(("home", component))
        if (
            not self.ignore_home_change
            or component == ORIGINAL_HOME
            or (self.enabled_state == "disabled-user" and not self.ignore_disabled_home_change)
        ):
            self.current_home = component

    def installed_digest(self, package):
        manage.require(self.installed, "Launcher missing")
        return self.sha256

    def read_config(self):
        return base64.b64encode(self.config).decode() if self.config is not None else None

    def write_config(self, content):
        if self.fail_config_write:
            self.fail_config_write = False
            raise RuntimeError("Failed to write configuration")
        self.config = content

    def run(self, *args):
        self.events.append(args)
        if args[0] == "install":
            self.installed = True
            if self.interrupt_install:
                raise KeyboardInterrupt
        elif args[0] == "uninstall":
            self.installed = False
            self.config = None
        else:
            raise AssertionError(args)
        return "Success"

    def shell(self, *args):
        if args[:3] == ("dumpsys", "activity", "activities"):
            return f"mResumedActivity: ActivityRecord{{u0 {self.current_home}}}"
        if args[0] == "settings":
            return "1"
        if args[:2] == ("input", "keyevent"):
            return ""
        raise AssertionError(args)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "state.json"
        self.artifact = patch("manage.artifact", return_value=Path("verified.apk"))
        self.artifact.start()
        self.addCleanup(self.artifact.stop)
        sleep = patch("manage.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def apply(self, device, content=CONTENT):
        with contextlib.redirect_stdout(io.StringIO()):
            manage.apply(device, PROFILE, IDENTITY, content, self.path)

    def restore(self, device):
        manage.restore(device, json.loads(self.path.read_text()), self.path)

    def test_new_install_round_trip_preserves_other_apps(self):
        device = FakeDevice()
        self.apply(device)
        self.assertTrue(device.installed)
        self.assertEqual(device.config, CONTENT)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.restore(device)
        self.assertEqual(device.current_home, ORIGINAL_HOME)
        self.assertFalse(device.installed)
        self.assertEqual(device.unrelated_packages, {"example.vendor", "example.player"})
        self.assertLess(
            device.events.index(("home", ORIGINAL_HOME)),
            device.events.index(("uninstall", PACKAGE)),
        )

    def test_reapply_keeps_first_baseline_and_restores_exact_bytes(self):
        device = FakeDevice(installed=True)
        original = device.config
        self.apply(device)
        self.apply(device, b"accent=green\n")
        self.restore(device)
        self.assertTrue(device.installed)
        self.assertEqual(device.config, original)
        self.assertEqual(device.current_home, ORIGINAL_HOME)
        self.assertFalse(any(event[0] in {"install", "uninstall"} for event in device.events))

    def test_restores_configuration_absence(self):
        device = FakeDevice(installed=True)
        device.config = None
        self.apply(device)
        self.restore(device)
        self.assertIsNone(device.config)

    def test_ignored_home_preference_rolls_back_new_install(self):
        device = FakeDevice()
        device.ignore_home_change = True
        with self.assertRaisesRegex(RuntimeError, "HOME still resolves"):
            self.apply(device)
        self.assertEqual(device.current_home, ORIGINAL_HOME)
        self.assertFalse(device.installed)
        self.assertEqual(json.loads(self.path.read_text())["status"], "restored")

    def test_waits_for_home_preference_to_settle(self):
        device = FakeDevice()
        self.apply(device)
        with patch.object(
            device, "home", side_effect=[ORIGINAL_HOME, PROFILE["launcher"]["component"]]
        ):
            manage.verify(device, PROFILE, CONTENT)

    def test_package_fallback_round_trip_restores_exact_state_before_home(self):
        for original_state in ["enabled", "default"]:
            with self.subTest(original_state=original_state):
                path = self.path.with_name(original_state + ".json")
                device = FakeDevice()
                device.enabled_state = original_state
                device.ignore_home_change = True
                profile = {
                    **PROFILE,
                    "home_fallback": {"disable_packages": [ORIGINAL_HOME.split("/")[0]]},
                }
                manage.apply(device, profile, IDENTITY, CONTENT, path)
                self.assertEqual(device.enabled_state, "disabled-user")
                self.assertEqual(device.current_home, PROFILE["launcher"]["component"])
                manage.apply(device, profile, IDENTITY, CONTENT, path)
                manage.restore(device, json.loads(path.read_text()), path)
                self.assertEqual(device.enabled_state, original_state)
                self.assertFalse(device.installed)
                self.assertLess(
                    device.events.index(("package", ORIGINAL_HOME.split("/")[0], original_state)),
                    device.events.index(("home", ORIGINAL_HOME)),
                )

    def test_failed_package_fallback_restores_launcher_and_package(self):
        device = FakeDevice()
        device.ignore_home_change = True
        device.ignore_disabled_home_change = True
        profile = {**PROFILE, "home_fallback": {"disable_packages": [ORIGINAL_HOME.split("/")[0]]}}
        with self.assertRaisesRegex(RuntimeError, "HOME still resolves"):
            manage.apply(device, profile, IDENTITY, CONTENT, self.path)
        self.assertEqual(device.enabled_state, "enabled")
        self.assertEqual(device.current_home, ORIGINAL_HOME)
        self.assertFalse(device.installed)

    def test_refused_package_disable_still_restores_without_rewriting_original_state(self):
        device = FakeDevice()
        device.ignore_home_change = True
        profile = {**PROFILE, "home_fallback": {"disable_packages": [ORIGINAL_HOME.split("/")[0]]}}
        with patch.object(
            device, "set_package_state", side_effect=RuntimeError("Package change refused")
        ) as change:
            with self.assertRaisesRegex(RuntimeError, "Package change refused"):
                manage.apply(device, profile, IDENTITY, CONTENT, self.path)
            change.assert_called_once()
        self.assertEqual(device.current_home, ORIGINAL_HOME)
        self.assertFalse(device.installed)
        self.assertEqual(json.loads(self.path.read_text())["status"], "restored")

    def test_package_fallback_refuses_unexpected_original_home(self):
        device = FakeDevice()
        profile = {**PROFILE, "home_fallback": {"disable_packages": ["other.vendor"]}}
        with self.assertRaisesRegex(RuntimeError, "include the original HOME"):
            manage.apply(device, profile, IDENTITY, CONTENT, self.path)
        self.assertEqual(device.events, [])
        self.assertFalse(self.path.exists())

    def test_reapply_requires_restoration_before_changing_home_fallback(self):
        device = FakeDevice()
        self.apply(device)
        profile = {**PROFILE, "home_fallback": {"disable_packages": [ORIGINAL_HOME.split("/")[0]]}}
        previous_events = list(device.events)
        with self.assertRaisesRegex(RuntimeError, "Restore before changing the HOME fallback"):
            manage.apply(device, profile, IDENTITY, CONTENT, self.path)
        self.assertEqual(device.events, previous_events)

    def test_multiple_home_handlers_restore_each_original_state(self):
        device = FakeDevice()
        device.ignore_home_change = True
        device.secondary_states["example.recovery"] = "default"
        profile = {
            **PROFILE,
            "home_fallback": {"disable_packages": ["example.vendor", "example.recovery"]},
        }
        with patch.object(
            device, "activities", return_value={ORIGINAL_HOME, "example.recovery/.Home"}
        ):
            manage.apply(device, profile, IDENTITY, CONTENT, self.path)
        self.assertEqual(device.secondary_states["example.recovery"], "disabled-user")
        self.restore(device)
        self.assertEqual(device.enabled_state, "enabled")
        self.assertEqual(device.secondary_states["example.recovery"], "default")

    def test_partial_fallback_failure_restores_already_disabled_package(self):
        device = FakeDevice()
        device.ignore_home_change = True
        device.secondary_states["example.recovery"] = "default"
        profile = {
            **PROFILE,
            "home_fallback": {"disable_packages": ["example.vendor", "example.recovery"]},
        }
        change = device.set_package_state

        def fail_second(package, state):
            if package == "example.recovery":
                raise RuntimeError("Recovery package change refused")
            change(package, state)

        with (
            patch.object(
                device, "activities", return_value={ORIGINAL_HOME, "example.recovery/.Home"}
            ),
            patch.object(device, "set_package_state", side_effect=fail_second),
        ):
            with self.assertRaisesRegex(RuntimeError, "Recovery package change refused"):
                manage.apply(device, profile, IDENTITY, CONTENT, self.path)
        self.assertEqual(device.enabled_state, "enabled")
        self.assertEqual(device.secondary_states["example.recovery"], "default")
        self.assertFalse(device.installed)

    def test_fallback_requires_completed_setup(self):
        device = FakeDevice()
        profile = {**PROFILE, "home_fallback": {"disable_packages": ["example.vendor"]}}
        with patch.object(device, "shell", return_value="0"):
            with self.assertRaisesRegex(RuntimeError, "Complete TV setup"):
                manage.apply(device, profile, IDENTITY, CONTENT, self.path)
        self.assertEqual(device.events, [])

    def test_fallback_refuses_packages_without_home_handler(self):
        device = FakeDevice()
        profile = {
            **PROFILE,
            "home_fallback": {"disable_packages": ["example.vendor", "example.unrelated"]},
        }
        with self.assertRaisesRegex(RuntimeError, "without a HOME handler"):
            manage.apply(device, profile, IDENTITY, CONTENT, self.path)
        self.assertEqual(device.events, [])

    def test_failed_config_push_rolls_back_existing_config(self):
        device = FakeDevice(installed=True)
        original = device.config
        device.fail_config_write = True
        with self.assertRaisesRegex(RuntimeError, "Failed to write"):
            self.apply(device)
        self.assertEqual(device.config, original)
        self.assertEqual(device.current_home, ORIGINAL_HOME)

    def test_interrupted_install_is_recoverable_and_blocks_reapply(self):
        device = FakeDevice()
        device.interrupt_install = True
        with self.assertRaises(KeyboardInterrupt):
            self.apply(device)
        self.assertEqual(json.loads(self.path.read_text())["status"], "pending")
        with self.assertRaisesRegex(RuntimeError, "interrupted apply"):
            self.apply(device)
        self.restore(device)
        self.assertFalse(device.installed)

    def test_refuses_existing_apk_update_before_any_mutation(self):
        device = FakeDevice(installed=True)
        device.sha256 = "different"
        with self.assertRaisesRegex(RuntimeError, "Existing dumbtv APK differs"):
            self.apply(device)
        self.assertEqual(device.events, [])
        self.assertFalse(self.path.exists())

    def test_refuses_launcher_shared_with_another_user_before_mutation(self):
        device = FakeDevice()
        device.other_user_launcher = True
        with self.assertRaisesRegex(RuntimeError, "another user"):
            self.apply(device)
        self.assertEqual(device.events, [])
        self.assertFalse(self.path.exists())

    def test_restore_keeps_launcher_if_another_user_installed_it(self):
        device = FakeDevice()
        self.apply(device)
        device.other_user_launcher = True
        with self.assertRaisesRegex(RuntimeError, "another user"):
            self.restore(device)
        self.assertEqual(device.current_home, ORIGINAL_HOME)
        self.assertTrue(device.installed)
        self.assertFalse(any(event[0] == "uninstall" for event in device.events))

    def test_restore_external_upgrade_keeps_app_and_restores_home(self):
        device = FakeDevice()
        self.apply(device)
        device.sha256 = "external-update"
        with self.assertRaisesRegex(RuntimeError, "changed outside"):
            self.restore(device)
        self.assertEqual(device.current_home, ORIGINAL_HOME)
        self.assertTrue(device.installed)
        self.assertEqual(json.loads(self.path.read_text())["status"], "applied")

    def test_refuses_baseline_from_different_device(self):
        device = FakeDevice()
        self.apply(device)
        state = json.loads(self.path.read_text())
        state["identity"]["serial"] = "different-device"
        manage.save(self.path, state)
        previous_events = list(device.events)
        with self.assertRaisesRegex(RuntimeError, "Device or firmware differs"):
            self.apply(device)
        self.assertEqual(device.events, previous_events)

    def test_restored_record_cannot_be_overwritten(self):
        device = FakeDevice()
        self.apply(device)
        self.restore(device)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "Archive the restored"):
            self.apply(device)
        self.assertEqual(self.path.read_bytes(), before)


class DeviceTests(unittest.TestCase):
    def test_package_state_change_targets_only_user_zero(self):
        device = object.__new__(manage.Device)
        with (
            patch.object(device, "shell") as shell,
            patch.object(device, "package_state", return_value="disabled-user"),
        ):
            device.set_package_state("example.vendor", "disabled-user")
            shell.assert_called_once_with("pm", "disable-user", "--user", "0", "example.vendor")

    def test_package_state_uses_active_package_and_user_zero(self):
        device = object.__new__(manage.Device)
        for number, state in enumerate(manage.ENABLED_STATES):
            with self.subTest(state=state):
                dump = (
                    "Packages:\n  Package [example.vendor] (hash):\n"
                    f"    User 0: installed=true enabled={number}\n"
                    "    User 10: installed=true enabled=1\n"
                    "Hidden system packages:\n  Package [example.vendor] (old):\n"
                    "    User 0: installed=true enabled=2\n"
                )
                with patch.object(device, "shell", return_value=dump):
                    self.assertEqual(device.package_state("example.vendor"), state)

    def test_package_state_refuses_unknown_output(self):
        device = object.__new__(manage.Device)
        for dump in ["", "Packages:\n  Package [example.vendor]:\n    User 0: installed=true\n"]:
            with patch.object(device, "shell", return_value=dump):
                with self.assertRaises(RuntimeError):
                    device.package_state("example.vendor")

    def test_install_failure_reports_code_without_raw_device_output(self):
        device = object.__new__(manage.Device)
        device.command = ["adb", "-s", "test-device"]
        with patch(
            "manage.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [],
                1,
                stdout=b"private device output",
                stderr=b"Failure [INSTALL_FAILED_VERIFICATION_FAILURE: private details]",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "^ADB operation failed ") as error:
                device.run("install", "verified.apk")
        self.assertEqual(
            str(error.exception),
            "ADB operation failed (install): INSTALL_FAILED_VERIFICATION_FAILURE.",
        )

    def test_other_users_checked_without_selecting_them(self):
        device = object.__new__(manage.Device)
        with (
            patch.object(device, "users", return_value=["0", "10"]),
            patch.object(device, "packages", return_value=set()) as packages,
        ):
            device.require_private_launcher(PACKAGE)
            packages.assert_called_once_with(user="10")
        with (
            patch.object(device, "users", return_value=["0", "10"]),
            patch.object(device, "packages", return_value={PACKAGE}),
        ):
            with self.assertRaisesRegex(RuntimeError, "another user"):
                device.require_private_launcher(PACKAGE)

    def test_retained_uninstalled_package_is_refused(self):
        device = FakeDevice()
        original_packages = device.packages
        device.packages = lambda *flags: (
            original_packages() | ({PACKAGE} if "-u" in flags else set())
        )
        with self.assertRaisesRegex(RuntimeError, "retained package state"):
            manage.baseline(device, PROFILE, IDENTITY)
        self.assertEqual(device.events, [])

    def test_remote_arguments_are_shell_quoted(self):
        device = object.__new__(manage.Device)
        device.command = ["adb", "-s", "test-device"]
        arguments = ("settings", "put", "global", "test", "a b; $(command)")
        with patch(
            "manage.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=b"", stderr=b""),
        ) as run:
            device.shell(*arguments)
        remote = run.call_args.args[0][-1]
        self.assertEqual(shlex.split(remote), list(arguments))

    def test_unauthorized_device_is_refused(self):
        with patch.object(
            manage.Device, "run", return_value="List of devices attached\ntest-device\tunauthorized"
        ):
            with self.assertRaisesRegex(RuntimeError, "Accept the debugging"):
                manage.Device("adb")

    def test_multiple_devices_require_selector(self):
        with patch.object(
            manage.Device,
            "run",
            return_value="List of devices attached\nfirst\tdevice\nsecond\tdevice",
        ):
            with self.assertRaisesRegex(RuntimeError, "exactly one TV"):
                manage.Device("adb")
            self.assertEqual(manage.Device("adb", "second").command, ["adb", "-s", "second"])

    def test_profile_hides_tiles_without_removing_packages(self):
        apps = {"com.google.android.youtube.tv", "example.unwanted", "org.jellyfin.androidtv"}
        content, missing = manage.render(PROFILE, apps)
        values = dict(line.split("=", 1) for line in content.decode().splitlines())
        self.assertEqual(
            values["apps.order"], "com.google.android.youtube.tv,org.jellyfin.androidtv"
        )
        self.assertEqual(values["apps.hide"], "example.unwanted")
        self.assertEqual(missing, ["Proton VPN"])
        self.assertEqual(
            apps, {"com.google.android.youtube.tv", "example.unwanted", "org.jellyfin.androidtv"}
        )


if __name__ == "__main__":
    unittest.main()
