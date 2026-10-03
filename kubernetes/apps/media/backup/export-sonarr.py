#!/usr/bin/env python3
"""Stage a fresh, validated native Sonarr backup without logging recovery data."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import zipfile


class ExportError(Exception):
    pass


def validate_archive(path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (len(names) != len(set(names)) or set(names) != {'config.xml', 'sonarr.db', 'INFO'}
                or any(entry.is_dir() or entry.file_size == 0 for entry in entries)
                or sum(entry.file_size for entry in entries) > 256 * 1024 * 1024):
            raise ExportError('Native archive has unexpected or missing recovery files.')
        if archive.testzip() is not None:
            raise ExportError('Native archive failed its CRC check.')
        config = ET.fromstring(archive.read('config.xml'))
        if config.tag != 'Config' or not config.findtext('ApiKey'):
            raise ExportError('Native archive configuration is invalid.')
        with tempfile.TemporaryDirectory(prefix='sonarr-validation-') as temporary:
            database = Path(temporary) / 'sonarr.db'
            database.write_bytes(archive.read('sonarr.db'))
            with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as connection:
                if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ExportError('Native database failed its integrity check.')
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'Series', 'Episodes', 'Config', 'VersionInfo'} <= tables:
                    raise ExportError('Native database is missing application tables.')


def export(config_path=Path('/config/config.xml'), output=Path('/exports/backups/sonarr.zip'),
           base_url='http://sonarr:8989'):
    key = ET.parse(config_path).getroot().findtext('ApiKey')
    if not key:
        raise ExportError('Sonarr API key is unavailable.')

    # Never forward the credential to an HTTP redirect target.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(path, payload=None, method=None):
        req = urllib.request.Request(base_url + path,
            method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'X-Api-Key': key, 'Content-Type': 'application/json'})
        with client.open(req, timeout=30) as response:
            body = response.read(64 * 1024 * 1024 + 1)
        if len(body) > 64 * 1024 * 1024:
            raise ExportError('Native backup response exceeds the size limit.')
        return json.loads(body) if body else None

    previous = {backup['id'] for backup in request('/api/v3/system/backup')}
    command = request('/api/v3/command', {'name': 'Backup'})
    command_id = command['id']
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        status = request(f'/api/v3/command/{command_id}')['status']
        if status == 'completed':
            break
        if status in {'failed', 'aborted', 'cancelled', 'orphaned'}:
            raise ExportError('Native Sonarr backup command failed.')
        time.sleep(2)
    else:
        raise ExportError('Native Sonarr backup command timed out.')

    fresh = [backup for backup in request('/api/v3/system/backup')
             if backup['id'] not in previous and backup['type'] == 'manual']
    if len(fresh) != 1:
        raise ExportError('Expected exactly one new completed native backup.')
    path = fresh[0]['path']
    name = fresh[0]['name']
    if (not name.startswith('sonarr_backup_') or not name.endswith('.zip')
            or '/' in name or '\\' in name or path != f'/backup/manual/{name}'):
        raise ExportError('Native backup download path is unexpected.')
    folder = Path(request('/api/v3/config/host')['backupFolder'])
    if not folder.is_absolute():
        folder = config_path.parent / folder
    native = folder / 'manual' / name
    if (not native.resolve().is_relative_to(config_path.parent.resolve())
            or native.is_symlink() or not native.is_file()
            or not 0 < native.stat().st_size <= 64 * 1024 * 1024):
        raise ExportError('Completed native archive is unavailable on the config volume.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.tmp', delete=False) as staging:
        temporary = Path(staging.name)
        os.chmod(temporary, 0o600)
        try:
            staging.write(native.read_bytes())
            staging.flush()
            os.fsync(staging.fileno())
            validate_archive(temporary)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    # This archive was created by this export, and its validated copy is staged.
    # Remove only that temporary native copy, never existing manual backups.
    request(f'/api/v3/system/backup/{fresh[0]["id"]}', method='DELETE')
    print('Validated native Sonarr configuration and database; staging archive replaced atomically.')


if __name__ == '__main__':
    try:
        export()
    except Exception as error:
        # URLs, HTTP responses, XML and SQLite errors may contain private data.
        if type(error) is ExportError:
            print(str(error))
        elif isinstance(error, urllib.error.HTTPError):
            print(f'Sonarr API request failed with HTTP {error.code}.')
        else:
            print(f'Sonarr export failed ({type(error).__name__}); diagnostic withheld.')
        raise SystemExit(1)
