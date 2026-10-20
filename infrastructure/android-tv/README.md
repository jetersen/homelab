# Android TV launcher

[profile.json](profile.json) configures the upstream
[dumbtv launcher](https://github.com/humblemuzzu/dumbtv/tree/90fa871149ec5897d1afd635d0e327ce672ab493/launcher).
Edit the appearance and ordered app candidates there. The first installed,
launchable candidate for each entry becomes a tile. Other apps remain installed
and can be made visible in the launcher's Options. Reapplying replaces those
local appearance and visibility choices.

Requires Python 3 and `adb`, an authorized debugging connection, Android TV 9 or
newer, with Android user 0 active. Launcher and package changes target user 0;
dumbtv must not be installed for another user because its APK is shared. On NixOS, run the
commands inside `nix shell nixpkgs#android-tools`. For network debugging, use the
address and port shown by the device; wireless debugging may require `adb pair`
before `adb connect`.
USB requires a data cable and a device port that actually exposes ADB.

```sh
python3 infrastructure/android-tv/manage.py fetch
python3 infrastructure/android-tv/manage.py plan
python3 infrastructure/android-tv/manage.py apply
python3 infrastructure/android-tv/manage.py verify
python3 infrastructure/android-tv/manage.py restore
```

Privacy changes use a separate transaction so they can be undone while keeping
the launcher. Review `privacy` in the profile and the plan before applying:

```sh
python3 infrastructure/android-tv/manage.py discover
python3 infrastructure/android-tv/manage.py privacy-plan
python3 infrastructure/android-tv/manage.py privacy-apply
python3 infrastructure/android-tv/manage.py privacy-verify
python3 infrastructure/android-tv/manage.py privacy-restore
```

`discover` prints possible candidates without saving an inventory or changing
the device. A matching name does not establish a package's purpose or safety.
The privacy profile disables only explicitly selected packages for user 0,
retaining their data. It can also disable app-error reporting and block the
microphone through Android's software privacy toggle. These controls do not
prevent all telemetry from retained apps or change online account preferences.
The app-error reporting toggle is device-wide. Microphone privacy targets user 0
and requires Android 12 or newer with a supported sensor privacy implementation.
The private `privacy.json` undo record preserves exact original enabled states,
settings including absence, and microphone privacy. Reapplication keeps that
baseline; restore privacy before changing its profile. Archive a restored record
before starting a new transaction. The full `restore` command undoes privacy
along with optional-app controls, then restores the original launcher.

The separate `philips` profile selects optional manufacturer apps. Review the
packages for the device and firmware before applying; a Philips package can
also provide hardware support. Disabling Help removes manufacturer tutorials
and diagnostics. Ambient artwork and sunrise-alarm apps are separate from the
core Ambilight services. Keep audio recovery, inputs, power, remote-control,
and update services enabled.

```sh
python3 infrastructure/android-tv/manage.py philips-plan
python3 infrastructure/android-tv/manage.py philips-apply
python3 infrastructure/android-tv/manage.py philips-verify
python3 infrastructure/android-tv/manage.py philips-restore
```

This uses the same package-state transaction mechanism, with an independent
private `philips.json` undo record. Apps and their data stay installed; restore
returns each package to its exact original enabled state. Reapplication preserves
the first baseline. Restore and archive that record before changing the package
list. Active privacy and optional-app transactions cannot own the same package.
`philips-restore` keeps the launcher and privacy controls; full `restore` also
undoes the optional-app controls.

Select a device with `--serial` when more than one is attached. `plan` reads the
TV without changing it. `fetch` downloads the pinned release and verifies its
SHA-256 without requiring a TV or an Android SDK. Missing apps are reported;
install them through the device's store and reapply.

The optional YouTube shortcut opens the installed app's Subscriptions feed with
an `ACTION_VIEW` intent. The forwarding app requests no permissions and has no
services. It does not contain an account identifier. YouTube controls account
selection and may still show a chooser; a deep link is not a guarantee against
future app changes. The pinned launcher has no per-app intent override, so the
profile prefers the forwarding tile when installed and otherwise uses YouTube.

Build locally with JDK 17+ and Android SDK platform/build-tools 34, then review
the device plan:

```sh
nix-shell infrastructure/android-tv/youtube-shortcut/shell.nix --run \
  'python3 infrastructure/android-tv/manage.py youtube-artwork'
nix-shell infrastructure/android-tv/youtube-shortcut/shell.nix --run \
  'python3 infrastructure/android-tv/manage.py youtube-build'
python3 infrastructure/android-tv/manage.py youtube-plan
python3 infrastructure/android-tv/manage.py youtube-apply
python3 infrastructure/android-tv/manage.py youtube-verify
python3 infrastructure/android-tv/manage.py youtube-restore
```

Use `--sdk` to select an existing SDK instead. APKs and build checksums stay in
`~/.cache/homelab/android-tv/youtube-shortcut/`. `youtube-artwork` reads the
installed YouTube APK and copies its banner and icon into that private cache;
neither the artwork nor the original APK is committed. Keep the private signing
key and its password under `~/.local/state/homelab/android-tv/signing/` together;
they are needed to reproduce the app's signing identity. Do not put signing material
in a Nix derivation or repository. The device's `youtube.json` undo record saves
the exact prior launcher configuration before installing anything. Existing or
retained copies of the helper are refused, as are APK updates. Restore and
archive a restored record before changing the helper. `youtube-restore` restores
the previous tiles and removes only the forwarding app introduced by this tool.
The full `restore` also undoes the shortcut. YouTube and its data remain installed.

Before changing the TV, `apply` saves the original HOME component, the previous
launcher configuration bytes or their absence, and whether dumbtv was already
installed. The private undo record lives under
`~/.local/state/homelab/android-tv/`, keyed by the hardware serial's hash.
Keep it until restoration is no longer needed. Use the same `--state-dir`
outside the repository on every command to override the default. Do not commit
device identifiers, undo records, or APKs. Reapplication preserves the original
baseline. After restoring, archive the record before starting a new baseline.

Some firmware ignores HOME selection while its original launcher is enabled.
The optional `home_fallback.disable_packages` must include the original HOME
package and may include explicitly selected HOME recovery handlers. Complete
TV setup first. If selection fails, the tool disables only those packages for
user 0, retaining their app data and installations for restoration. The undo
record preserves each package's original enabled state; restoration puts those
states back before selecting HOME. Other profiles keep their handlers enabled.
Remove this fallback from the profile on devices that do not require it.

`restore` selects the original HOME and restores the original configuration. If
this tool introduced dumbtv, restoration removes it, including configuration
created since installation. Existing apps and their data are left alone.
An existing dumbtv installation must match the pinned APK; updates are refused
because ADB cannot reliably back up and restore its private app data. Firmware
changes also require review before using an older undo record.

Run the transaction regression tests with
`python3 -m unittest discover -s infrastructure/android-tv -p 'test_*.py'`.

This does not run dumbtv's debloat or DNS scripts, uninstall existing apps,
disable unrelated packages, install browsers, or alter DNS or VPN configuration.
Fire OS needs a separate HOME hook and is refused. If verification fails,
`apply` attempts restoration and retains the undo record. If the connection drops
or the process stops, reconnect and run `restore`; an incomplete transaction
blocks further applies.
