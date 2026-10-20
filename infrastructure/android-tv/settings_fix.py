"""Build a pinned settings-button patch and switch launchers without replacing app data."""

import contextlib
import copy
import fcntl
import hashlib
import io
import json
import os
import secrets
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

from manage import HERE, artifact, baseline, digest, render, require, save

COMMIT = "90fa871149ec5897d1afd635d0e327ce672ab493"
ORIGINAL = "tv.dumbtv.home"
PACKAGE = "tv.homelab.home"
OLD = """        Intent tvSettings = new Intent(Intent.ACTION_MAIN)
                .addCategory("android.intent.category.LEANBACK_SETTINGS");
        boolean found = tvSettings.resolveActivity(getPackageManager()) != null;
        launch(found ? tvSettings : new Intent(Settings.ACTION_SETTINGS), null);"""
NEW = "        launch(new Intent(Settings.ACTION_SETTINGS), null);"


def run(*args):
    result = subprocess.run([str(a) for a in args], capture_output=True, timeout=180)
    require(result.returncode == 0, f"Launcher build tool failed: {Path(args[0]).name}.")
    return result.stdout


def cache():
    path = Path.home() / ".cache/homelab/android-tv/settings-fix"
    require(not path.resolve().is_relative_to(HERE.parents[1]), "Keep APKs outside Git.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def source_digest():
    return hashlib.sha256(COMMIT.encode() + Path(__file__).read_bytes()).hexdigest()


def built_apk():
    metadata = json.loads((cache() / "artifact.json").read_text())
    require(
        metadata["source"] == source_digest(), "Rebuild the launcher patch after source changes."
    )
    apk = cache() / "launcher.apk"
    require(digest(apk) == metadata["sha256"], "Patched launcher APK checksum differs.")
    return apk


def patched_profile(profile):
    require(COMMIT in profile["launcher"]["source"], "Review the patch for the new source pin.")
    apk = built_apk()
    result = copy.deepcopy(profile)
    result["launcher"].update(
        package=PACKAGE,
        component=PACKAGE + "/.Home",
        version="1.1-settings.1",
        sha256=digest(apk),
        local_artifact=str(apk),
    )
    result.pop("home_fallback", None)
    return result


def patch_source(root):
    home = root / "src/tv/dumbtv/home/Home.java"
    content = home.read_text()
    require(content.count(OLD) == 1, "Pinned Settings method differs; review before patching.")
    home.write_text(content.replace(OLD, NEW))
    # A separate package preserves the upstream installation and its signing identity/data.
    for path in root.rglob("*"):
        if path.suffix in {".java", ".xml"}:
            path.write_text(path.read_text().replace(ORIGINAL, PACKAGE))


def build(source, sdk):
    try:
        built_apk()
    except (FileNotFoundError, RuntimeError):
        pass
    else:
        print("The checked launcher patch already matches its sources.")
        return
    require(sdk is not None, "Provide --sdk or use youtube-shortcut/shell.nix.")
    require(
        run("javac", "-version").decode().startswith("javac 17."),
        "Use the pinned JDK 17 shell for the launcher build.",
    )
    tools = sdk / "build-tools/34.0.0"
    jar = sdk / "platforms/android-34/android.jar"
    require(jar.is_file() and (tools / "aapt2").is_file(), "Android SDK 34 tools are missing.")
    signing = Path.home() / ".local/state/homelab/android-tv/signing"
    require(
        not signing.resolve().is_relative_to(HERE.parents[1]), "Keep signing material outside Git."
    )
    signing.mkdir(parents=True, exist_ok=True, mode=0o700)
    signing.chmod(0o700)
    key, password = signing / "launcher.keystore", signing / "launcher.password"
    require(not key.exists() or password.is_file(), "Keep the signing password with its key.")
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
            "launcher",
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
            "CN=Android TV launcher",
        )
    key.chmod(0o600)
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        archive = run("git", "-C", source, "archive", "--format=tar", COMMIT, "launcher")
        with tarfile.open(fileobj=io.BytesIO(archive)) as source_tar:
            source_tar.extractall(work, filter="data")
        root = work / "launcher"
        patch_source(root)
        classes, generated = work / "classes", work / "gen"
        classes.mkdir()
        generated.mkdir()
        run(tools / "aapt2", "compile", "--dir", root / "res", "-o", work / "res.zip")
        run(
            tools / "aapt2",
            "link",
            "-I",
            jar,
            "--manifest",
            root / "AndroidManifest.xml",
            work / "res.zip",
            "--min-sdk-version",
            "28",
            "--target-sdk-version",
            "28",
            "--version-code",
            "2",
            "--version-name",
            "1.1-settings.1",
            "--java",
            generated,
            "-o",
            work / "app.apk",
        )
        run(
            "javac",
            "--release",
            "8",
            "-classpath",
            jar,
            "-d",
            classes,
            *sorted((root / "src").rglob("*.java")),
            *sorted(generated.rglob("*.java")),
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
            work / "signed.apk",
            work / "aligned.apk",
        )
        run(tools / "apksigner", "verify", work / "signed.apk")
        (cache() / "launcher.apk").write_bytes((work / "signed.apk").read_bytes())
    save(
        cache() / "artifact.json",
        {"source": source_digest(), "sha256": digest(cache() / "launcher.apk")},
    )
    print("Pinned launcher patched, built, and signature checked; APK and keys remain private.")


