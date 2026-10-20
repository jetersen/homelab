# Android TV launcher

[profile.json](profile.json) configures the upstream
[dumbtv launcher](https://github.com/humblemuzzu/dumbtv/tree/90fa871149ec5897d1afd635d0e327ce672ab493/launcher).
Edit the appearance and ordered app candidates there. The first installed,
launchable candidate for each entry becomes a tile. Other apps remain installed
and can be made visible in the launcher's Options. Reapplying replaces those
local appearance and visibility choices.

Requires Python 3 and `adb`, an authorized debugging connection, Android TV 9 or
newer, with Android user 0 active. Other profiles are left unchanged; dumbtv must
not be installed for another user because its APK is shared. On NixOS, run the
commands inside `nix shell nixpkgs#android-tools`. For network debugging, use the address and port
shown by the device; wireless debugging may require `adb pair` before `adb connect`.
USB requires a data cable and a device port that actually exposes ADB.

```sh
python3 infrastructure/android-tv/manage.py fetch
python3 infrastructure/android-tv/manage.py plan
python3 infrastructure/android-tv/manage.py apply
python3 infrastructure/android-tv/manage.py verify
python3 infrastructure/android-tv/manage.py restore
```

Select a device with `--serial` when more than one is attached. `plan` reads the
TV without changing it. `fetch` downloads the pinned release and verifies its
SHA-256 without requiring a TV or an Android SDK. Missing apps are reported;
install them through the device's store and reapply.

Before changing the TV, `apply` saves the original HOME component, the previous
launcher configuration bytes or their absence, and whether dumbtv was already
installed. The private undo record lives under
`~/.local/state/homelab/android-tv/`, keyed by the hardware serial's hash.
Keep it until restoration is no longer needed. Use the same `--state-dir`
outside the repository on every command to override the default. Do not commit
device identifiers, undo records, or APKs. Reapplication preserves the original
baseline. After restoring, archive the record before starting a new baseline.

`restore` selects the original HOME and restores the original configuration. If
this tool introduced dumbtv, restoration removes it, including configuration
created since installation. Existing apps and their data are left alone.
An existing dumbtv installation must match the pinned APK; updates are refused
because ADB cannot reliably back up and restore its private app data. Firmware
changes also require review before using an older undo record.

Run the transaction regression tests with
`python3 -m unittest discover -s infrastructure/android-tv -p 'test_*.py'`.

This manages the launcher only. It does not run dumbtv's debloat or DNS scripts,
disable vendor packages, install browsers, or alter VPN configuration. Fire OS
needs a separate HOME hook and is refused. Some Android TV firmware ignores a
preferred HOME while the vendor launcher is enabled. If verification fails,
`apply` attempts restoration and retains the undo record. Investigate that model
before disabling packages. If USB disconnects or the process stops, reconnect
and run `restore`; an incomplete transaction blocks further applies.
