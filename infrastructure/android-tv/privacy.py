"""Reversible, explicitly selected Android TV privacy and optional-app controls."""

import fcntl
import json
import re

from manage import require, save

# Privacy cleanup must not take over the launcher or disable functional dependencies.
PROTECTED = {
    "android",
    "com.android.systemui",
    "com.android.settings",
    "com.android.tv.settings",
    "com.android.tv",
    "com.android.bluetooth",
    "com.android.providers.settings",
    "com.google.android.gms",
    "com.google.android.gsf",
    "com.android.vending",
    "com.google.android.apps.mediashell",
    "com.google.android.tv.remote.service",
    "com.google.android.youtube.tv",
    "org.jellyfin.androidtv",
    "ch.protonvpn.android",
    "tv.dumbtv.home",
    "tv.homelab.youtube",
    "org.droidtv.upgradeapp",
    "org.droidtv.ambisvc",
    "org.droidtv.ambiair",
    "org.droidtv.channels",
    "org.droidtv.playtv",
    "org.droidtv.tvsystemui",
    "org.droidtv.bluetoothremote",
    "org.droidtv.tvpowermanagerservice",
    "org.droidtv.tv.tpvaudiomanager",
    "org.droidtv.tv.tpvvideomanager",
    "org.droidtv.tv.tpvbluetoothmanager",
    "org.droidtv.customautologservice",  # Also handles audio-DSP reset checks.
}
SCOPES = ("privacy", "philips")


def discover(device):
    pattern = re.compile(
        r"(^|\.)(ads?|adservices|advertising|analytics|telemetry|tracking|metrics|promo|feedback)"
        r"(\.|$)|samba|katniss|amazonalexa",
        re.IGNORECASE,
    )
    print("Read-only candidates; a name alone is not evidence to disable a package:")
    for package in sorted(device.packages()):
        if package not in PROTECTED and pattern.search(package):
            print(f"  {package}: {device.package_state(package)}")


def capture(device, policy, identity):
    packages = policy["disable_packages"]
    require(len(packages) == len(set(packages)), "Duplicate privacy package.")
    homes = {
        component.split("/")[0]
        for component in device.activities("android.intent.category.HOME", include_disabled=True)
    }
    require(
        not set(packages) & (PROTECTED | homes), "Privacy profile includes a protected package."
    )
    installed = device.packages()
    settings = policy.get("settings", [])
    require(
        all(
            item["namespace"] == "global"
            and item["key"] == "send_action_app_error"
            and item["value"] == "0"
            for item in settings
        ),
        "Unsupported privacy setting; review its API and rollback before adding it.",
    )
    return {
        "schema": 1,
        "identity": identity,
        "policy": policy,
        "packages": {p: device.package_state(p) for p in packages if p in installed},
        "missing": [p for p in packages if p not in installed],
        "settings": [
            {**item, "before": device.read_setting(item["namespace"], item["key"])}
            for item in settings
        ],
        "microphone_before": device.microphone_blocked()
        if policy.get("microphone_blocked") is not None
        else None,
        "status": "pending",
    }


def load(path, identity):
    state = json.loads(path.read_text())
    require(state["schema"] == 1, "Unsupported control undo record schema.")
    require(state["identity"] == identity, "Device or firmware differs from control undo record.")
    return state


def require_complete(directory, identity, *, exclude=None):
    for scope in SCOPES:
        path = directory / f"{scope}.json"
        if scope != exclude and path.exists():
            require(
                load(path, identity)["status"] in {"applied", "restored"},
                f"Restore the interrupted {scope} transaction first.",
            )


def require_separate(directory, identity, scope, policy):
    for peer in SCOPES:
        path = directory / f"{peer}.json"
        if peer != scope and path.exists():
            state = load(path, identity)
            if state["status"] != "restored":
                require(
                    not set(policy["disable_packages"]) & set(state["policy"]["disable_packages"]),
                    "Package already belongs to another active control transaction.",
                )


