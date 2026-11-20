"""Install checksum-pinned binaries and maintained user services on Linux amd64."""

import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path


def main():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Release pins target Linux amd64")
    os.umask(0o077)
    source = Path(__file__).parent
    destination = Path.home() / ".local/share/agent-observability"
    (destination / "bin").mkdir(parents=True, exist_ok=True)
    for name, release in json.loads((source / "releases.json").read_text()).items():
        with urllib.request.urlopen(release["url"], timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != release["sha256"]:
            raise RuntimeError(f"{name} release checksum mismatch")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            entries = [m for m in archive.getmembers() if m.isfile() and Path(m.name).name == name]
            if len(entries) != 1:
                raise RuntimeError(f"Unexpected {name} archive layout")
            target = destination / "bin" / name
            temporary = target.with_suffix(".new")
            with temporary.open("wb") as output:
                shutil.copyfileobj(archive.extractfile(entries[0]), output)
            temporary.chmod(0o700)
            temporary.replace(target)
    for name in ["t3_search.py", "backup.py"]:
        shutil.copy2(source / name, destination / name)
    units = Path.home() / ".config/systemd/user"
    units.mkdir(parents=True, exist_ok=True)
    for unit in [*source.glob("*.service"), *source.glob("*.timer")]:
        shutil.copy2(unit, units / unit.name)
    data = Path("/media/games/agent-observability/search")
    data.mkdir(parents=True, exist_ok=True)
    if not (data / "config.toml").exists():
        shutil.copy2(source / "agentsview.toml", data / "config.toml")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print(
        "Installed agent binaries and services; review storage and initialize backups before enabling"
    )


if __name__ == "__main__":
    main()
