"""Build and reversibly install a permission-free YouTube subscriptions shortcut."""

import base64
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import zipfile
from pathlib import Path

from manage import HERE, digest, render, require, save

PACKAGE = "tv.homelab.youtube"
TARGET = "com.google.android.youtube.tv"
SOURCE = HERE / "youtube-shortcut"


def run(*args):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, timeout=180)
    require(result.returncode == 0, f"Shortcut build tool failed: {Path(args[0]).name}.")
    return result.stdout.decode()


def cache():
    directory = Path.home() / ".cache/homelab/android-tv/youtube-shortcut"
    require(not directory.resolve().is_relative_to(HERE.parents[1]), "Keep APKs outside Git.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory


def source_digest():
    value = hashlib.sha256()
    for root in (SOURCE, cache() / "artwork"):
        for path in sorted(root.rglob("*")):
            if path.is_file():
                value.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    value.update(Path(__file__).read_bytes())
    return value.hexdigest()


def artifact():
    directory = cache()
    metadata = json.loads((directory / "artifact.json").read_text())
    path = directory / "youtube.apk"
    require(metadata["source"] == source_digest(), "Rebuild the shortcut after source changes.")
    require(digest(path) == metadata["sha256"], "Shortcut APK checksum mismatch; rebuild it.")
    return path


def artwork(device, sdk):
    require(sdk is not None, "Provide --sdk or use youtube-shortcut/shell.nix.")
    paths = device.shell("pm", "path", "--user", "0", TARGET).splitlines()
    base = [line.removeprefix("package:") for line in paths if line.endswith("/base.apk")]
    require(len(base) == 1, "Expected one YouTube base APK.")
    directory = cache() / "artwork"
    directory.mkdir(exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory() as temporary:
        apk = Path(temporary) / "youtube.apk"
        device.run("pull", base[0], str(apk))
        badging = run(sdk / "build-tools/34.0.0/aapt2", "dump", "badging", apk)
        require(f"package: name='{TARGET}'" in badging, "Unexpected artwork source package.")
        banner = re.search(r"(?m)^application:.* banner='([^']+)'", badging)
        icon = re.search(r"(?m)^application-icon-320:'([^']+)'", badging)
        require(banner is not None and icon is not None, "YouTube PNG artwork was not found.")
        with zipfile.ZipFile(apk) as archive:
            for name, match in (("banner", banner), ("icon", icon)):
                data = archive.read(match[1])
                require(data.startswith(b"\x89PNG\r\n\x1a\n"), "Expected PNG artwork.")
                (directory / (name + ".png")).write_bytes(data)
    print("Copied the installed YouTube banner and icon into the private build cache.")


def build(sdk):
    try:
        artifact()
    except (FileNotFoundError, RuntimeError):
        pass
    else:
        print("The checked shortcut APK already matches its sources.")
        return
    require(sdk is not None, "Provide --sdk or build inside youtube-shortcut/shell.nix.")
    tools = sdk / "build-tools/34.0.0"
    jar = sdk / "platforms/android-34/android.jar"
    require(jar.is_file() and (tools / "aapt2").is_file(), "Android SDK 34 tools are missing.")
    signing = Path.home() / ".local/state/homelab/android-tv/signing"
    require(
        not signing.resolve().is_relative_to(HERE.parents[1]), "Keep signing material outside Git."
    )
    signing.mkdir(parents=True, exist_ok=True, mode=0o700)
    signing.chmod(0o700)
    key = signing / "youtube.keystore"
    password = signing / "youtube.password"
    require(
        not key.exists() or password.is_file(), "Keep the shortcut signing password with its key."
    )
    if not password.exists():
        with open(password, "x", opener=lambda p, f: os.open(p, f, 0o600)) as output:
            output.write(secrets.token_urlsafe(48) + "\n")
    password.chmod(0o600)
    if not key.exists():
        run(
            "keytool",
            "-genkeypair",
            "-keystore",
            key,
            "-alias",
            "shortcut",
            "-keyalg",
            "RSA",
            "-keysize",
            "2048",
            "-validity",
            "10000",
            "-storepass:file",
            password,
            "-keypass:file",
            password,
            "-dname",
            "CN=Android TV shortcut",
        )
    key.chmod(0o600)
    directory = cache()
    images = directory / "artwork"
    require(
        all((images / name).is_file() for name in ("banner.png", "icon.png")),
        "Run youtube-artwork before building the shortcut.",
    )
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        classes = work / "classes"
        classes.mkdir()
        resources = work / "res/drawable-nodpi"
        resources.mkdir(parents=True)
        for name in ("banner.png", "icon.png"):
            (resources / name).write_bytes((images / name).read_bytes())
        run(tools / "aapt2", "compile", "--dir", work / "res", "-o", work / "res.zip")
        run(
            tools / "aapt2",
            "link",
            "-I",
            jar,
            "--manifest",
            SOURCE / "AndroidManifest.xml",
            work / "res.zip",
            "--min-sdk-version",
            "28",
            "--target-sdk-version",
            "34",
            "--version-code",
            "1",
            "--version-name",
            "1",
            "-o",
            work / "app.apk",
        )
        run(
            "javac",
            "--release",
            "8",
            "-Xlint:all",
            "-Xlint:-options",
            "-Werror",
            "-classpath",
            jar,
            "-d",
            classes,
            *sorted((SOURCE / "src").rglob("*.java")),
        )
        run(
            tools / "d8",
            "--release",
            "--min-api",
            "28",
            "--lib",
            jar,
            "--output",
            work,
            *sorted(classes.rglob("*.class")),
        )
        with zipfile.ZipFile(work / "app.apk", "a") as apk:
            apk.write(work / "classes.dex", "classes.dex")
        run(tools / "zipalign", "-f", "4", work / "app.apk", work / "aligned.apk")
        output = work / "signed.apk"
        run(
            tools / "apksigner",
            "sign",
            "--ks",
            key,
            "--ks-pass",
            "file:" + str(password),
            "--v4-signing-enabled",
            "false",
            "--out",
            output,
            work / "aligned.apk",
        )
        run(tools / "apksigner", "verify", output)
        require(
            "uses-permission" not in run(tools / "aapt2", "dump", "permissions", output),
            "The shortcut must not request permissions.",
        )
        (directory / "youtube.apk").write_bytes(output.read_bytes())
    save(
        directory / "artifact.json",
        {"source": source_digest(), "sha256": digest(directory / "youtube.apk")},
    )
    print("YouTube shortcut built and signature checked; signing material remains outside Git.")


def load(path, identity):
    state = json.loads(path.read_text())
    require(
        state["schema"] == 1 and state["package"] == PACKAGE, "Unsupported shortcut undo record."
    )
    require(state["identity"] == identity, "Device or firmware differs from shortcut undo record.")
    return state


def content(device, profile):
    categories = ("android.intent.category.LEANBACK_LAUNCHER", "android.intent.category.LAUNCHER")
    launchable = {c.split("/")[0] for cat in categories for c in device.activities(cat)}
    known = {
        c.split("/")[0] for cat in categories for c in device.activities(cat, include_disabled=True)
    }
    require(TARGET in launchable, "Install and enable YouTube before configuring its shortcut.")
    require(
        any(app["candidates"][0] == PACKAGE for app in profile["apps"]),
        "The profile must prefer the shortcut tile.",
    )
    return render(profile, launchable | {PACKAGE}, known | {PACKAGE})[0]


def verify(device, state, expected):
    require(
        PACKAGE
        in {
            c.split("/")[0] for c in device.activities("android.intent.category.LEANBACK_LAUNCHER")
        },
        "The shortcut is not launchable.",
    )
    require(
        device.installed_digest(PACKAGE) == state["sha256"],
        "Shortcut APK changed outside this tool.",
    )
    require(
        device.read_config() == base64.b64encode(expected).decode(),
        "Shortcut tile configuration differs.",
    )


def restore(device, state, path, *, restore_config=True):
    # Refuse removal if another profile or an external update now owns this package.
    device.require_private_launcher(PACKAGE)
    present = PACKAGE in device.packages()
    if present:
        require(
            device.installed_digest(PACKAGE) == state["sha256"],
            "Shortcut APK changed outside this tool.",
        )
    if restore_config:
        require(
            device.installed_digest(state["launcher"]["package"]) == state["launcher"]["sha256"],
            "Launcher APK changed outside this tool; review its configuration before restoring.",
        )
        device.write_config(base64.b64decode(state["config_before"]))
        require(
            device.read_config() == state["config_before"],
            "Shortcut configuration did not restore.",
        )
    if present:
        require(
            device.run("uninstall", PACKAGE) == "Success",
            "Could not remove the introduced shortcut.",
        )
        require(PACKAGE not in device.packages(), "Shortcut is still installed.")
    state["status"] = "restored"
    save(path, state)


def apply(device, profile, identity, path, apk):
    expected = content(device, profile)
    device.require_private_launcher(PACKAGE)
    require(device.home().split("/")[0] == profile["launcher"]["package"], "Apply dumbtv first.")
    if path.exists():
        state = load(path, identity)
        require(
            state["status"] == "applied", "Restore or archive the previous shortcut transaction."
        )
        require(state["sha256"] == digest(apk), "Restore before updating the shortcut APK.")
        verify(device, state, expected)
        return
    require(
        PACKAGE not in device.packages("-u"), "Refusing an existing or retained shortcut package."
    )
    before = device.read_config()
    require(before is not None, "Apply the launcher configuration first.")
    state = {
        "schema": 1,
        "identity": identity,
        "package": PACKAGE,
        "sha256": digest(apk),
        "launcher": profile["launcher"],
        "config_before": before,
        "status": "pending",
    }
    save(path, state)
    try:
        require(
            "Success" in device.run("install", "--user", "0", str(apk)).splitlines(),
            "Shortcut installation failed.",
        )
        device.write_config(expected)
        verify(device, state, expected)
    except BaseException:
        print("Shortcut apply failed; restoring its original tile configuration.")
        restore(device, state, path)
        raise
    state["status"] = "applied"
    save(path, state)


def command(action, device, profile, identity, directory):
    path = directory / "youtube.json"
    if action == "youtube-plan":
        if path.exists():
            require(
                load(path, identity)["status"] == "applied",
                "Restore or archive the shortcut transaction.",
            )
        else:
            device.require_private_launcher(PACKAGE)
            require(
                PACKAGE not in device.packages("-u"),
                "Refusing an existing or retained shortcut package.",
            )
        content(device, profile)
        artifact()
        print("Install only the forwarding shortcut for user 0; replace the YouTube tile with it.")
        print("Keep YouTube installed and save the exact previous launcher configuration for undo.")
        return
    if action == "youtube-verify":
        state = load(path, identity)
        require(state["status"] == "applied", "Shortcut transaction is not applied.")
        verify(device, state, content(device, profile))
        print("Shortcut APK, launchability, and tile configuration verified.")
        return
    require(directory.is_dir(), "Apply the managed launcher before its shortcut.")
    launcher = json.loads((directory / "state.json").read_text())
    require(
        launcher["identity"] == identity and launcher["status"] == "applied",
        "Restore the interrupted launcher transaction first.",
    )
    require(
        launcher["launcher"] == profile["launcher"], "Restore before changing launcher version."
    )
    require(
        device.installed_digest(profile["launcher"]["package"]) == profile["launcher"]["sha256"],
        "Installed launcher changed outside this tool.",
    )
    privacy_path = directory / "privacy.json"
    if action == "youtube-apply" and privacy_path.exists():
        import privacy

        require(
            privacy.load(privacy_path, identity)["status"] in {"applied", "restored"},
            "Restore the interrupted privacy transaction first.",
        )
    with (directory / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if action == "youtube-apply":
            apply(device, profile, identity, path, artifact())
            print("YouTube subscriptions shortcut applied; private undo record preserved.")
        else:
            restore(device, load(path, identity), path)
            print("Original YouTube tile restored; only the introduced forwarding app removed.")
