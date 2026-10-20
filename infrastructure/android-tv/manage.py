#!/usr/bin/env python3
"""Manage dumbtv's Android TV home screen with a durable, device-specific undo record."""

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPONENT = re.compile(r"^[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+$")
HOME_INTENT = ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME"]
CONFIG = "/sdcard/Android/data/tv.dumbtv.home/files/home.conf"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


class Device:
    def __init__(self, adb, serial=None):
        self.command = [adb]
        result = self.run("devices")
        devices = [line.split() for line in result.splitlines()[1:] if line.strip()]
        require(all(len(row) == 2 for row in devices), "ADB reports a device access error.")
        if serial:
            require([serial, "device"] in devices, "Selected TV is absent or not authorized.")
        else:
            require(len(devices) == 1, "Connect exactly one TV, or select it with --serial.")
            serial, status = devices[0]
            require(status == "device", "Accept the debugging authorization prompt on the TV.")
        self.command += ["-s", serial]

    def run(self, *args):
        result = subprocess.run(
            [*self.command, *args], capture_output=True, timeout=90, check=False
        )
        # Do not echo commands or device output: it can contain device/account identifiers.
        errors = sorted(
            set(
                re.findall(
                    rb"INSTALL_(?:FAILED|PARSE_FAILED)_[A-Z_]+", result.stdout + result.stderr
                )
            )
        )
        detail = ": " + ", ".join(code.decode() for code in errors) if errors else ""
        require(result.returncode == 0, f"ADB operation failed ({args[0]}){detail}.")
        return result.stdout.decode().replace("\r", "").strip()

    def shell(self, *args):
        # adb shell joins arguments; quote explicitly for the remote shell.
        return self.run("shell", shlex.join(args))

    def identity(self):
        require(self.shell("am", "get-current-user") == "0", "Only Android user 0 is supported.")
        require("0" in self.users(), "Android user 0 is missing.")
        manufacturer = self.shell("getprop", "ro.product.manufacturer")
        require(manufacturer.lower() != "amazon", "Fire OS requires its own reviewed HOME hook.")
        sdk = self.shell("getprop", "ro.build.version.sdk")
        require(
            sdk.isdigit() and int(sdk) >= 28, "The pinned launcher requires Android 9 or newer."
        )
        features = self.shell("pm", "list", "features").splitlines()
        require("feature:android.software.leanback" in features, "Device is not an Android TV.")
        serial = self.shell("getprop", "ro.serialno")
        require(
            serial and serial != "unknown", "A stable hardware serial is required for rollback."
        )
        return {"serial": serial, "build": self.shell("getprop", "ro.build.fingerprint")}

    def users(self):
        users = re.findall(r"UserInfo\{(\d+):", self.shell("pm", "list", "users"))
        require(users, "Could not enumerate Android users.")
        return users

    def packages(self, *flags, user="0"):
        return {
            line.removeprefix("package:")
            for line in self.shell("pm", "list", "packages", "--user", user, *flags).splitlines()
            if line.startswith("package:")
        }

    def require_private_launcher(self, package):
        require(
            all(package not in self.packages(user=user) for user in self.users() if user != "0"),
            "dumbtv is installed for another user; refusing a change that could affect their data.",
        )

    def activities(self, category):
        result = self.shell(
            "cmd",
            "package",
            "query-activities",
            "--components",
            "--user",
            "0",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            category,
        )
        return {line for line in result.splitlines() if COMPONENT.fullmatch(line)}

    def home(self):
        result = self.shell(
            "cmd", "package", "resolve-activity", "--components", "--user", "0", *HOME_INTENT
        )
        matches = [line for line in result.splitlines() if COMPONENT.fullmatch(line)]
        require(len(matches) == 1, "Could not resolve one concrete HOME activity.")
        home = matches[0]
        require(not home.startswith("android/"), "Choose a default home screen on the TV first.")
        return home

    def set_home(self, component):
        result = self.shell("cmd", "package", "set-home-activity", "--user", "0", component)
        require(result == "Success", "Android refused the default HOME change.")

    def read_config(self):
        # Listing the parent first avoids treating denied shared-storage access as an absent file.
        self.shell("ls", "/sdcard/Android/data")
        status = self.shell(
            "sh", "-c", f"if test -f {CONFIG}; then echo present; else echo absent; fi"
        )
        require(
            status in {"present", "absent"}, "Launcher configuration directory is inaccessible."
        )
        if status == "absent":
            return None
        # Pull preserves exact bytes, unlike adb shell's text handling.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "home.conf"
            self.run("pull", CONFIG, str(path))
            return base64.b64encode(path.read_bytes()).decode()

    def write_config(self, content):
        self.shell("am", "force-stop", "--user", "0", "tv.dumbtv.home")
        if content is None:
            self.shell("rm", "-f", CONFIG)
            return
        self.shell("mkdir", "-p", str(Path(CONFIG).parent))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "home.conf"
            path.write_bytes(content)
            # The app is stopped and the original bytes are journaled. A direct push avoids
            # leaving an extra remote file behind if a transfer is interrupted.
            self.run("push", str(path), CONFIG)

    def installed_digest(self, package):
        paths = self.shell("pm", "path", "--user", "0", package).splitlines()
        require(len(paths) == 1 and paths[0].startswith("package:"), "Expected one launcher APK.")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "launcher.apk"
            self.run("pull", paths[0].removeprefix("package:"), str(path))
            return digest(path)


