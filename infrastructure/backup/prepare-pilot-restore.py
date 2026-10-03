#!/usr/bin/env python3
"""Render an isolated restore after verifying the successful manual pilot and an unused PVC name."""
import argparse
import datetime
import json
import subprocess


def kubectl(namespace, *args):
    result = subprocess.run(['kubectl', '--context', 'homelab', '-n', namespace, *args],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Read-only cluster check failed; kubectl output withheld.')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('application', choices=['home-assistant', 'zigbee2mqtt', 'sonarr'])
    parser.add_argument('--as-of', required=True, help='Explicit RFC3339 recovery cutoff after the pilot snapshot')
    args = parser.parse_args()
    namespace = 'media' if args.application == 'sonarr' else 'home-assistant'
    cutoff = datetime.datetime.fromisoformat(args.as_of.replace('Z', '+00:00'))
    if cutoff.utcoffset() is None:
        raise RuntimeError('Recovery cutoff must have an explicit timezone.')
    source = json.loads(kubectl(namespace, 'get', 'replicationsource', f'{args.application}-backup', '-o', 'json'))
    status = source.get('status', {})
    manual = source['spec'].get('trigger', {}).get('manual')
    if (not manual or status.get('lastManualSync') != manual or not status.get('lastSyncTime')
            or status.get('latestMoverStatus', {}).get('result') != 'Successful'):
        raise RuntimeError('The requested manual pilot has not completed successfully.')
    completed = datetime.datetime.fromisoformat(status['lastSyncTime'].replace('Z', '+00:00'))
    if source['spec'].get('kopia', {}).get('repository') == f'{args.application}-kopia-nas':
        workflow = json.loads(kubectl(namespace, 'get', 'cronjob', f'{args.application}-backup', '-o', 'json'))
        replicated = workflow.get('status', {}).get('lastSuccessfulTime')
        if not replicated or datetime.datetime.fromisoformat(replicated.replace('Z', '+00:00')) < completed:
            raise RuntimeError('S3 replication has not completed after the latest NAS backup.')
    if cutoff < completed or cutoff > datetime.datetime.now(datetime.timezone.utc):
        raise RuntimeError('Cutoff must be between pilot completion and the current time.')
    name = f'{args.application}-kopia-pilot-restore'
    for kind in ['pvc', 'replicationdestination']:
        if kubectl(namespace, 'get', kind, name, '--ignore-not-found', '-o', 'name').strip():
            raise RuntimeError('Restore target already exists; choose a separate recovery procedure.')
    pvc = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
           'metadata': {'name': name, 'namespace': namespace},
           'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'local-path',
                    'resources': {'requests': {'storage': '1Gi'}}}}
    destination = {'apiVersion': 'volsync.backube/v1alpha1', 'kind': 'ReplicationDestination',
                   'metadata': {'name': name, 'namespace': namespace},
                   'spec': {'trigger': {'manual': 'pilot-restore-1'}, 'kopia': {
                       'repository': f'{args.application}-kopia', 'copyMethod': 'Direct',
                       'destinationPVC': name, 'cacheCapacity': '1Gi', 'restoreAsOf': args.as_of,
                       'username': args.application, 'hostname': 'homelab', 'enableFileDeletion': False,
                       'moverSecurityContext': {'runAsUser': 0, 'runAsGroup': 0, 'fsGroup': 0},
                       'moverResources': {'requests': {'cpu': '100m', 'memory': '128Mi'},
                                          'limits': {'memory': '1Gi'}}}}}
    # JSON is valid YAML and contains no connection credentials.
    print(json.dumps(pvc, indent=2))
    print('---')
    print(json.dumps(destination, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import sys
        print(str(error) if type(error) is RuntimeError else 'Restore preparation failed; diagnostic withheld.',
              file=sys.stderr)
        raise SystemExit(1)
