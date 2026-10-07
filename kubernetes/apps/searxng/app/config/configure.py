"""Apply managed settings while retaining the upstream-generated secret."""

import os
from pathlib import Path

import yaml


def configure(settings_path: Path, template_path: Path) -> None:
    if not settings_path.exists():
        # The upstream entrypoint generates the first settings file and secret.
        return

    current = yaml.safe_load(settings_path.read_text())
    desired = yaml.safe_load(template_path.read_text())
    secret = current["server"]["secret_key"]
    if not isinstance(secret, str) or len(secret) < 24 or secret == "ultrasecretkey":
        raise ValueError("Persistent application secret is missing or invalid")
    desired["server"]["secret_key"] = secret
    if current == desired:
        return

    temporary = settings_path.with_suffix(".tmp")
    with open(temporary, "w", opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
        yaml.safe_dump(desired, f, sort_keys=False)
    temporary.replace(settings_path)


if __name__ == "__main__":
    configure(Path("/etc/searxng/settings.yml"), Path("/config/settings.yml"))
