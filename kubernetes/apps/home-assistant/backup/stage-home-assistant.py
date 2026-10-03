#!/usr/bin/env python3
"""Stage the newest completed Home Assistant native archive for Kopiur."""
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import time


def stage(source=Path('/data/backups'), destination=Path('/exports/backups/home-assistant.tar'), now=None):
    now = time.time() if now is None else now
    archives = list(source.glob('*.tar'))
    if not 1 <= len(archives) <= 3:
        raise RuntimeError('Expected one to three native archives; review native retention.')
    for archive in archives:
        if archive.is_symlink() or not archive.is_file() or not archive.stat().st_size:
            raise RuntimeError('Invalid native archive.')
        if now - archive.stat().st_mtime < 300:
            raise RuntimeError('A native archive is still being produced.')
    latest = max(archives, key=lambda archive: archive.stat().st_mtime)
    before = latest.stat()
    if now - before.st_mtime > 108000:
        raise RuntimeError('The newest native archive is stale.')
    with tarfile.open(latest) as archive:
        if not archive.getmembers():
            raise RuntimeError('The native archive is empty.')
    if destination.is_symlink() or destination.parent.is_symlink():
        raise RuntimeError('Invalid staging destination.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            with latest.open('rb') as archive:
                shutil.copyfileobj(archive, output)
        after = latest.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('Native archive changed while staging.')
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print('Completed native archive staged.')


if __name__ == '__main__':
    try:
        stage()
    except Exception:
        raise SystemExit('Native archive staging failed; diagnostics withheld.')
