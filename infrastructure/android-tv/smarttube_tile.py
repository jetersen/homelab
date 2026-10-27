"""Build a clean-artwork SmartTube shortcut without modifying its signed APK."""

import base64
import copy
import fcntl
import hashlib
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import smarttube
from manage import HERE, digest, require, save
from youtube_shortcut import run

PACKAGE = smarttube.TILE_PACKAGE
SOURCE = HERE / "smarttube-tile"


def cache():
    directory = Path.home() / ".cache/homelab/android-tv/smarttube-tile"
    require(not directory.resolve().is_relative_to(HERE.parents[1]), "Keep APKs outside Git.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory


def source_digest(profile):
    value = hashlib.sha256(Path(__file__).read_bytes())
    value.update(json.dumps(profile["smarttube_tile"], sort_keys=True).encode())
    for path in sorted(SOURCE.rglob("*")):
        if path.is_file():
            value.update(str(path.relative_to(SOURCE)).encode() + b"\0" + path.read_bytes())
    return value.hexdigest()


def artifact(profile):
    directory = cache()
    metadata = json.loads((directory / "artifact.json").read_text())
    apk = directory / "tile.apk"
    require(
        metadata["source"] == source_digest(profile),
        "Rebuild the SmartTube tile after source changes.",
    )
    require(digest(apk) == metadata["sha256"], "SmartTube tile APK checksum mismatch.")
    return apk


def prepared_profile(profile):
    apk = artifact(profile)
    result = copy.deepcopy(profile)
    result["smarttube_tile"] = {
        "package": PACKAGE,
        "sha256": digest(apk),
        "source": source_digest(profile),
        "version": "1",
    }
    return result


def build(profile, sdk):
    require(profile["smarttube_tile"]["package"] == PACKAGE, "Unsupported tile package.")
    try:
        artifact(profile)
    except (FileNotFoundError, RuntimeError):
        pass
    else:
        print("The checked SmartTube tile APK already matches its sources.")
        return
    require(sdk is not None, "Use the SDK shell or provide --sdk.")
    tools = sdk / "build-tools/34.0.0"
    jar = sdk / "platforms/android-34/android.jar"
    require(jar.is_file() and (tools / "aapt2").is_file(), "Android SDK 34 tools are missing.")
    signing = Path.home() / ".local/state/homelab/android-tv/signing"
    require(
        not signing.resolve().is_relative_to(HERE.parents[1]), "Keep signing material outside Git."
    )
    key, password = signing / "youtube.keystore", signing / "youtube.password"
    require(
        key.is_file() and password.is_file(),
        "Build the legacy YouTube shortcut first to create its local signing identity.",
    )
    directory = cache()
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        resources = work / "res/drawable-nodpi"
        resources.mkdir(parents=True)
        for name in ("banner", "icon"):
            spec = profile["smarttube_tile"]
            require(spec[name + "_url"].startswith("https://"), "Artwork requires HTTPS.")
            with urllib.request.urlopen(spec[name + "_url"], timeout=60) as response:
                data = response.read(1024 * 1024)
            require(
                hashlib.sha256(data).hexdigest() == spec[name + "_sha256"],
                "SmartTube artwork checksum mismatch.",
            )
            require(data.startswith(b"\x89PNG\r\n\x1a\n"), "Expected PNG artwork.")
            (resources / (name + ".png")).write_bytes(data)
        classes = work / "classes"
        classes.mkdir()
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
            "The tile must not request permissions.",
        )
        (directory / "tile.apk").write_bytes(output.read_bytes())
    save(
        directory / "artifact.json",
        {"source": source_digest(profile), "sha256": digest(directory / "tile.apk")},
    )
    print("SmartTube tile built with pinned upstream artwork and no permissions.")


def parent(device, profile, identity, directory):
    state = smarttube.load(directory / "smarttube.json", identity)
    require(
        state["status"] == "applied" and state["app"] == profile["smarttube"],
        "Apply the pinned SmartTube transaction first.",
    )
    require(
        device.installed_digest(smarttube.PACKAGE) == state["app"]["sha256"],
        "Installed SmartTube changed.",
    )
    return smarttube.active_profile(device, profile, identity, directory)


def command(action, device, profile, identity, directory):
    path = directory / "smarttube_tile.json"
    operation = action.removeprefix("smarttube-tile-")
    if operation == "restore":
        require(path.is_file(), "No SmartTube tile undo record found.")
        with (directory / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            smarttube.restore(device, smarttube.load(path, identity), path)
        device.shell("input", "keyevent", "KEYCODE_HOME")
        print("Previous tile restored; SmartTube and its account data retained.")
        return
    effective = parent(device, profile, identity, directory)
    prepared = prepared_profile(profile)
    effective["smarttube_tile"] = prepared["smarttube_tile"]
    if operation == "verify":
        state = smarttube.load(path, identity)
        require(state["status"] == "applied", "SmartTube tile transaction is not applied.")
        require(
            state["app"] == prepared["smarttube_tile"]
            and state["launcher"] == effective["launcher"],
            "Tile or launcher pin changed.",
        )
        require(
            state["config_applied"]
            == base64.b64encode(smarttube.content(device, effective, PACKAGE)).decode(),
            "Reapply the updated tile profile.",
        )
        smarttube.verify(device, state)
        print(
            "Clean-artwork tile, SmartTube APK, active launcher, HOME, and configuration verified."
        )
        return
    require(operation in {"plan", "apply"}, "Unknown SmartTube tile operation.")
    if operation == "plan":
        device.require_private_launcher(PACKAGE)
        if path.exists():
            state = smarttube.load(path, identity)
            require(
                state["status"] == "applied"
                and state["app"] == prepared["smarttube_tile"]
                and state["launcher"] == effective["launcher"],
                "Restore or archive the previous tile transaction.",
            )
        else:
            require(
                PACKAGE not in device.packages("-u"),
                "Refusing an existing or retained tile installation.",
            )
        smarttube.content(device, effective, PACKAGE)
        print(
            "Install a permission-free tile with pinned SmartTube artwork; open native Subscriptions. Undo keeps SmartTube and its data."
        )
        return
    with (directory / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        effective = parent(device, profile, identity, directory)
        effective["smarttube_tile"] = prepared["smarttube_tile"]
        smarttube.apply(
            device, effective, identity, path, artifact(profile), scope="smarttube_tile"
        )
    print("Clean SmartTube tile applied; native app and account data retained.")
