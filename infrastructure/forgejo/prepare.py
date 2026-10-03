#!/usr/bin/env python3
"""Prepare encrypted Forgejo storage and credentials without plaintext manifests."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nas-record', type=Path, required=True,
                        help='Protected local record containing the new NAS server and path')
    parser.add_argument('--staging-record', type=Path, required=True,
                        help='Protected local record for separate NAS backup staging')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    app = root / 'kubernetes/apps/forgejo'
    keys = ['BACKUP_S3_BUCKET', 'BACKUP_S3_ENDPOINT', 'BACKUP_S3_REGION',
            'BACKUP_S3_ACCESS_KEY_ID', 'BACKUP_S3_SECRET_ACCESS_KEY', 'BACKUP_KOPIA_PASSWORD']
    if any(not os.environ.get(key) for key in keys):
        raise RuntimeError('Run through Varlock with the existing S3 backup settings enabled.')
    record = json.loads(args.nas_record.read_text())
    staging = json.loads(args.staging_record.read_text())
    for item in [record, staging]:
        if (not isinstance(item, dict) or not isinstance(item.get('server'), str)
                or not item['server'] or not isinstance(item.get('path'), str)
                or not item['path'].startswith('/mnt/') or '..' in item['path'].split('/')):
            raise RuntimeError('Invalid protected NAS record.')
    if (record['server'], record['path']) == (staging['server'], staging['path']):
        raise RuntimeError('Backup staging must be separate from live storage.')
    admin_password = secrets.token_urlsafe(32)
    admin = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
             'metadata': {'name': 'forgejo-admin', 'namespace': 'forgejo'},
             'stringData': {'username': 'jetersen', 'password': admin_password}}
    backup = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
              'metadata': {'name': 'forgejo-kopia', 'namespace': 'forgejo'},
              'stringData': {'KOPIA_PASSWORD': os.environ['BACKUP_KOPIA_PASSWORD'],
                            'KOPIA_BUCKET': os.environ['BACKUP_S3_BUCKET'],
                            'KOPIA_PREFIX': 'applications/forgejo/',
                            'KOPIA_S3_ENDPOINT': os.environ['BACKUP_S3_ENDPOINT'],
                            'AWS_REGION': os.environ['BACKUP_S3_REGION'],
                            'AWS_ACCESS_KEY_ID': os.environ['BACKUP_S3_ACCESS_KEY_ID'],
                            'AWS_SECRET_ACCESS_KEY': os.environ['BACKUP_S3_SECRET_ACCESS_KEY']}}
    annotations = {'kustomize.toolkit.fluxcd.io/prune': 'disabled'}
    volume = {'apiVersion': 'v1', 'kind': 'PersistentVolume',
              'metadata': {'name': 'forgejo-nas', 'annotations': annotations},
              'spec': {'capacity': {'storage': '100Gi'}, 'accessModes': ['ReadWriteMany'],
                       'persistentVolumeReclaimPolicy': 'Retain', 'storageClassName': '',
                       'mountOptions': ['nfsvers=4.2', 'hard', 'timeo=600', 'retrans=2'],
                       'claimRef': {'namespace': 'forgejo', 'name': 'forgejo-nas'},
                       'nfs': {'server': record['server'], 'path': record['path']}}}
    claim = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
             'metadata': {'name': 'forgejo-nas', 'namespace': 'forgejo', 'annotations': annotations},
             'spec': {'accessModes': ['ReadWriteMany'], 'storageClassName': '',
                      'volumeName': 'forgejo-nas', 'resources': {'requests': {'storage': '100Gi'}}}}
    staging_volume = json.loads(json.dumps(volume))
    staging_volume['metadata']['name'] = 'forgejo-backup-staging'
    staging_volume['spec'].update(capacity={'storage': '120Gi'},
        claimRef={'namespace': 'forgejo', 'name': 'forgejo-backup-staging'},
        nfs={'server': staging['server'], 'path': staging['path']})
    staging_claim = json.loads(json.dumps(claim))
    staging_claim['metadata']['name'] = 'forgejo-backup-staging'
    staging_claim['spec'].update(volumeName='forgejo-backup-staging',
        resources={'requests': {'storage': '120Gi'}})
    targets = [(app / 'app/admin-secret.sops.yaml', admin),
               (app / 'backup/secret.sops.yaml', backup),
               (app / 'app/nas-storage.sops.yaml', volume),
               (app / 'backup/nas-storage.sops.yaml', staging_volume)]
    if any(target.exists() for target, _ in targets):
        raise RuntimeError('Forgejo manifests already exist; refuse credential or storage replacement.')
    sensitive = [admin_password, record['server'], record['path'], staging['server'],
                 staging['path'], *[os.environ[k] for k in keys]]
    prepared = []
    for target, document in targets:
        result = subprocess.run(['sops', 'encrypt', '--filename-override', str(target),
                                 '--input-type', 'json', '--output-type', 'yaml'],
                                input=json.dumps(document), text=True, capture_output=True, cwd=root)
        if result.returncode or 'ENC[AES256_GCM,' not in result.stdout:
            raise RuntimeError('Encryption failed; diagnostics withheld.')
        # Non-secret backup endpoint and region may remain inside encrypted stringData,
        # and all actual credentials and NAS locations must be absent in plaintext.
        if any(value in result.stdout for value in sensitive if len(value) > 8):
            raise RuntimeError('Encrypted manifest contains a plaintext protected value.')
        content = result.stdout
        if document['kind'] == 'PersistentVolume':
            content += '\n---\n' + json.dumps(staging_claim if document is staging_volume else claim) + '\n'
        prepared.append((target, content))
    for target, content in prepared:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    print('Prepared encrypted Forgejo admin, S3 backup, and NAS volume manifests.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error) if type(error) is RuntimeError else 'Preparation failed; diagnostics withheld.')
        raise SystemExit(1)
