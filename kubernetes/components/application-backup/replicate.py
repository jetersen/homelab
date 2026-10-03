#!/usr/bin/env python3
"""Replicate the primary NAS repository to its matching S3 destination."""
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit


class SyncError(Exception):
    pass


def require_nfs(path, mountinfo=Path('/proc/self/mountinfo')):
    for line in mountinfo.read_text().splitlines():
        fields, filesystem = line.split(' - ', 1)
        if fields.split()[4] == str(path) and filesystem.split()[0] in ['nfs', 'nfs4']:
            return
    raise SyncError('Primary repository is not mounted over NFS.')


def sync(repository=Path('/mnt/nas-repository'), cache=Path('/cache'), check_mount=require_nfs):
    os.umask(0o077)
    check_mount(repository)
    if repository.is_symlink() or not repository.is_dir():
        raise SyncError('NAS repository directory is invalid.')
    marker = repository / 'kopia.repository.f'
    if marker.is_symlink() or not marker.is_file():
        raise SyncError('Primary NAS repository has not been initialized.')
    destination = urlsplit(os.environ.get('KOPIA_S3_REPOSITORY', os.environ['KOPIA_REPOSITORY']))
    if destination.scheme != 's3' or not destination.netloc or not destination.path.strip('/'):
        raise SyncError('Expected an S3 destination with a dedicated prefix.')
    cache.mkdir(parents=True, exist_ok=True)
    source_config = cache / 'replication-source.config'
    target_config = cache / 'replication-target.config'
    limits = ['--content-cache-size-limit-mb=128', '--metadata-cache-size-limit-mb=64']

    def kopia(config, *args):
        result = subprocess.run(['kopia', '--config-file=' + str(config),
            '--disable-file-logging', '--no-progress', *args], capture_output=True, timeout=900)
        if result.returncode:
            (cache / 'replication-error.log').write_bytes(result.stdout + result.stderr)
            raise SyncError('Kopia replication or verification failed; diagnostic withheld.')
        return result.stdout

    kopia(source_config, 'repository', 'connect', 'filesystem', '--readonly',
          '--path=' + str(repository), '--cache-directory=' + str(cache / 'source-cache'), *limits)
    kopia(target_config, 'repository', 'connect', 's3', '--readonly',
          '--bucket=' + destination.netloc, '--prefix=' + destination.path.strip('/') + '/',
          '--endpoint=' + os.environ['KOPIA_S3_ENDPOINT'], '--region=' + os.environ['AWS_REGION'],
          '--cache-directory=' + str(cache / 'target-cache'), *limits)
    # Prevent pruning an S3 repository that belongs to another backup source.
    if kopia(source_config, 'blob', 'show', 'kopia.repository') != kopia(target_config, 'blob', 'show', 'kopia.repository'):
        raise SyncError('S3 repository identity differs from the NAS source.')
    kopia(source_config, 'snapshot', 'verify', '--verify-files-percent=100')
    kopia(source_config, 'repository', 'sync-to', 's3', '--bucket=' + destination.netloc,
          '--prefix=' + destination.path.strip('/') + '/', '--endpoint=' + os.environ['KOPIA_S3_ENDPOINT'],
          '--region=' + os.environ['AWS_REGION'], '--update', '--delete', '--must-exist')
    before = json.loads(kopia(source_config, 'snapshot', 'list', '--all', '--json'))
    after = json.loads(kopia(target_config, 'snapshot', 'list', '--all', '--json'))
    if {s['id'] for s in before} != {s['id'] for s in after}:
        raise SyncError('NAS and S3 snapshot inventories differ.')
    # Verify cloud metadata without downloading all archive contents on every run.
    kopia(target_config, 'snapshot', 'verify', '--verify-files-percent=0')
    print('S3 replica synchronized and snapshot metadata verified.')


if __name__ == '__main__':
    try:
        sync()
    except Exception as error:
        print(str(error) if type(error) is SyncError else 'Repository replication failed; diagnostic withheld.')
        raise SystemExit(1)
