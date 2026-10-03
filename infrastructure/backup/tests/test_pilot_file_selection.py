"""Exercise the actual pinned Kopia binary, source guard, and an isolated restore offline."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / 'kubernetes/apps/home-assistant/backup'
IMAGE = 'ghcr.io/perfectra1n/volsync:0.17.11@sha256:79674d3c48685e21cadaac8e0afd14268130a0a51a10c41a9dd65096c1434a0f'


class FileSelectionTests(unittest.TestCase):
    def test_archive_selection_and_restore_for_both_applications(self):
        for application, extension in [('home-assistant', 'tar'), ('zigbee2mqtt', 'zip')]:
            with self.subTest(application=application), tempfile.TemporaryDirectory(prefix='kopia-offline-') as temporary:
                folder = Path(temporary)
                data = folder / 'data'
                (data / 'backups/nested').mkdir(parents=True)
                (folder / 'cache').mkdir()
                archive = data / f'backups/ready.{extension}'
                if extension == 'tar':
                    with tarfile.open(archive, 'w') as output:
                        payload = b'{"fixture":true}'
                        member = tarfile.TarInfo('backup.json'); member.size = len(payload)
                        output.addfile(member, io.BytesIO(payload))
                    os.utime(archive, (0, 0))
                else:
                    archive = data / 'backups/zigbee2mqtt.zip'
                    with zipfile.ZipFile(archive, 'w') as output:
                        output.writestr('configuration.yaml', 'version: 4')
                for name in ['home-assistant.log', 'home-assistant_v2.db', '.hidden',
                             'backups/partial.tmp', f'backups/nested/wrong.{extension}']:
                    (data / name).write_text('excluded fixture')
                command = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', '/bin/bash',
                           '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/cache',
                           '-v', f'{data}:/data:ro', '-v', f'{folder}/cache:/cache',
                           '-v', f'{BACKUP}/check-source.sh:/kopia-config/check-source.sh:ro',
                           '-v', f'{BACKUP}/{application}-policy.json:/kopia-config/policy.json:ro', IMAGE,
                           '-c', f'''set -e
export KOPIA_PASSWORD=offline-test KOPIA_CACHE_DIR=/cache KOPIA_CONFIG_PATH=/kopia-config KOPIA_CHECK_FOR_UPDATES=false
export DIRECTION=source DATA_DIR=/data KOPIA_REPOSITORY=filesystem:///cache/repository
export KOPIA_OVERRIDE_USERNAME={application} KOPIA_OVERRIDE_HOSTNAME=homelab
export KOPIA_BEFORE_SNAPSHOT='bash /kopia-config/check-source.sh {application}'
/mover-kopia/entry.sh >/cache/mover-first.log 2>&1
/mover-kopia/entry.sh >/cache/mover-second.log 2>&1
kopia --config-file=/cache/kopia.config --disable-file-logging snapshot list {application}@homelab:/data --json | jq '.[0]' >/cache/snapshot.json
kopia --config-file=/cache/kopia.config --disable-file-logging snapshot restore "$(jq -r .id /cache/snapshot.json)" /cache/restore >/dev/null 2>&1
''']
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[-1000:])
                restored = folder / 'cache/restore'
                files = sorted(item.relative_to(restored).as_posix() for item in restored.rglob('*') if item.is_file())
                expected = archive.relative_to(data).as_posix()
                self.assertEqual(files, [expected])
                self.assertEqual((restored / expected).read_bytes(), archive.read_bytes())
                manifest = json.loads((folder / 'cache/snapshot.json').read_text())
                self.assertEqual(manifest['rootEntry']['summ']['numFailed'], 0)


if __name__ == '__main__':
    unittest.main()
