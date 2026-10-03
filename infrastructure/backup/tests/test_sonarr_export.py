import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('sonarr_export', ROOT / 'kubernetes/apps/media/backup/export-sonarr.py')
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def native_archive(folder, extra=False, corrupt=False):
    database = folder / 'fixture.db'
    with contextlib.closing(sqlite3.connect(database)) as connection, connection:
        for name in ['Series', 'Episodes', 'Config', 'VersionInfo']:
            connection.execute(f'CREATE TABLE IF NOT EXISTS {name} (Id INTEGER)')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('config.xml', '<Config><ApiKey>fixture-key</ApiKey></Config>')
        archive.writestr('sonarr.db', b'broken database' if corrupt else database.read_bytes())
        archive.writestr('INFO', 'v4.0.20.3014\nfixture')
        if extra:
            archive.writestr('logs/sonarr.txt', 'should not be backed up')
    return output.getvalue()


class ExportTests(unittest.TestCase):
    def run_export(self, folder, archive, *, stale=False, status='completed', download_path=None):
        config = folder / 'config.xml'
        config.write_text('<Config><ApiKey>fixture-key</ApiKey></Config>')
        target = folder / 'backups/sonarr.zip'
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'previous validated export')
        before = {'id': 1, 'type': 'manual', 'name': 'sonarr_backup_old.zip',
                  'path': '/backup/manual/sonarr_backup_old.zip'}
        fresh = {'id': 2, 'type': 'manual', 'name': 'sonarr_backup_new.zip',
                 'path': download_path or '/backup/manual/sonarr_backup_new.zip'}
        inventory_calls = 0
        requests = []

        def open_request(request, **kwargs):
            nonlocal inventory_calls
            requests.append(request)
            self.assertEqual(request.get_header('X-api-key'), 'fixture-key')
            self.assertNotIn('fixture-key', request.full_url)
            if request.full_url.endswith('/api/v3/system/backup'):
                inventory_calls += 1
                body = [before] if inventory_calls == 1 or stale else [fresh, before]
            elif request.full_url.endswith('/api/v3/command'):
                self.assertEqual(json.loads(request.data), {'name': 'Backup'})
                body = {'id': 42}
            elif request.full_url.endswith('/api/v3/command/42'):
                body = {'status': status}
            else:
                return io.BytesIO(archive)
            return io.BytesIO(json.dumps(body).encode())

        with patch.object(exporter.urllib.request.OpenerDirector, 'open', side_effect=open_request), \
                contextlib.redirect_stdout(io.StringIO()):
            exporter.export(config, target, 'http://sonarr:8989')
        return target, requests

    def test_fresh_native_backup_is_validated_and_staged_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            archive = native_archive(folder)
            target, requests = self.run_export(folder, archive)
            self.assertEqual(target.read_bytes(), archive)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(target.parent.glob('*.tmp')), [])
            self.assertEqual(len(requests), 5)

    def test_invalid_archive_preserves_previous_export(self):
        for kwargs in [{'extra': True}, {'corrupt': True}]:
            with self.subTest(**kwargs), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                with self.assertRaises((exporter.ExportError, sqlite3.DatabaseError)):
                    self.run_export(folder, native_archive(folder, **kwargs))
                self.assertEqual((folder / 'backups/sonarr.zip').read_bytes(), b'previous validated export')
                self.assertEqual(list((folder / 'backups').glob('*.tmp')), [])

    def test_stale_failed_and_redirected_downloads_are_rejected(self):
        for kwargs in [{'stale': True}, {'status': 'failed'}, {'download_path': '//outside.test/archive.zip'}]:
            with self.subTest(**kwargs), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                with self.assertRaises(exporter.ExportError):
                    self.run_export(folder, native_archive(folder), **kwargs)
                self.assertEqual((folder / 'backups/sonarr.zip').read_bytes(), b'previous validated export')


if __name__ == '__main__':
    unittest.main()