def render(profile, launchable):
    selected = []
    names = {}
    missing = []
    for app in profile["apps"]:
        candidates = [package for package in app["candidates"] if package in launchable]
        if not candidates:
            missing.append(app["name"])
            continue
        package = candidates[0]
        selected.append(package)
        names["name." + package] = app["name"]
    require(selected, "None of the configured apps is launchable; review profile.json first.")
    values = {
        **profile["appearance"],
        "apps.order": ",".join(selected),
        "apps.show": ",".join(selected),
        "apps.hide": ",".join(
            sorted(launchable - set(selected) - {profile["launcher"]["package"]})
        ),
        **names,
    }
    require(
        all("\n" not in str(v) for v in values.values()), "Configuration cannot contain newlines."
    )
    return ("".join(f"{key}={value}\n" for key, value in values.items())).encode(), missing


def artifact(profile):
    launcher = profile["launcher"]
    cache = Path.home() / ".cache/homelab/android-tv"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (launcher["sha256"] + ".apk")
    if not path.exists() or digest(path) != launcher["sha256"]:
        require(launcher["url"].startswith("https://"), "APK downloads require HTTPS.")
        with urllib.request.urlopen(launcher["url"], timeout=60) as response:
            content = response.read()
        require(hashlib.sha256(content).hexdigest() == launcher["sha256"], "APK checksum mismatch.")
        path.write_bytes(content)
    return path


def baseline(device, profile, identity):
    launcher = profile["launcher"]
    home = device.home()
    require(
        home.split("/")[0] != launcher["package"], "Original HOME must be a different launcher."
    )
    installed = launcher["package"] in device.packages()
    require(
        installed or launcher["package"] not in device.packages("-u"),
        "dumbtv has retained package state; refusing to risk existing data during restoration.",
    )
    if installed:
        require(
            device.installed_digest(launcher["package"]) == launcher["sha256"],
            "Existing dumbtv APK differs; refusing an update that cannot restore app data.",
        )
        require(launcher["package"] in device.packages("-e"), "Existing dumbtv must be enabled.")
    return {
        "schema": 1,
        "identity": identity,
        "launcher": launcher,
        "home": home,
        "installed_before": installed,
        "config_before": device.read_config() if installed else None,
        "status": "pending",
    }


def verify(device, profile, content):
    package = profile["launcher"]["package"]
    require(device.home().split("/")[0] == package, "HOME still resolves to the vendor launcher.")
    require(device.read_config() == base64.b64encode(content).decode(), "Launcher config differs.")
    device.shell("input", "keyevent", "KEYCODE_HOME")
    for _ in range(10):
        activities = device.shell("dumpsys", "activity", "activities")
        resumed = [
            line
            for line in activities.splitlines()
            if "mResumedActivity" in line or "topResumedActivity" in line
        ]
        if any(package + "/" in line for line in resumed):
            return
        time.sleep(0.5)
    raise RuntimeError("The HOME key did not bring dumbtv to the foreground.")


def restore(device, state, path):
    launcher = state["launcher"]
    # Put the working original HOME back before modifying or removing dumbtv.
    device.set_home(state["home"])
    require(
        device.home() == state["home"], "Original HOME did not restore; keeping dumbtv installed."
    )
    device.require_private_launcher(launcher["package"])
    present = launcher["package"] in device.packages()
    if present:
        require(
            device.installed_digest(launcher["package"]) == launcher["sha256"],
            "dumbtv APK changed outside this tool; original HOME restored, manual review needed.",
        )
        if state["installed_before"]:
            content = state["config_before"]
            device.write_config(base64.b64decode(content) if content is not None else None)
            require(device.read_config() == content, "Original configuration did not restore.")
        else:
            result = device.run("uninstall", launcher["package"])
            require(result == "Success", "Could not remove the newly installed launcher.")
            require(launcher["package"] not in device.packages(), "Launcher is still installed.")
    else:
        require(not state["installed_before"], "Previously installed dumbtv is missing.")
    device.shell("input", "keyevent", "KEYCODE_HOME")
    state["status"] = "restored"
    save(path, state)


