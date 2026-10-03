import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('prepare_connections', Path(__file__).parents[1] / 'prepare-kubernetes-secrets.py')
connections = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(connections)

SETTINGS = {'BACKUP_S3_BUCKET': 'fixture-bucket', 'BACKUP_S3_REGION': 'de',
            'BACKUP_S3_ENDPOINT': 'fixture.example', 'BACKUP_S3_ACCESS_KEY_ID': 'fixture-access-key',
            'BACKUP_S3_SECRET_ACCESS_KEY': 'fixture-secret-key', 'BACKUP_KOPIA_PASSWORD': 'fixture-password'}


class ConnectionTests(unittest.TestCase):
    def prepare(self, root, arguments, returncode=0):
        documents = []

        def encrypt(command, **kwargs):
            document = json.loads(kwargs['input'])
            documents.append(document)
            return SimpleNamespace(returncode=returncode, stdout='stringData:\n  KOPIA_PASSWORD: ENC[AES256_GCM,fixture]\n')

        with patch.object(connections, '__file__', str(root / 'infrastructure/backup/prepare-kubernetes-secrets.py')), \
                patch.dict(connections.os.environ, SETTINGS), \
                patch.object(connections.subprocess, 'run', side_effect=encrypt), \
                patch('sys.argv', ['prepare-kubernetes-secrets.py', *arguments]), \
                contextlib.redirect_stdout(io.StringIO()):
            connections.main()
        return documents

    def test_sonarr_connection_uses_media_and_preserves_existing_connections(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'kubernetes/apps/media/backup'
            directory.mkdir(parents=True)
            old = root / 'kubernetes/apps/home-assistant/backup/home-assistant-secret.sops.yaml'
            old.parent.mkdir(parents=True)
            old.write_text('existing encrypted connection')
            documents = self.prepare(root, ['--application', 'sonarr'])
            self.assertEqual(documents[0]['metadata'], {'name': 'sonarr-kopia', 'namespace': 'media'})
            self.assertEqual(documents[0]['stringData']['KOPIA_REPOSITORY'], 's3://fixture-bucket/pilot/sonarr')
            self.assertEqual(old.read_text(), 'existing encrypted connection')
            self.assertIn('ENC[AES256_GCM,', (directory / 'sonarr-secret.sops.yaml').read_text())

    def test_existing_target_and_duplicate_application_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'kubernetes/apps/media/backup/sonarr-secret.sops.yaml'
            target.parent.mkdir(parents=True)
            target.write_text('existing encrypted connection')
            with self.assertRaisesRegex(RuntimeError, 'already exist'):
                self.prepare(root, ['--application', 'sonarr'])
            with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
                self.prepare(root, ['--application', 'sonarr', '--application', 'sonarr'])
            self.assertEqual(target.read_text(), 'existing encrypted connection')

    def test_encryption_failure_writes_no_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'kubernetes/apps/media/backup/sonarr-secret.sops.yaml'
            target.parent.mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, 'SOPS encryption failed'):
                self.prepare(root, ['--application', 'sonarr'], returncode=1)
            self.assertFalse(target.exists())

    def test_nas_connection_preserves_s3_recovery_and_has_no_cloud_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'kubernetes/apps/media/backup'
            directory.mkdir(parents=True)
            cloud = directory / 'sonarr-secret.sops.yaml'
            cloud.write_text('existing S3 recovery connection')
            documents = self.prepare(root, ['--destination', 'nas', '--application', 'sonarr'])
            self.assertEqual(documents[0]['metadata']['name'], 'sonarr-kopia-nas')
            self.assertEqual(documents[0]['stringData']['KOPIA_REPOSITORY'], 'filesystem:///mnt/nas-repository')
            self.assertNotIn('AWS_ACCESS_KEY_ID', documents[0]['stringData'])
            self.assertEqual(cloud.read_text(), 'existing S3 recovery connection')


if __name__ == '__main__':
    unittest.main()
