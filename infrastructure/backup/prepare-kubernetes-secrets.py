#!/usr/bin/env python3
"""Encrypt Kopia connection manifests from Varlock-injected values, using only memory for plaintext."""
import json
import os
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[2]
    keys = ['BACKUP_S3_BUCKET', 'BACKUP_S3_REGION', 'BACKUP_S3_ENDPOINT',
            'BACKUP_S3_ACCESS_KEY_ID', 'BACKUP_S3_SECRET_ACCESS_KEY', 'BACKUP_KOPIA_PASSWORD']
    if any(not os.environ.get(key) for key in keys):
        raise RuntimeError('Required backup settings are missing; run through Varlock.')
    targets = [root / f'kubernetes/apps/home-assistant/backup/{app}-secret.sops.yaml'
               for app in ['home-assistant', 'zigbee2mqtt']]
    if any(path.exists() for path in targets):
        raise RuntimeError('Connection manifests already exist; review credential changes before regeneration.')
    encrypted = []
    for app, target in zip(['home-assistant', 'zigbee2mqtt'], targets):
        document = {'apiVersion': 'v1', 'kind': 'Secret',
                    'metadata': {'name': f'{app}-kopia', 'namespace': 'home-assistant'},
                    'type': 'Opaque', 'stringData': {
                        'KOPIA_REPOSITORY': f's3://{os.environ["BACKUP_S3_BUCKET"]}/pilot/{app}',
                        'KOPIA_PASSWORD': os.environ['BACKUP_KOPIA_PASSWORD'],
                        'AWS_ACCESS_KEY_ID': os.environ['BACKUP_S3_ACCESS_KEY_ID'],
                        'AWS_SECRET_ACCESS_KEY': os.environ['BACKUP_S3_SECRET_ACCESS_KEY'],
                        'AWS_REGION': os.environ['BACKUP_S3_REGION'],
                        'KOPIA_S3_ENDPOINT': os.environ['BACKUP_S3_ENDPOINT'],
                        'KOPIA_CHECK_FOR_UPDATES': 'false',
                        'KOPIA_FILE_LOG_LEVEL': 'info',
                    }}
        result = subprocess.run(['sops', 'encrypt', '--filename-override', str(target),
                                 '--input-type', 'json', '--output-type', 'yaml'],
                                input=json.dumps(document), capture_output=True, text=True, cwd=root)
        if result.returncode or 'ENC[AES256_GCM,' not in result.stdout:
            raise RuntimeError('SOPS encryption failed; subprocess output withheld.')
        if any(os.environ[key] in result.stdout for key in keys[3:]):
            raise RuntimeError('SOPS output failed the plaintext-secret check.')
        encrypted.append(result.stdout)
    for target, content in zip(targets, encrypted):
        target.write_text(content)
    print('Prepared two SOPS-encrypted Kopia connection manifests; no plaintext files written.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Only controlled diagnostics are exposed. Never stringify unknown subprocess exceptions.
        if type(error) is RuntimeError:
            print(str(error))
        else:
            print('Connection preparation failed; diagnostic withheld.')
        raise SystemExit(1)
