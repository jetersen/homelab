#!/usr/bin/env python3
"""Stage a stopped Forgejo instance, resume it, then snapshot both stores to S3."""
import argparse
import json
import os
from pathlib import Path
import signal
import shutil
import sqlite3
import ssl
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

PAUSE = 'backup.jetersen.dev/forgejo-pause'
LOCAL = Path('/source/local')
NAS = Path('/source/nas')
STAGE = Path('/stage')
CACHE = Path('/cache')


class BackupError(Exception):
    pass


class Kubernetes:
    def __init__(self):
        credentials = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.namespace = (credentials / 'namespace').read_text().strip()
        self.token = (credentials / 'token').read_text().strip()
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl.create_default_context(
                cafile=str(credentials / 'ca.crt'))))

    def request(self, resource, payload=None, query=''):
        group = 'api/v1' if resource == 'pods' else 'apis/apps/v1'
        url = f'https://kubernetes.default.svc/{group}/namespaces/{self.namespace}/{resource}'
        if query:
            url += '?' + query
        req = urllib.request.Request(url, method='PATCH' if payload else 'GET',
            data=json.dumps(payload).encode() if payload else None,
            headers={'Authorization': 'Bearer ' + self.token,
                     'Content-Type': 'application/merge-patch+json'})
        with self.client.open(req, timeout=30) as response:
            return json.load(response)

    def deployment(self):
        return self.request('deployments/forgejo')

    def patch(self, current, replicas, marker):
        return self.request('deployments/forgejo', {
            'metadata': {'resourceVersion': current['metadata']['resourceVersion'],
                         'annotations': {PAUSE: marker}}, 'spec': {'replicas': replicas}})

    def pods(self, deployment):
        selector = ','.join(k + '=' + v for k, v in
                            deployment['spec']['selector']['matchLabels'].items())
        return self.request('pods', query=urllib.parse.urlencode({'labelSelector': selector}))['items']


