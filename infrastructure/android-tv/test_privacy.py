import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manage
import privacy

IDENTITY = {"serial": "test-device", "build": "test-build"}
POLICY = {
    "disable_packages": ["example.tracking", "example.voice", "example.absent"],
    "settings": [{"namespace": "global", "key": "send_action_app_error", "value": "0"}],
    "microphone_blocked": True,
}


class FakeDevice:
    def __init__(self):
        self.states = {"example.tracking": "default", "example.voice": "enabled"}
        self.setting = None
        self.blocked = False
        self.changes = []

    def packages(self):
        return set(self.states)

    def activities(self, category, include_disabled=False):
        return {"example.home/.Home"}

    def package_state(self, package):
        return self.states[package]

    def set_package_state(self, package, state):
        self.changes.append((package, state))
        self.states[package] = state

    def read_setting(self, namespace, key):
        return self.setting

    def write_setting(self, namespace, key, value):
        self.changes.append((key, value))
        self.setting = value

    def microphone_blocked(self):
        return self.blocked

    def set_microphone_blocked(self, blocked):
        self.changes.append(("microphone", blocked))
        self.blocked = blocked


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "privacy.json"
        self.device = FakeDevice()

    def apply(self, policy=POLICY):
        with contextlib.redirect_stdout(io.StringIO()):
            privacy.apply(self.device, policy, IDENTITY, self.path)

    def restore(self):
        privacy.restore(self.device, privacy.load(self.path, IDENTITY), self.path)

    def test_round_trip_preserves_exact_states_and_setting_absence(self):
        before = dict(self.device.states)
        self.apply()
        self.assertEqual(set(self.device.states.values()), {"disabled-user"})
        self.assertTrue(self.device.blocked)
        self.assertEqual(self.device.setting, "0")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.restore()
        self.assertEqual(self.device.states, before)
        self.assertIsNone(self.device.setting)
        self.assertFalse(self.device.blocked)

    def test_reapply_keeps_original_baseline(self):
        self.device.setting = "1"
        self.device.blocked = True
        self.apply()
        before = privacy.load(self.path, IDENTITY)
        self.apply()
        self.assertEqual(privacy.load(self.path, IDENTITY), before)
        self.restore()
        self.assertEqual(self.device.setting, "1")
        self.assertTrue(self.device.blocked)

    def test_partial_apply_failure_restores_prior_changes(self):
        original = self.device.set_package_state

        def change(package, state):
            if package == "example.voice" and state == "disabled-user":
                raise RuntimeError("change refused")
            original(package, state)

        with patch.object(self.device, "set_package_state", side_effect=change):
            with self.assertRaisesRegex(RuntimeError, "change refused"):
                self.apply()
        self.assertEqual(self.device.states["example.tracking"], "default")
        self.assertEqual(privacy.load(self.path, IDENTITY)["status"], "restored")

    def test_mic_failure_restores_packages_and_setting(self):
        original = self.device.set_microphone_blocked

        def change(blocked):
            if blocked:
                raise RuntimeError("microphone refused")
            original(blocked)

        with patch.object(self.device, "set_microphone_blocked", side_effect=change):
            with self.assertRaisesRegex(RuntimeError, "microphone refused"):
                self.apply()
        self.assertEqual(self.device.states["example.tracking"], "default")
        self.assertIsNone(self.device.setting)

    def test_pending_record_blocks_reapply(self):
        state = privacy.capture(self.device, POLICY, IDENTITY)
        manage.save(self.path, state)
        with self.assertRaisesRegex(RuntimeError, "previous privacy transaction"):
            self.apply()
        self.assertEqual(self.device.changes, [])

    def test_pending_privacy_record_blocks_launcher_mutation(self):
        manage.save(self.path, privacy.capture(self.device, POLICY, IDENTITY))
        with self.assertRaisesRegex(RuntimeError, "interrupted privacy transaction"):
            manage.apply(self.device, {}, IDENTITY, b"", self.path.with_name("state.json"))
        self.assertEqual(self.device.changes, [])

    def test_changed_policy_or_device_blocks_reapply(self):
        self.apply()
        changes = list(self.device.changes)
        with self.assertRaisesRegex(RuntimeError, "changing its profile"):
            self.apply({**POLICY, "microphone_blocked": False})
        state = privacy.load(self.path, IDENTITY)
        state["identity"] = {**IDENTITY, "serial": "different"}
        manage.save(self.path, state)
        with self.assertRaisesRegex(RuntimeError, "Device or firmware differs"):
            self.apply()
        self.assertEqual(self.device.changes, changes)

    def test_protected_or_home_package_refused_before_mutation(self):
        for package in ["com.google.android.apps.mediashell", "example.home"]:
            with self.subTest(package=package):
                with self.assertRaisesRegex(RuntimeError, "protected"):
                    self.apply({**POLICY, "disable_packages": [package]})
        self.assertEqual(self.device.changes, [])

    def test_unknown_setting_refused(self):
        policy = {**POLICY, "settings": [{"namespace": "global", "key": "guess", "value": "0"}]}
        with self.assertRaisesRegex(RuntimeError, "Unsupported privacy setting"):
            self.apply(policy)
        self.assertEqual(self.device.changes, [])

    def test_new_install_of_previously_absent_app_requires_review(self):
        self.apply()
        self.device.states["example.absent"] = "default"
        with self.assertRaisesRegex(RuntimeError, "previously absent"):
            privacy.verify(self.device, privacy.load(self.path, IDENTITY))

    def test_full_restore_includes_privacy_before_launcher(self):
        self.apply()
        launcher_path = self.path.with_name("state.json")
        state = {
            "identity": IDENTITY,
            "launcher": {"package": "example.launcher"},
            "home": "home/.Home",
        }

        def set_home(component):
            self.assertEqual(privacy.load(self.path, IDENTITY)["status"], "restored")
            raise RuntimeError("stop after checking ordering")

        with patch.object(self.device, "set_home", side_effect=set_home, create=True):
            with self.assertRaisesRegex(RuntimeError, "checking ordering"):
                manage.restore(self.device, state, launcher_path)


class PhilipsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "philips.json"
        self.device = FakeDevice()
        self.device.states.update(
            {"example.gallery": "default", "example.demo": "disabled-until-used"}
        )
        self.policy = {"disable_packages": ["example.gallery", "example.demo"]}
        self.profile = {"philips": self.policy, "privacy": POLICY}

    def command(self, action):
        with contextlib.redirect_stdout(io.StringIO()):
            privacy.command(action, self.device, self.profile, IDENTITY, self.directory)

    def test_plan_is_read_only_and_does_not_touch_privacy_controls(self):
        self.command("philips-plan")
        self.assertEqual(self.device.changes, [])
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_independent_restore_preserves_privacy_and_exact_original_states(self):
        self.command("privacy-apply")
        privacy_path = self.directory / "privacy.json"
        privacy_before = privacy_path.read_bytes()
        self.command("philips-apply")
        baseline = self.path.read_bytes()
        self.command("philips-apply")
        self.assertEqual(self.path.read_bytes(), baseline)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.command("philips-verify")
        self.command("philips-restore")
        self.assertEqual(self.device.states["example.gallery"], "default")
        self.assertEqual(self.device.states["example.demo"], "disabled-until-used")
        self.assertEqual(privacy_path.read_bytes(), privacy_before)
        privacy.verify(self.device, privacy.load(privacy_path, IDENTITY))

    def test_full_restore_restores_both_controls_before_home(self):
        self.command("privacy-apply")
        self.command("philips-apply")
        state = {
            "identity": IDENTITY,
            "launcher": {"package": "example.launcher"},
            "home": "example.home/.Home",
        }

        def set_home(component):
            for scope in privacy.SCOPES:
                self.assertEqual(
                    privacy.load(self.directory / f"{scope}.json", IDENTITY)["status"],
                    "restored",
                )
            raise RuntimeError("checked both controls before HOME")

        with patch.object(self.device, "set_home", side_effect=set_home, create=True):
            with self.assertRaisesRegex(RuntimeError, "checked both"):
                manage.restore(self.device, state, self.directory / "state.json")

    def test_failed_disable_restores_optional_apps_without_touching_privacy(self):
        self.command("privacy-apply")
        before = dict(self.device.states)
        original = self.device.set_package_state

        def change(package, state):
            if package == "example.demo" and state == "disabled-user":
                raise RuntimeError("disable refused")
            original(package, state)

        with patch.object(self.device, "set_package_state", side_effect=change):
            with self.assertRaisesRegex(RuntimeError, "disable refused"):
                self.command("philips-apply")
        self.assertEqual(self.device.states, before)
        self.assertEqual(privacy.load(self.path, IDENTITY)["status"], "restored")
        self.assertTrue(self.device.blocked)
        self.assertEqual(self.device.setting, "0")

    def test_pending_peer_blocks_both_control_scopes_and_launcher(self):
        for scope in privacy.SCOPES:
            with self.subTest(scope=scope):
                path = self.directory / f"{scope}.json"
                manage.save(path, privacy.capture(self.device, self.profile[scope], IDENTITY))
                peer = next(s for s in privacy.SCOPES if s != scope)
                for action in (f"{peer}-plan", f"{peer}-apply"):
                    with self.assertRaisesRegex(RuntimeError, f"interrupted {scope}"):
                        self.command(action)
                with self.assertRaisesRegex(RuntimeError, f"interrupted {scope}"):
                    manage.apply(self.device, {}, IDENTITY, b"", self.directory / "state.json")
                path.unlink()
        self.assertEqual(self.device.changes, [])

    def test_overlap_including_absent_packages_cannot_own_two_baselines(self):
        self.command("privacy-apply")
        before = list(self.device.changes)
        for package in ("example.tracking", "example.absent"):
            self.profile["philips"] = {"disable_packages": [package]}
            with self.assertRaisesRegex(RuntimeError, "another active control transaction"):
                self.command("philips-apply")
        self.assertEqual(self.device.changes, before)

    def test_pending_optional_app_transaction_blocks_shortcut_cli(self):
        manage.save(self.path, privacy.capture(self.device, self.policy, IDENTITY))
        import youtube_shortcut

        with (
            patch("sys.argv", ["manage.py", "youtube-apply", "--state-dir", str(self.directory)]),
            patch.object(manage, "Device", return_value=self.device),
            patch.object(self.device, "identity", return_value=IDENTITY, create=True),
            patch.object(youtube_shortcut, "command") as shortcut,
        ):
            with self.assertRaisesRegex(RuntimeError, "interrupted philips"):
                manage.main()
        shortcut.assert_not_called()
        self.assertEqual(self.device.changes, [])

    def test_philips_profile_refuses_global_or_microphone_changes(self):
        self.profile["philips"] = {**self.policy, "microphone_blocked": False}
        with self.assertRaisesRegex(RuntimeError, "only disable selected apps"):
            self.command("philips-apply")
        self.assertEqual(self.device.changes, [])

    def test_philips_audio_recovery_is_protected(self):
        self.device.states["org.droidtv.customautologservice"] = "default"
        self.profile["philips"] = {"disable_packages": ["org.droidtv.customautologservice"]}
        with self.assertRaisesRegex(RuntimeError, "protected"):
            self.command("philips-apply")
        self.assertEqual(self.device.changes, [])

    def test_restore_uses_saved_policy_even_if_profile_was_removed(self):
        self.command("philips-apply")
        del self.profile["philips"]
        self.command("philips-restore")
        self.assertEqual(self.device.states["example.gallery"], "default")
        self.assertEqual(self.device.states["example.demo"], "disabled-until-used")


