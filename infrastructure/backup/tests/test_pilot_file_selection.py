"""Exercise pinned Kopia selection, retention, guards and isolated restores offline."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import unittest
import zipfile
import yaml

from test_sonarr_export import native_archive

ROOT = Path(__file__).resolve().parents[3]
IMAGE = 'ghcr.io/perfectra1n/volsync:0.17.11@sha256:79674d3c48685e21cadaac8e0afd14268130a0a51a10c41a9dd65096c1434a0f'


class FileSelectionTests(unittest.TestCase):
    def fixture(self, folder, application, revision=0):
        data = folder / 'data'
        (data / 'backups/nested').mkdir(parents=True, exist_ok=True)
        (folder / 'cache').mkdir(exist_ok=True)
        if application == 'home-assistant':
            archive = data / 'backups/Automatic backup v2026.9.4.tar'
            with tarfile.open(archive, 'w') as output:
                payload = json.dumps({'fixture': revision}).encode()
                member = tarfile.TarInfo('backup.json')
                member.size = len(payload)
                output.addfile(member, io.BytesIO(payload))
            modified = time.time() - 600 + revision
            os.utime(archive, (modified, modified))
            for name in ['older-1.tar', 'older-2.tar']:
                older = archive.parent / name
                older.write_bytes(archive.read_bytes())
                os.utime(older, (0, 0))
        elif application == 'sonarr':
            archive = data / 'backups/sonarr.zip'
            archive.write_bytes(native_archive(folder))
            with zipfile.ZipFile(archive, 'a') as output:
                output.comment = str(revision).encode()
        else:
            archive = data / 'backups/zigbee2mqtt.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('configuration.yaml', 'version: 4')
        for name in ['application.log', 'live.db', '.hidden', 'backups/partial.tmp',
                     'backups/nested/wrong.zip', 'backups/unwanted.zip']:
            (data / name).write_text('excluded fixture')
        return archive

    def container(self, folder, application, script):
        command = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', '/bin/bash',
                   '--user', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/cache',
                   '-v', f'{folder}/data:/data:ro', '-v', f'{folder}/cache:/cache',
                   '-v', f'{folder}/config:/kopia-config:ro',
                   IMAGE, '-c', script]
        return subprocess.run(command, capture_output=True, text=True)

    def environment(self, folder, application):
        namespace = 'media' if application == 'sonarr' else 'home-assistant'
        backup = ROOT / f'kubernetes/apps/{namespace}/backup'
        rendered = subprocess.run(['kustomize', 'build', str(backup)], capture_output=True, text=True, check=True)
        resources = list(yaml.safe_load_all(rendered.stdout))
        config = next(item['data'] for item in resources
                      if item['kind'] == 'ConfigMap' and item['metadata']['name'] == f'{application}-backup-policy')
        (folder / 'config').mkdir()
        for name, contents in config.items():
            (folder / 'config' / name).write_text(contents)
        policy = json.loads(config['policy.json'])['(global)']
        retention = policy['retention']
        suffix = '' if application == 'sonarr' else f' {application}'
        settings = {'HOURLY': 'keepHourly', 'DAILY': 'keepDaily', 'WEEKLY': 'keepWeekly',
                    'MONTHLY': 'keepMonthly', 'YEARLY': 'keepAnnual', 'LATEST': 'keepLatest'}
        source = next(item for item in resources
                      if item['kind'] == 'ReplicationSource' and item['metadata']['name'] == f'{application}-backup')
        self.assertEqual(source['spec']['kopia']['retain'],
                         {name.lower(): retention[key] for name, key in settings.items()})
        variables = '\n'.join(f'export KOPIA_RETAIN_{name}={retention[key]}' for name, key in settings.items())
        return f'''set -e
export KOPIA_PASSWORD=offline-test KOPIA_CACHE_DIR=/cache KOPIA_CONFIG_PATH=/kopia-config KOPIA_CHECK_FOR_UPDATES=false
export DIRECTION=source DATA_DIR=/data KOPIA_REPOSITORY=filesystem:///cache/repository
export KOPIA_OVERRIDE_USERNAME={application} KOPIA_OVERRIDE_HOSTNAME=homelab
export KOPIA_GLOBAL_POLICY_FILE=/kopia-config/global-policy.json
{variables}
export KOPIA_BEFORE_SNAPSHOT='bash /kopia-config/check-source.sh{suffix}'
'''

    def test_selection_restore_and_latest_three_pruning(self):
        for application in ['home-assistant', 'zigbee2mqtt', 'sonarr']:
            with self.subTest(application=application), tempfile.TemporaryDirectory(prefix='kopia-offline-') as temporary:
                folder = Path(temporary)
                environment = self.environment(folder, application)
                runs = 2 if application == 'zigbee2mqtt' else 5
                for revision in range(runs):
                    archive = self.fixture(folder, application, revision)
                    result = self.container(folder, application, environment + '/mover-kopia/entry.sh >/cache/mover.log 2>&1')
                    self.assertEqual(result.returncode, 0, result.stderr[-1000:])
                inspect = environment + f'''
kopia --config-file=/cache/kopia.config --disable-file-logging snapshot list {application}@homelab:/data --json >/cache/snapshots.json
kopia --config-file=/cache/kopia.config --disable-file-logging snapshot restore "$(jq -r '.[-1].id' /cache/snapshots.json)" /cache/restore >/dev/null 2>&1
'''
                result = self.container(folder, application, inspect)
                self.assertEqual(result.returncode, 0, result.stderr[-1000:])
                snapshots = json.loads((folder / 'cache/snapshots.json').read_text())
                if application != 'zigbee2mqtt':
                    self.assertEqual(len(snapshots), 3)
                restored = folder / 'cache/restore'
                files = sorted(item.relative_to(restored).as_posix() for item in restored.rglob('*') if item.is_file())
                expected = archive.relative_to(folder / 'data').as_posix()
                self.assertEqual(files, [expected])
                self.assertEqual((restored / expected).read_bytes(), archive.read_bytes())
                self.assertEqual(snapshots[-1]['rootEntry']['summ']['numFailed'], 0)
                maintenance = environment + f'''
export DIRECTION=maintenance KOPIA_OVERRIDE_MAINTENANCE_USERNAME={application}@homelab
export KOPIA_GLOBAL_POLICY_FILE=/no-policy-file
/mover-kopia/entry.sh >/cache/maintenance.log 2>&1
'''
                result = self.container(folder, application, maintenance)
                self.assertEqual(result.returncode, 0, result.stderr[-1000:])
                self.assertIn('OPERATION_RESULT: SUCCESS', (folder / 'cache/maintenance.log').read_text())

    def test_accumulating_home_assistant_archives_and_stale_sonarr_are_rejected(self):
        for application in ['home-assistant', 'sonarr']:
            with self.subTest(application=application), tempfile.TemporaryDirectory(prefix='kopia-guard-') as temporary:
                folder = Path(temporary)
                archive = self.fixture(folder, application)
                environment = self.environment(folder, application)
                result = self.container(folder, application, environment + '/mover-kopia/entry.sh >/cache/initial.log 2>&1')
                self.assertEqual(result.returncode, 0)
                if application == 'home-assistant':
                    for name in ['extra-1.tar', 'extra-2.tar', 'extra-3.tar']:
                        (archive.parent / name).write_bytes(archive.read_bytes())
                else:
                    os.utime(archive, (0, 0))
                result = self.container(folder, application, environment + '/mover-kopia/entry.sh >/cache/rejected.log 2>&1')
                self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