def wait(check, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(2)
    raise BackupError('Forgejo did not reach the required state before the deadline.')


def require_nfs(path):
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields, filesystem = line.split(' - ', 1)
        if fields.split()[4] == str(path) and filesystem.split()[0] in ['nfs', 'nfs4']:
            return
    raise BackupError('Expected a mounted NAS volume; refusing to use an ordinary directory.')


def require_layout():
    require_nfs(NAS)
    require_nfs(STAGE)
    for path in [LOCAL, NAS, STAGE]:
        if path.is_symlink() or not path.is_dir():
            raise BackupError('Invalid source or staging volume.')
    if not (LOCAL / 'gitea/forgejo.db').is_file() or not (LOCAL / 'gitea/conf/app.ini').is_file():
        raise BackupError('Forgejo database or configuration is missing.')
    # rsync --delete operates only in these two owned directories, never a volume root.
    marker = STAGE / '.forgejo-staging'
    if marker.exists():
        if marker.is_symlink() or marker.read_text() != 'forgejo-staging-v1\n':
            raise BackupError('Unrecognized staging ownership marker.')
    elif any(STAGE.iterdir()):
        raise BackupError('Staging volume contains unrecognized data.')
    else:
        marker.write_text('forgejo-staging-v1\n')
    for name in ['local', 'nas']:
        path = STAGE / 'current' / name
        if (STAGE / 'current').is_symlink() or path.is_symlink():
            raise BackupError('Staging destination must not be a symlink.')
        path.mkdir(parents=True, exist_ok=True)


def command(args, timeout=900, allowed=(0,)):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode not in allowed:
        # Source paths, app configuration, and repository credentials never enter logs.
        raise BackupError('Backup command failed; sensitive diagnostics withheld.')
    return result.stdout


def copy_stores(live=False):
    for source, name in [(LOCAL, 'local'), (NAS, 'nas')]:
        command(['rsync', '-a', '--no-owner', '--no-group', '--delete',
                 *([] if live else ['--checksum']), str(source) + '/',
                 str(STAGE / 'current' / name) + '/'],
                timeout=600, allowed=(0, 24) if live else (0,))


def validate_database():
    db = STAGE / 'current/local/gitea/forgejo.db'
    # Validate on local storage; SQLite WAL must never acquire locks over NFS.
    with tempfile.TemporaryDirectory(dir=CACHE) as directory:
        local = Path(directory) / db.name
        for suffix in ['', '-wal', '-shm']:
            source = Path(str(db) + suffix)
            if source.exists():
                shutil.copy2(source, Path(str(local) + suffix))
        with sqlite3.connect(local.as_uri() + '?mode=ro', uri=True) as connection:
            if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise BackupError('Staged SQLite database failed its integrity check.')


def resume(api, marker):
    current = api.deployment()
    if current['metadata'].get('annotations', {}).get(PAUSE) != marker:
        raise BackupError('Backup pause ownership changed; manual inspection is required.')
    api.patch(current, 1, None)
    wait(lambda: api.deployment().get('status', {}).get('availableReplicas', 0) == 1, 300)
    print('Forgejo resumed and is available.', flush=True)


def recover(api, now=None):
    current = api.deployment()
    marker = current['metadata'].get('annotations', {}).get(PAUSE)
    if not marker:
        return
    value = json.loads(marker)
    if (now or time.time()) - value['started'] > 1500:
        resume(api, marker)
        print('Recovered an expired backup pause.', flush=True)


def stage_and_upload(api, copy=copy_stores, validate=validate_database, upload=None):
    current = api.deployment()
    if current['spec'].get('replicas') != 1 or current['metadata'].get('annotations', {}).get(PAUSE):
        raise BackupError('Forgejo is stopped or already paused; refusing another backup.')
    marker = json.dumps({'id': str(uuid.uuid4()), 'started': time.time()})
    # Mark ownership and scale down in one resource-version-checked update.
    api.patch(current, 0, marker)
    try:
        wait(lambda: not api.pods(current))
        print('Forgejo stopped; synchronizing both stores.', flush=True)
        copy()
        after = api.deployment()
        if (after['spec'].get('replicas') != 0 or api.pods(current)
                or after['metadata'].get('annotations', {}).get(PAUSE) != marker):
            raise BackupError('Forgejo restarted during staging; refusing an inconsistent backup.')
        validate()
    finally:
        # Resume even when copying or validation fails; upload never extends downtime.
        resume(api, marker)
    if upload:
        upload()


def kopia(*args):
    return command(['kopia', '--config-file=' + str(CACHE / 'repository.config'),
                    '--disable-file-logging', '--no-progress', *args], timeout=5400)


def connect(initialize=False):
    keys = ['KOPIA_BUCKET', 'KOPIA_PREFIX', 'KOPIA_S3_ENDPOINT', 'AWS_REGION',
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'KOPIA_PASSWORD']
    if any(not os.environ.get(key) for key in keys):
        raise BackupError('S3 backup credentials are incomplete.')
    prefix = os.environ['KOPIA_PREFIX']
    if prefix != 'applications/forgejo/':
        raise BackupError('Expected the dedicated Forgejo backup prefix.')
    kopia('repository', 'create' if initialize else 'connect', 's3',
          '--bucket=' + os.environ['KOPIA_BUCKET'], '--prefix=' + prefix,
          '--endpoint=' + os.environ['KOPIA_S3_ENDPOINT'], '--region=' + os.environ['AWS_REGION'],
          '--cache-directory=' + str(CACHE / 'content'),
          '--content-cache-size-limit-mb=128', '--metadata-cache-size-limit-mb=64',
          '--no-check-for-updates')
    kopia('repository', 'set-client', '--username=forgejo', '--hostname=homelab')


def upload():
    kopia('policy', 'set', '--global', '--keep-latest=3', '--keep-daily=14',
          '--keep-weekly=8', '--keep-monthly=6', '--keep-annual=0', '--keep-hourly=0',
          '--ignore-file-errors=false', '--ignore-dir-errors=false', '--ignore-cache-dirs=false')
    snapshot = json.loads(kopia('snapshot', 'create', str(STAGE / 'current'), '--json', '--fail-fast'))
    if snapshot.get('incomplete') or snapshot.get('incompleteReason') or snapshot.get('rootEntry', {}).get('summ', {}).get('numFailed', 0):
        raise BackupError('Kopia produced an incomplete snapshot.')
    kopia('snapshot', 'verify', '--verify-files-percent=0')
    print('Consistent Forgejo snapshot uploaded to S3 and metadata verified.', flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--maintenance', action='store_true')
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    if args.recover:
        recover(Kubernetes())
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    connect(args.initialize)
    if args.initialize:
        print('Initialized the dedicated Forgejo S3 repository.', flush=True)
    elif args.maintenance:
        kopia('maintenance', 'set', '--owner=forgejo@homelab')
        kopia('maintenance', 'run', '--full')
        print('Forgejo S3 repository maintenance completed.', flush=True)
    else:
        require_layout()
        # Copy most bytes while online. A checksum pass while stopped catches all changes.
        copy_stores(live=True)
        stage_and_upload(Kubernetes(), upload=upload)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise BackupError('Backup interrupted.')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except Exception as error:
        print(str(error) if type(error) is BackupError else
              f'Forgejo backup failed ({type(error).__name__}); diagnostics withheld.', flush=True)
        raise SystemExit(1)
