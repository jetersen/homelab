import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('forgejo_backup', ROOT / 'kubernetes/apps/forgejo/backup/backup.py')
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


class API:
    def __init__(self):
        self.replicas = 1
        self.marker = None
        self.changes = []

    def deployment(self):
        return {'metadata': {'resourceVersion': '7', 'annotations': {backup.PAUSE: self.marker}},
                'spec': {'replicas': self.replicas}, 'status': {'availableReplicas': self.replicas}}

    def patch(self, current, replicas, marker):
        self.replicas, self.marker = replicas, marker
        self.changes.append(replicas)

    def pods(self, current):
        return [] if self.replicas == 0 else [{}]


class BackupTests(unittest.TestCase):
    def test_copies_while_stopped_and_uploads_after_available(self):
        api, events = API(), []
        def copy():
            self.assertEqual(api.replicas, 0)
            events.append('copy')
        def upload():
            self.assertEqual(api.replicas, 1)
            self.assertIsNone(api.marker)
            events.append('upload')
        backup.stage_and_upload(api, copy=copy, validate=lambda: events.append('validate'), upload=upload)
        self.assertEqual(events, ['copy', 'validate', 'upload'])
        self.assertEqual(api.changes, [0, 1])

    def test_copy_or_validation_failure_resumes_without_upload(self):
        for operation in ['copy', 'validate']:
            api, uploaded = API(), []
            def fail():
                raise backup.BackupError('fixture failure')
            with self.assertRaises(backup.BackupError):
                backup.stage_and_upload(api, copy=fail if operation == 'copy' else lambda: None,
                    validate=fail if operation == 'validate' else lambda: None,
                    upload=lambda: uploaded.append(True))
            self.assertEqual(api.replicas, 1)
            self.assertFalse(uploaded)

    def test_restart_during_copy_rejects_snapshot(self):
        api, uploaded = API(), []
        def copy():
            api.replicas = 1
        with self.assertRaises(backup.BackupError):
            backup.stage_and_upload(api, copy=copy, upload=lambda: uploaded.append(True))
        self.assertFalse(uploaded)

    def test_does_not_start_when_already_stopped(self):
        api = API()
        api.replicas = 0
        with self.assertRaises(backup.BackupError):
            backup.stage_and_upload(api)
        self.assertFalse(api.changes)

    def test_watchdog_only_resumes_expired_owned_pause(self):
        api = API()
        api.replicas = 0
        api.marker = json.dumps({'id': 'fixture', 'started': 100})
        backup.recover(api, now=200)
        self.assertEqual(api.replicas, 0)
        backup.recover(api, now=1700)
        self.assertEqual(api.replicas, 1)

    def test_refuses_unrecognized_or_symlink_staging_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local, nas, stage = [root / name for name in ['local', 'nas', 'stage']]
            for path in [local, nas, stage]:
                path.mkdir()
            (local / 'gitea/conf').mkdir(parents=True)
            (local / 'gitea/conf/app.ini').touch()
            (local / 'gitea/forgejo.db').touch()
            with patch.multiple(backup, LOCAL=local, NAS=nas, STAGE=stage), patch.object(backup, 'require_nfs'):
                (stage / 'unrelated').touch()
                with self.assertRaises(backup.BackupError):
                    backup.require_layout()
                (stage / 'unrelated').unlink()
                backup.require_layout()
                (stage / 'current/nas').rmdir()
                (stage / 'current/nas').symlink_to(nas, target_is_directory=True)
                with self.assertRaises(backup.BackupError):
                    backup.require_layout()

    def test_local_integrity_validation_accepts_database_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            stage, cache = Path(directory) / 'stage', Path(directory) / 'cache'
            db = stage / 'current/local/gitea/forgejo.db'
            db.parent.mkdir(parents=True)
            cache.mkdir()
            with sqlite3.connect(db) as connection:
                connection.execute('CREATE TABLE fixture (id INTEGER)')
            with patch.multiple(backup, STAGE=stage, CACHE=cache):
                backup.validate_database()
                db.write_bytes(b'invalid SQLite')
                with self.assertRaises(sqlite3.DatabaseError):
                    backup.validate_database()

    def test_require_nfs_rejects_ordinary_directory(self):
        with self.assertRaises(backup.BackupError):
            backup.require_nfs(Path('/tmp'))


if __name__ == '__main__':
    unittest.main()