class DeviceTests(unittest.TestCase):
    def test_microphone_parser_selects_user_zero_software_toggle(self):
        device = object.__new__(manage.Device)
        for state, expected in [("1", True), ("2", False)]:
            dump = (
                "user_id=0\n sensors=[{ sensor=1\n toggles={\n"
                f"toggle_type=1\n state_type={state}\n last_change=1\n"
                "toggle_type=2\n state_type=1\n } } { sensor=2\n toggles={\n"
                "toggle_type=1\n state_type=1 } }]\n"
                "user_id=10\n sensors=[{ sensor=1\n toggles={\n toggle_type=1\n state_type=1 } }]"
            )
            with patch.object(device, "shell", return_value=dump):
                self.assertEqual(device.microphone_blocked(), expected)
        with patch.object(device, "shell", return_value="unknown"):
            with self.assertRaisesRegex(RuntimeError, "Could not inspect"):
                device.microphone_blocked()

    def test_disabled_apps_are_hidden_but_not_selected_as_launchable(self):
        profile = json.loads((Path(__file__).parent / "profile.json").read_text())
        launchable = {"com.google.android.youtube.tv"}
        content, missing = manage.render(
            profile, launchable, launchable | {"org.jellyfin.androidtv"}
        )
        self.assertIn(b"apps.hide=org.jellyfin.androidtv", content)
        self.assertIn("Jellyfin", missing)


if __name__ == "__main__":
    unittest.main()
