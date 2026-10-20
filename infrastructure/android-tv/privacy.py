"""Reversible, explicitly selected Android TV privacy controls."""

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
    "org.droidtv.upgradeapp",
}


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
    require(state["schema"] == 1, "Unsupported privacy undo record schema.")
    require(state["identity"] == identity, "Device or firmware differs from privacy undo record.")
    return state


def verify(device, state):
    for package in state["packages"]:
        require(
            device.package_state(package) == "disabled-user", f"Privacy package differs: {package}"
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
            state["status"] == "applied", "Restore or archive the previous privacy transaction."
        )
        require(state["policy"] == policy, "Restore privacy before changing its profile.")
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
        print("Privacy apply failed; restoring the original privacy controls.")
        restore(device, state, path)
        raise
    state["status"] = "applied"
    save(path, state)


def command(action, device, profile, identity, directory):
    path = directory / "privacy.json"
    if action == "discover":
        discover(device)
        return
    policy = profile["privacy"]
    if action == "privacy-plan":
        if path.exists():
            state = load(path, identity)
            require(state["status"] == "applied", "Restore or archive the privacy transaction.")
            require(state["policy"] == policy, "Restore privacy before changing its profile.")
        else:
            state = capture(device, policy, identity)
        for package in state["packages"]:
            print(f"Disable for user 0, retaining data: {package}")
        for package in state["missing"]:
            print(f"Not installed; skip: {package}")
        print("Apply configured crash-report and microphone controls; save exact undo state.")
        return
    if action == "privacy-verify":
        state = load(path, identity)
        require(state["status"] == "applied", "Privacy transaction is not applied.")
        verify(device, state)
        print("Privacy package, setting, and microphone states verified.")
        return
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    with (directory / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if action == "privacy-apply":
            launcher = directory / "state.json"
            if launcher.exists():
                require(
                    json.loads(launcher.read_text())["status"] in {"applied", "restored"},
                    "Restore the interrupted launcher transaction first.",
                )
            apply(device, policy, identity, path)
            print("Privacy profile applied and verified; private undo state preserved.")
        else:
            restore(device, load(path, identity), path)
            print("Original privacy package, setting, and microphone states restored.")