def apply(device, profile, identity, content, path):
    device.require_private_launcher(profile["launcher"]["package"])
    if path.exists():
        state = json.loads(path.read_text())
        require(state["schema"] == 1, "Unsupported undo record schema.")
        require(state["identity"] == identity, "Device or firmware differs from the undo record.")
        require(
            state["status"] != "restored", "Archive the restored undo record before a new apply."
        )
        require(state["status"] == "applied", "An interrupted apply needs restore first.")
        require(
            state["launcher"] == profile["launcher"], "Restore before changing launcher version."
        )
        require(
            device.installed_digest(profile["launcher"]["package"])
            == profile["launcher"]["sha256"],
            "Installed launcher changed outside this tool.",
        )
    else:
        state = baseline(device, profile, identity)
        # Download and verify before recording a transaction or changing anything on the TV.
        apk = artifact(profile) if not state["installed_before"] else None
        save(path, state)
        try:
            if apk is not None:
                result = device.run("install", "--user", "0", str(apk))
                require("Success" in result.splitlines(), "Launcher installation failed.")
        except BaseException:
            print(
                "Installation interrupted. The undo record is saved; run restore before retrying."
            )
            raise
    state["status"] = "pending"
    save(path, state)
    try:
        device.write_config(content)
        device.set_home(profile["launcher"]["component"])
        verify(device, profile, content)
    except BaseException:
        print("Apply failed; restoring the original launcher and configuration.")
        restore(device, state, path)
        raise
    state["status"] = "applied"
    save(path, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "fetch", "apply", "verify", "restore"])
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", help="ADB transport selector, never saved in the repository")
    parser.add_argument("--profile", type=Path, default=HERE / "profile.json")
    parser.add_argument("--state-dir", type=Path, help="Private rollback directory outside Git")
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    if args.action == "fetch":
        artifact(profile)
        print("Pinned launcher APK downloaded and SHA-256 verified.")
        return
    device = Device(args.adb, args.serial)
    identity = device.identity()
    key = hashlib.sha256(identity["serial"].encode()).hexdigest()[:24]
    directory = (args.state_dir or Path.home() / ".local/state/homelab/android-tv" / key).resolve()
    repository = HERE.parents[1]
    require(not directory.is_relative_to(repository), "Keep rollback state outside the repository.")
    if args.action == "plan":
        device.require_private_launcher(profile["launcher"]["package"])
        if (directory / "state.json").exists():
            state = json.loads((directory / "state.json").read_text())
            require(
                state["identity"] == identity, "Device or firmware differs from the undo record."
            )
            require(
                state["status"] == "applied", "Restore or archive the previous transaction first."
            )
        else:
            baseline(device, profile, identity)
    elif args.action == "restore":
        require((directory / "state.json").is_file(), "No undo record found for this TV.")
    if args.action != "restore":
        launchable = {
            component.split("/")[0]
            for category in [
                "android.intent.category.LEANBACK_LAUNCHER",
                "android.intent.category.LAUNCHER",
            ]
            for component in device.activities(category)
        }
        content, missing = render(profile, launchable)
        for name in missing:
            print(f"Configured app is not installed or launchable: {name}")
    if args.action == "plan":
        print("Plan: install the pinned launcher if absent; apply profile; select it as HOME.")
        print("Other apps are hidden from this launcher and remain installed with their data.")
        print("No package disabling, DNS, VPN, accessibility, or system settings changes.")
        return
    if args.action == "verify":
        verify(device, profile, content)
        print("HOME resolution, configuration bytes, and foreground activity verified.")
        return
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / "state.json"
    with (directory / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "restore":
            state = json.loads(path.read_text())
            require(
                state["identity"] == identity, "Device or firmware differs from the undo record."
            )
            require(state["schema"] == 1, "Unsupported undo record schema.")
            restore(device, state, path)
            print("Original HOME and launcher configuration restored.")
        else:
            apply(device, profile, identity, content, path)
            print(
                "Launcher profile applied and verified. Keep the private state directory for undo."
            )


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Interrupted. If apply started, reconnect and run restore.") from None
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error)) from None
