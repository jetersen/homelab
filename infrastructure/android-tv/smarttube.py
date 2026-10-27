"""Pin SmartTube F-Droid and reversibly replace the active launcher's YouTube tile."""

import base64
import contextlib
import copy
import fcntl
import json
import re
import subprocess

import manage
import privacy
import settings_fix
import youtube_shortcut
from manage import require, save

PACKAGE = "app.smarttube.fdroid"
TILE_PACKAGE = "tv.homelab.smarttube"
PACKAGES = {"smarttube": PACKAGE, "smarttube_tile": TILE_PACKAGE}
CATEGORIES = ("android.intent.category.LEANBACK_LAUNCHER", "android.intent.category.LAUNCHER")


def legacy_profile(profile):
    result = copy.deepcopy(profile)
    for app in result["apps"]:
        app["candidates"] = [p for p in app["candidates"] if p not in PACKAGES.values()]
    result["apps"] = [a for a in result["apps"] if a["candidates"]]
    return result


def fetch(profile, sdk):
    spec = profile["smarttube"]
    require(spec["package"] == PACKAGE, "Only the reviewed F-Droid package is supported.")
    require(sdk is not None, "Use the SDK shell or provide --sdk for APK signature verification.")
    apk = manage.artifact({"launcher": spec})
    tool = sdk / "build-tools/34.0.0/apksigner"
    result = subprocess.run(
        [str(tool), "verify", "--print-certs", str(apk)], capture_output=True, text=True, timeout=60
    )
    require(result.returncode == 0, "SmartTube APK signature verification failed.")
    signers = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)", result.stdout)
    require(
        signers == [spec["signer_sha256"]], "SmartTube signing certificate differs from the pin."
    )
    result = subprocess.run(
        [str(sdk / "build-tools/34.0.0/aapt2"), "dump", "badging", str(apk)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    require(result.returncode == 0, "Could not inspect SmartTube's APK manifest.")
    expected = f"package: name='{PACKAGE}' versionCode='{spec['version_code']}' versionName='{spec['version']}'"
    require(
        result.stdout.startswith(expected), "SmartTube package or version differs from the pin."
    )
    save(apk.with_suffix(".verified.json"), {"spec": spec})
    print("SmartTube APK SHA-256, signing certificate, package, and version verified.")


def artifact(profile):
    spec = profile["smarttube"]
    require(spec["package"] == PACKAGE, "Unsupported SmartTube package.")
    apk = manage.artifact({"launcher": spec})
    metadata = apk.with_suffix(".verified.json")
    require(metadata.is_file(), "Run smarttube-fetch with the SDK before applying.")
    require(
        json.loads(metadata.read_text()) == {"spec": spec}, "Re-verify the changed SmartTube pin."
    )
    return apk


def load(path, identity):
    state = json.loads(path.read_text())
    require(
        state["schema"] == 1 and state["app"]["package"] == PACKAGES.get(path.name.split(".")[0]),
        "Unknown SmartTube undo record.",
    )
    require(state["identity"] == identity, "Device or firmware differs from SmartTube undo record.")
    return state


def require_complete(directory, identity):
    for scope in PACKAGES:
        path = directory / f"{scope}.json"
        if path.exists():
            require(
                load(path, identity)["status"] in {"applied", "restored"},
                "Recover the interrupted SmartTube transaction first.",
            )


def require_inactive(directory, identity):
    for scope in PACKAGES:
        path = directory / f"{scope}.json"
        if path.exists():
            require(
                load(path, identity)["status"] == "restored",
                "Run smarttube-restore before changing the underlying launcher or shortcut.",
            )


@contextlib.contextmanager
def route(device, package):
    before = device.config_package
    device.config_package = package
    try:
        yield
    finally:
        device.config_package = before


def active_profile(device, profile, identity, directory):
    state = json.loads((directory / "state.json").read_text())
    require(
        state["identity"] == identity and state["status"] == "applied",
        "Apply the launcher first; recover interrupted transactions before SmartTube.",
    )
    require(state["launcher"] == profile["launcher"], "The underlying launcher profile changed.")
    child = settings_fix.state_path(directory)
    if child.exists():
        patch = settings_fix.load(child, identity)
        require(
            patch["status"] in {"applied", "restored"},
            "Recover the interrupted Settings patch first.",
        )
        if patch["status"] == "applied":
            profile = settings_fix.patched_profile(profile)
            require(patch["launcher"] == profile["launcher"], "Patched launcher artifact changed.")
    privacy.require_complete(directory, identity)
    shortcut = directory / "youtube.json"
    if shortcut.exists():
        require(
            youtube_shortcut.load(shortcut, identity)["status"] in {"applied", "restored"},
            "Recover the interrupted YouTube shortcut first.",
        )
    require(device.home() == profile["launcher"]["component"], "The managed launcher is not HOME.")
    require(
        device.installed_digest(profile["launcher"]["package"]) == profile["launcher"]["sha256"],
        "Active launcher APK changed.",
    )
    return profile


def content(device, profile, package=PACKAGE):
    require(
        any(package in a["candidates"] for a in profile["apps"]),
        "The profile must prefer SmartTube for a tile.",
    )
    launchable = {c.split("/")[0] for cat in CATEGORIES for c in device.activities(cat)}
    known = {
        c.split("/")[0] for cat in CATEGORIES for c in device.activities(cat, include_disabled=True)
    }
    return manage.render(profile, launchable | {package}, known | {package})[0]


def verify(device, state):
    package = state["app"]["package"]
    require(
        package in {c.split("/")[0] for c in device.activities(CATEGORIES[0])},
        "SmartTube is not launchable.",
    )
    require(
        device.installed_digest(package) == state["app"]["sha256"],
        "SmartTube APK changed outside this tool.",
    )
    require(
        device.installed_digest(state["launcher"]["package"]) == state["launcher"]["sha256"],
        "Active launcher APK changed.",
    )
    with route(device, state["launcher"]["package"]):
        manage.verify(
            device, {"launcher": state["launcher"]}, base64.b64decode(state["config_applied"])
        )


def restore(device, state, path):
    if state["status"] == "restored":
        return
    package = state["app"]["package"]
    device.require_private_launcher(package)
    present = package in device.packages()
    if present:
        require(
            device.installed_digest(package) == state["app"]["sha256"],
            "SmartTube APK changed; review before removing its data.",
        )
    require(
        state["launcher"]["package"] in device.packages()
        and device.installed_digest(state["launcher"]["package"]) == state["launcher"]["sha256"],
        "The recorded launcher changed or is missing; review before restoring its configuration.",
    )
    child = path.with_name("smarttube_tile.json")
    if package == PACKAGE and child.exists():
        restore(device, load(child, state["identity"]), child)
    state["status"] = "restoring"
    save(path, state)
    with route(device, state["launcher"]["package"]):
        device.write_config(base64.b64decode(state["config_before"]))
        require(
            device.read_config() == state["config_before"],
            "Previous launcher configuration did not restore.",
        )
    if present:
        require(
            device.run("uninstall", package) == "Success",
            "Could not remove the introduced SmartTube app.",
        )
        require(
            package not in device.packages("-u"),
            "Introduced SmartTube app still has retained state.",
        )
    state.pop("reapply_before", None)
    state["status"] = "restored"
    save(path, state)


def apply(device, profile, identity, path, apk, *, scope="smarttube"):
    spec = profile[scope]
    package = spec["package"]
    require(PACKAGES.get(scope) == package, "Unsupported app transaction.")
    expected = content(device, profile, package)
    device.require_private_launcher(package)
    existing = path.exists()
    with route(device, profile["launcher"]["package"]):
        before = device.read_config()
    require(before is not None, "The active launcher has no configuration.")
    if existing:
        state = load(path, identity)
        require(
            state["status"] == "applied", "Restore or archive the previous SmartTube transaction."
        )
        require(
            state["app"] == spec and state["launcher"] == profile["launcher"],
            "Restore SmartTube before changing its APK or launcher.",
        )
        require(
            device.installed_digest(package) == state["app"]["sha256"],
            "Installed SmartTube changed.",
        )
        previous = copy.deepcopy(state)
        state["reapply_before"] = before
    else:
        require(
            package not in device.packages("-u"),
            "Refusing an existing or retained SmartTube installation.",
        )
        state = {
            "schema": 1,
            "identity": identity,
            "app": spec,
            "launcher": profile["launcher"],
            "config_before": before,
        }
    require(manage.digest(apk) == spec["sha256"], "SmartTube download changed.")
    state.update(status="pending", config_applied=base64.b64encode(expected).decode())
    save(path, state)
    try:
        if not existing:
            require(
                "Success" in device.run("install", "--user", "0", str(apk)).splitlines(),
                "SmartTube installation failed.",
            )
        with route(device, profile["launcher"]["package"]):
            device.write_config(expected)
        verify(device, state)
    except BaseException:
        if existing:
            # A failed reapply must keep account data created since the first installation.
            with route(device, profile["launcher"]["package"]):
                device.write_config(base64.b64decode(before))
                require(
                    device.read_config() == before,
                    "Reapply rollback failed; recover the pending transaction.",
                )
            save(path, previous)
        else:
            print(
                "SmartTube apply failed; restoring the previous tile and removing only the introduced app."
            )
            restore(device, state, path)
        raise
    state.pop("reapply_before", None)
    state["status"] = "applied"
    save(path, state)


def command(action, device, profile, identity, directory):
    path = directory / "smarttube.json"
    operation = action.removeprefix("smarttube-")
    if operation == "restore":
        require(path.is_file(), "No SmartTube undo record found.")
        with (directory / "lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            restore(device, load(path, identity), path)
        device.shell("input", "keyevent", "KEYCODE_HOME")
        print("Previous tile restored; only the introduced SmartTube app and its data removed.")
        return
    effective = active_profile(device, profile, identity, directory)
    if operation == "verify":
        state = load(path, identity)
        require(state["status"] == "applied", "SmartTube transaction is not applied.")
        require(
            state["app"] == profile["smarttube"] and state["launcher"] == effective["launcher"],
            "SmartTube or launcher pin changed.",
        )
        require(
            state["config_applied"] == base64.b64encode(content(device, effective)).decode(),
            "Reapply the updated tile profile through smarttube-apply.",
        )
        verify(device, state)
        print("SmartTube APK, active launcher, HOME, and exact tile configuration verified.")
        return
    apk = artifact(profile)
    if operation == "plan":
        if path.exists():
            state = load(path, identity)
            require(state["status"] == "applied", "Restore or archive the SmartTube transaction.")
            require(
                state["app"] == profile["smarttube"] and state["launcher"] == effective["launcher"],
                "Restore before changing SmartTube or its launcher.",
            )
        else:
            device.require_private_launcher(PACKAGE)
            require(
                PACKAGE not in device.packages("-u"),
                "Refusing an existing or retained SmartTube installation.",
            )
        content(device, effective)
        print(
            "Install the pinned F-Droid app for user 0 without requesting runtime permission grants; update the active YouTube tile."
        )
        print(
            "Keep official YouTube, its data, and the Settings patch. Undo restores the exact prior tiles and removes only introduced SmartTube data."
        )
        return
    require(operation == "apply", "Unknown SmartTube operation.")
    with (directory / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        effective = active_profile(device, profile, identity, directory)
        apply(device, effective, identity, path, apk)
    print("SmartTube installed and the active YouTube tile updated; private undo record preserved.")
