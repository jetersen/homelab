import importlib.util
import io
from pathlib import Path
import os
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('ha_staging', ROOT / 'kubernetes/apps/home-assistant/backup/stage-home-assistant.py')
staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(staging)


class StagingTests(unittest.TestCase):
    def archive(self, source, name, modified):
        path = source / name
        with tarfile.open(path, 'w') as output:
            member = tarfile.TarInfo('backup.json')
            content = name.encode()
            member.size = len(content)
            output.addfile(member, io.BytesIO(content))
        os.utime(path, (modified, modified))
        return path

    def test_only_latest_completed_archive_is_staged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.archive(root, 'old.tar', 1)
            latest = self.archive(root, 'Native backup with spaces.tar', 500)
            (root / 'live.db').write_bytes(b'never back up live database')
            destination = root / 'exports/backups/home-assistant.tar'
            staging.stage(root, destination, now=1000)
            self.assertEqual(destination.read_bytes(), latest.read_bytes())
            self.assertEqual([p.name for p in destination.parent.iterdir()], ['home-assistant.tar'])
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_in_progress_stale_and_excess_archives_are_rejected(self):
        for modified, count in [(900, 1), (1, 1), (500, 4)]:
            with self.subTest(modified=modified, count=count), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for index in range(count):
                    self.archive(root, f'{index}.tar', modified)
                with self.assertRaises(RuntimeError):
                    staging.stage(root, root / 'exports/latest.tar', now=200000 if modified==1 else 1000)
                self.assertFalse((root / 'exports/latest.tar').exists())

    def test_symlink_archive_and_invalid_tar_are_rejected(self):
        for symlink in [True, False]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = self.archive(root, 'original.bin', 500)
                if symlink:
                    (root / 'backup.tar').symlink_to(archive)
                else:
                    archive.rename(root / 'backup.tar')
                    (root / 'backup.tar').write_bytes(b'not a tar')
                    os.utime(root / 'backup.tar', (500, 500))
                with self.assertRaises((RuntimeError, tarfile.TarError)):
                    staging.stage(root, root / 'exports/latest.tar', now=1000)

    def test_failed_copy_preserves_previous_export_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.archive(root, 'backup.tar', 500)
            target = root / 'exports/backups/home-assistant.tar'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'previous export')
            with patch.object(staging.shutil, 'copyfileobj', side_effect=OSError('fixture')):
                with self.assertRaises(OSError):
                    staging.stage(root, target, now=1000)
            self.assertEqual(target.read_bytes(), b'previous export')
            self.assertEqual(list(target.parent.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
