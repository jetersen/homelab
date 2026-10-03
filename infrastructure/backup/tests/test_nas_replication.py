"""Verify NAS safety checks and real Kopia replication, pruning and recovery offline."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_pilot_file_selection as selection

IMAGE, ROOT = selection.IMAGE, selection.ROOT

SCRIPT = ROOT / 'kubernetes/components/application-backup/replicate.py'
SPEC = importlib.util.spec_from_file_location('nas_sync', SCRIPT)
nas = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nas)


class NASReplicationTests(unittest.TestCase):
    def test_unmounted_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            info = Path(temporary) / 'mountinfo'
            info.write_text('10 9 0:1 / /nas-repository rw - ext4 /dev/test rw\n')
            with self.assertRaises(nas.SyncError):
                nas.require_nfs(Path('/nas-repository'), info)
            info.write_text('10 9 0:1 / /nas-repository rw - nfs4 nas:/backup rw\n')
            nas.require_nfs(Path('/nas-repository'), info)

    def test_uninitialized_primary_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'existing').write_text('preserve')
            with self.assertRaises(nas.SyncError):
                nas.sync(directory, check_mount=lambda _: None)
            self.assertEqual((directory / 'existing').read_text(), 'preserve')

    def test_wrong_repository_is_rejected_before_sync_or_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'kopia.repository.f').write_bytes(b'other repository')
            environment = {'KOPIA_REPOSITORY': 's3://fixture/app',
                           'KOPIA_S3_ENDPOINT': 'fixture', 'AWS_REGION': 'fixture'}
            with patch.dict(os.environ, environment), patch.object(nas.subprocess, 'run') as run:
                run.return_value.returncode = 0
                run.side_effect = [type('Result', (), {'returncode': 0, 'stdout': output})() for output in [b'', b'', b'primary identity', b'other identity']]
                with self.assertRaises(nas.SyncError):
                    nas.sync(directory, directory / 'cache', check_mount=lambda _: None)
                self.assertEqual(run.call_count, 4)
                self.assertEqual((directory / 'kopia.repository.f').read_bytes(), b'other repository')

    def test_real_replica_retention_verification_and_restore(self):
        fixture = selection.FileSelectionTests()
        with tempfile.TemporaryDirectory(prefix='kopia-replica-') as temporary:
            folder = Path(temporary)
            environment = fixture.environment(folder, 'home-assistant')
            (folder / 'cache/replica').mkdir(parents=True)
            # Translate only the fixture's S3 connection to its offline filesystem
            # source. Sync, verification, retention and restore commands are real.
            adapter = """import os,runpy,subprocess
real_run=subprocess.run
def offline(args, **kwargs):
 if args[4:7]==['repository','connect','s3']:
  args=args[:4]+['repository','connect','filesystem','--readonly','--path=/replica']
 elif args[4:7]==['repository','sync-to','s3']:
  args=args[:4]+['repository','sync-to','filesystem','--path=/replica','--update','--delete','--must-exist']
 return real_run(args, **kwargs)
subprocess.run=offline
os.environ.update(KOPIA_REPOSITORY='s3://fixture/home-assistant',KOPIA_S3_ENDPOINT='fixture',AWS_REGION='fixture')
sync=runpy.run_path('/scripts/replicate.py')['sync']
sync(check_mount=lambda _:None)
"""
            for revision in range(5):
                archive = fixture.fixture(folder, 'home-assistant', revision)
                result = fixture.container(folder, 'home-assistant', environment + '/mover-kopia/entry.sh >/cache/mover.log 2>&1')
                self.assertEqual(result.returncode, 0)
                if revision == 0:
                    seeded = fixture.container(folder, 'home-assistant', environment + 'kopia --config-file=/cache/kopia.config --disable-file-logging repository sync-to filesystem --path=/cache/replica >/dev/null 2>&1')
                    self.assertEqual(seeded.returncode, 0)
                code = adapter
                command = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python3',
                           '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/cache',
                           '-e', 'KOPIA_PASSWORD=offline-test', '-e', 'KOPIA_CHECK_FOR_UPDATES=false',
                           '-v', f'{folder}/cache:/cache', '-v', f'{folder}/cache/repository:/mnt/nas-repository:ro',
                           '-v', f'{folder}/cache/replica:/replica',
                           '-v', f'{SCRIPT.parent}:/scripts:ro', IMAGE, '-c', code]
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            recovery = environment + '''
kopia --config-file=/cache/replication-target.config --disable-file-logging snapshot list home-assistant@homelab:/data --json >/cache/replica-snapshots.json
kopia --config-file=/cache/replication-target.config --disable-file-logging snapshot restore "$(jq -r '.[-1].id' /cache/replica-snapshots.json)" /cache/replica-restore >/dev/null 2>&1
'''
            # The replica is also mounted for this fresh recovery command.
            command = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', '/bin/bash',
                       '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/cache',
                       '-v', f'{folder}/cache:/cache', '-v', f'{folder}/cache/replica:/replica:ro',
                       IMAGE, '-c', recovery]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr[-1000:])
            self.assertEqual(len(json.loads((folder / 'cache/replica-snapshots.json').read_text())), 3)
            restored = folder / 'cache/replica-restore' / archive.relative_to(folder / 'data')
            self.assertEqual(restored.read_bytes(), archive.read_bytes())


if __name__ == '__main__':
    unittest.main()
