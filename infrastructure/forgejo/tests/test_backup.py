import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('forgejo_backup', ROOT / 'kubernetes/apps/forgejo/backup/stage-forgejo.py')
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
    def test_synchronization_checks_contents_and_prunes_only_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / 'source', root / 'destination'
            source.mkdir()
            destination.mkdir()
            (source / 'repository').mkdir()
            (source / 'repository/data').write_bytes(b'new')
            (destination / 'repository').mkdir()
            (destination / 'repository/data').write_bytes(b'old')
            (destination / 'obsolete').write_text('delete from staging')
            (root / 'outside').write_text('preserve')
            (destination / 'link').symlink_to(root / 'outside')
            (source / 'link').write_text('regular file replaces symlink')
            backup.synchronize(source, destination)
            self.assertEqual((destination / 'repository/data').read_bytes(), b'new')
            self.assertFalse((destination / 'obsolete').exists())
            self.assertEqual((root / 'outside').read_text(), 'preserve')
            self.assertFalse((destination / 'link').is_symlink())

    def test_source_symlinks_are_copied_without_following_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / 'source', root / 'destination'
            source.mkdir()
            (source / 'link').symlink_to('../outside')
            backup.synchronize(source, destination)
            self.assertTrue((destination / 'link').is_symlink())
            self.assertEqual((destination / 'link').readlink(), Path('../outside'))

    def test_copy_and_validation_finish_before_application_resumes(self):
        api, events = API(), []
        def copy():
            self.assertEqual(api.replicas, 0)
            events.append('copy')
        backup.stage_and_resume(api, copy=copy, validate=lambda: events.append('validate'))
        self.assertEqual(events, ['copy', 'validate'])
        self.assertEqual(api.changes, [0, 1])
        self.assertEqual(api.replicas, 1)
        self.assertIsNone(api.marker)

    def test_copy_or_validation_failure_resumes_and_fails_the_hook(self):
        for operation in ['copy', 'validate']:
            api = API()
            def fail():
                raise backup.BackupError('fixture failure')
            with self.assertRaises(backup.BackupError):
                backup.stage_and_resume(api, copy=fail if operation == 'copy' else lambda: None,
                    validate=fail if operation == 'validate' else lambda: None)
            self.assertEqual(api.replicas, 1)

    def test_restart_during_copy_rejects_staging(self):
        api = API()
        def copy():
            api.replicas = 1
        with self.assertRaises(backup.BackupError):
            backup.stage_and_resume(api, copy=copy)

    def test_does_not_start_when_already_stopped(self):
        api = API()
        api.replicas = 0
        with self.assertRaises(backup.BackupError):
            backup.stage_and_resume(api)
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
