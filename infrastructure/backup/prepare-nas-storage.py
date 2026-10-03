#!/usr/bin/env python3
"""Generate encrypted NAS volume locations without writing plaintext manifests."""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True)
    parser.add_argument('--base-path', required=True)
    args = parser.parse_args()
    path = PurePosixPath(args.base_path)
    if not path.is_absolute() or '..' in path.parts or len(path.parts) < 3:
        raise RuntimeError('Choose an absolute dedicated NAS dataset path.')
    root = Path(__file__).resolve().parents[2]
    targets = [root / f'kubernetes/apps/{namespace}/backup/nas-storage.sops.yaml'
               for namespace in ['home-assistant', 'media']]
    if any(target.exists() for target in targets):
        raise RuntimeError('NAS manifests already exist; review location changes before regeneration.')
    encrypted = []
    for namespace, target in zip(['home-assistant', 'media'], targets):
        applications = ['sonarr'] if namespace == 'media' else ['home-assistant', 'zigbee2mqtt']
        volumes = []
        for app in applications:
            name = f'{app}-nas-backup'
            annotations = {'kustomize.toolkit.fluxcd.io/prune': 'disabled'}
            volumes.append({'apiVersion': 'v1', 'kind': 'PersistentVolume',
                'metadata': {'name': name, 'annotations': annotations}, 'spec': {
                    'capacity': {'storage': '100Gi'}, 'accessModes': ['ReadWriteMany'],
                    'persistentVolumeReclaimPolicy': 'Retain', 'storageClassName': '',
                    'mountOptions': ['nfsvers=4.2', 'hard', 'timeo=600', 'retrans=2'],
                    'claimRef': {'namespace': namespace, 'name': name},
                    'nfs': {'server': args.server, 'path': str(path / app)}}})
            volumes.append({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                'metadata': {'name': name, 'namespace': namespace, 'annotations': annotations},
                'spec': {'accessModes': ['ReadWriteMany'], 'storageClassName': '', 'volumeName': name,
                         'resources': {'requests': {'storage': '100Gi'}}}})
        documents = []
        for volume in volumes:
            if volume['kind'] == 'PersistentVolumeClaim':
                documents.append(json.dumps(volume))
                continue
            result = subprocess.run(['sops', 'encrypt', '--filename-override', str(target),
                '--input-type', 'json', '--output-type', 'yaml'], input=json.dumps(volume),
                capture_output=True, text=True, cwd=root)
            if result.returncode or 'ENC[AES256_GCM,' not in result.stdout:
                raise RuntimeError('NAS manifest encryption failed; diagnostic withheld.')
            if args.server in result.stdout or args.base_path in result.stdout:
                raise RuntimeError('NAS locations were not encrypted.')
            documents.append(result.stdout)
        encrypted.append('\n---\n'.join(documents))
    for target, content in zip(targets, encrypted):
        target.write_text(content)
    print('Prepared encrypted NAS volumes for three applications.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error) if type(error) is RuntimeError else 'NAS preparation failed; diagnostic withheld.')
        raise SystemExit(1)
