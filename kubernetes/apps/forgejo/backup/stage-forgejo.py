#!/usr/bin/env python3
"""Stage a stopped Forgejo instance and resume it before Kopiur snapshots the copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import sqlite3
import ssl
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


def synchronize(source, destination, live=False):
    """Synchronize an owned staging tree without following source or destination symlinks."""
    destination.mkdir(exist_ok=True)
    entries = {entry.name: entry for entry in source.iterdir()}
    for entry in destination.iterdir():
        if entry.name not in entries:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    for name, entry in entries.items():
        target = destination / name
        if entry.is_symlink():
            if target.is_symlink() and os.readlink(entry) == os.readlink(target):
                continue
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            target.symlink_to(os.readlink(entry))
        elif entry.is_dir():
            if target.is_symlink() or (target.exists() and not target.is_dir()):
                target.unlink()
            synchronize(entry, target, live)
            shutil.copystat(entry, target)
        elif entry.is_file():
            if target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            unchanged = target.is_file() and entry.stat().st_size == target.stat().st_size
            if unchanged:
                if live:
                    unchanged = entry.stat().st_mtime_ns == target.stat().st_mtime_ns
                else:
                    def digest(path):
                        with path.open('rb') as stream:
                            return hashlib.file_digest(stream, 'sha256').digest()
                    unchanged = digest(entry) == digest(target)
            if not unchanged:
                shutil.copy2(entry, target)
        else:
            raise BackupError('Unsupported entry in a source store.')


def copy_stores(live=False):
    for source, name in [(LOCAL, 'local'), (NAS, 'nas')]:
        try:
            synchronize(source, STAGE / 'current' / name, live)
        except FileNotFoundError:
            if not live:
                raise


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


def stage_and_resume(api, copy=copy_stores, validate=validate_database):
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



def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    if args.recover:
        recover(Kubernetes())
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    require_layout()
    copy_stores(live=True)
    stage_and_resume(Kubernetes())


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