def state_path(directory):
    return directory / "settings/state.json"


def load(path, identity):
    state = json.loads(path.read_text())
    require(
        state["schema"] == 2 and state["launcher"]["package"] == PACKAGE,
        "Unknown patch undo record.",
    )
    require(state["identity"] == identity, "Device or firmware differs from patch undo record.")
    return state


def require_inactive(directory, identity, *, allow_applied=False):
    path = state_path(directory)
    if path.exists():
        allowed = {"restored", "applied"} if allow_applied else {"restored"}
        require(
            load(path, identity)["status"] in allowed,
            "Run settings-restore before changing the underlying launcher or shortcut.",
        )


@contextlib.contextmanager
def route(device):
    before = device.config_package
    device.config_package = PACKAGE
    try:
        yield
    finally:
        device.config_package = before


def restore(device, identity, directory):
    import manage

    path = state_path(directory)
    state = load(path, identity)
    if state["status"] != "restored":
        with route(device):
            manage.restore(device, state, path)


def command(action, device, profile, identity, directory):
    import manage
    import privacy
    import youtube_shortcut

    operation = action.removeprefix("settings-")
    path = state_path(directory)
    if operation == "restore":
        require(path.exists(), "No settings-patch undo record found.")
        with (directory / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            restore(device, identity, directory)
        print("Original dumbtv selected; only the introduced patched copy removed.")
        return
    original = json.loads((directory / "state.json").read_text())
    require(
        original["identity"] == identity and original["status"] == "applied",
        "Apply the upstream launcher first; recover interrupted transactions before patching.",
    )
    require(original["launcher"] == profile["launcher"], "Original launcher profile changed.")
    require(
        device.installed_digest(ORIGINAL) == original["launcher"]["sha256"],
        "Original launcher APK changed.",
    )
    privacy.require_complete(directory, identity)
    shortcut = directory / "youtube.json"
    if shortcut.exists():
        require(
            youtube_shortcut.load(shortcut, identity)["status"] in {"applied", "restored"},
            "Recover the interrupted shortcut before patching.",
        )
    effective = patched_profile(profile)
    # External wallpapers belong to the original app; do not silently lose them.
    require(
        profile["appearance"].get("background") != "image"
        and profile["appearance"].get("rotate", "off") == "off",
        "The separate launcher patch currently supports solid backgrounds only.",
    )
    launchable = {
        c.split("/")[0]
        for cat in ("android.intent.category.LEANBACK_LAUNCHER", "android.intent.category.LAUNCHER")
        for c in device.activities(cat)
    }
    known = {
        c.split("/")[0]
        for cat in ("android.intent.category.LEANBACK_LAUNCHER", "android.intent.category.LAUNCHER")
        for c in device.activities(cat, include_disabled=True)
    }
    content, _ = render(effective, launchable, known)
    with route(device):
        if operation == "plan":
            if path.exists():
                state = load(path, identity)
                require(
                    state["status"] == "applied" and state["launcher"] == effective["launcher"],
                    "Restore or archive the previous patch before changing it.",
                )
            else:
                require(
                    device.home() == profile["launcher"]["component"],
                    "Select the managed upstream launcher before patching.",
                )
                device.require_private_launcher(PACKAGE)
                require(
                    PACKAGE not in device.packages("-u"),
                    "Refusing an existing or retained patched launcher.",
                )
                baseline(device, effective, identity)
                artifact(effective)
            print(
                "Install a patched copy for user 0 and select HOME; keep the original launcher and data installed."
            )
            return
        if operation == "verify":
            state = load(path, identity)
            require(state["status"] == "applied", "The settings patch is not applied.")
            require(
                state["launcher"] == effective["launcher"], "Patched launcher artifact differs."
            )
            require(
                device.installed_digest(PACKAGE) == state["launcher"]["sha256"],
                "Patched launcher APK changed.",
            )
            manage.verify(device, effective, content)
            print("Patched launcher APK, HOME, configuration, and foreground verified.")
            return
        require(operation == "apply", "Unknown settings-patch operation.")
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.parent.chmod(0o700)
        with (directory / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not path.exists():
                require(
                    device.home() == profile["launcher"]["component"],
                    "Select the managed upstream launcher before patching.",
                )
                require(
                    PACKAGE not in device.packages("-u"),
                    "Refusing an existing or retained patched launcher.",
                )
            manage.apply(device, effective, identity, content, path)
        print(
            "Settings-button patch applied; original installation and first undo baseline preserved."
        )