def verify(device, state):
    for package in state["packages"]:
        require(
            device.package_state(package) == "disabled-user", f"Disabled package differs: {package}"
        )
    require(
        not set(state["missing"]) & device.packages(), "A previously absent privacy app appeared."
    )
    for item in state["settings"]:
        require(
            device.read_setting(item["namespace"], item["key"]) == item["value"],
            "Privacy setting differs.",
        )
    if state["microphone_before"] is not None:
        require(
            device.microphone_blocked() == state["policy"]["microphone_blocked"],
            "Microphone privacy state differs.",
        )


def restore(device, state, path):
    for package, before in state["packages"].items():
        if device.package_state(package) != before:
            device.set_package_state(package, before)
    for item in state["settings"]:
        device.write_setting(item["namespace"], item["key"], item["before"])
    if state["microphone_before"] is not None:
        device.set_microphone_blocked(state["microphone_before"])
    state["status"] = "restored"
    save(path, state)


def apply(device, policy, identity, path):
    if path.exists():
        state = load(path, identity)
        require(
            state["status"] == "applied",
            f"Restore or archive the previous {path.stem} transaction.",
        )
        require(state["policy"] == policy, "Restore controls before changing its profile.")
    else:
        state = capture(device, policy, identity)
    state["status"] = "pending"
    save(path, state)
    try:
        for package in state["packages"]:
            device.set_package_state(package, "disabled-user")
        for item in state["settings"]:
            device.write_setting(item["namespace"], item["key"], item["value"])
        if state["microphone_before"] is not None:
            device.set_microphone_blocked(policy["microphone_blocked"])
        verify(device, state)
    except BaseException:
        print(f"{path.stem.capitalize()} apply failed; restoring the original controls.")
        restore(device, state, path)
        raise
    state["status"] = "applied"
    save(path, state)


def command(action, device, profile, identity, directory):
    if action == "discover":
        discover(device)
        return
    scope, operation = action.split("-", 1)
    require(scope in SCOPES, "Unknown package-control scope.")
    path = directory / f"{scope}.json"
    if operation in {"plan", "apply"}:
        policy = profile[scope]
        if scope == "philips":
            require(
                set(policy) == {"disable_packages"}, "Philips controls only disable selected apps."
            )
        require_complete(directory, identity, exclude=scope)
        require_separate(directory, identity, scope, policy)
    if operation == "plan":
        if path.exists():
            state = load(path, identity)
            require(state["status"] == "applied", "Restore or archive the control transaction.")
            require(state["policy"] == policy, "Restore controls before changing its profile.")
        else:
            state = capture(device, policy, identity)
        for package in state["packages"]:
            print(f"Disable for user 0, retaining data: {package}")
        for package in state["missing"]:
            print(f"Not installed; skip: {package}")
        if scope == "privacy":
            print("Apply configured crash-report and microphone controls; save exact undo state.")
        else:
            print("Save exact enabled states; do not uninstall apps or clear their data.")
        return
    if operation == "verify":
        state = load(path, identity)
        require(state["status"] == "applied", "Control transaction is not applied.")
        verify(device, state)
        print(f"{scope.capitalize()} controls verified.")
        return
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    with (directory / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if operation == "apply":
            require_complete(directory, identity, exclude=scope)
            require_separate(directory, identity, scope, policy)
            shortcut_path = directory / "youtube.json"
            if shortcut_path.exists():
                import youtube_shortcut

                require(
                    youtube_shortcut.load(shortcut_path, identity)["status"]
                    in {"applied", "restored"},
                    "Restore the interrupted shortcut transaction first.",
                )
            launcher = directory / "state.json"
            if launcher.exists():
                require(
                    json.loads(launcher.read_text())["status"] in {"applied", "restored"},
                    "Restore the interrupted launcher transaction first.",
                )
            apply(device, policy, identity, path)
            print(
                f"{scope.capitalize()} profile applied and verified; private undo state preserved."
            )
        else:
            restore(device, load(path, identity), path)
            print(f"Original {scope} controls restored.")
