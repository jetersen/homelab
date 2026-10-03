#!/usr/bin/env python3
"""Run a native export before requesting and verifying a VolSync backup."""
import argparse
import json
import os
from pathlib import Path
import ssl
import runpy
import time
import urllib.request
import uuid


class BackupError(Exception):
    pass


class Kubernetes:
    def __init__(self):
        credentials = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.namespace = (credentials / 'namespace').read_text().strip()
        self.token = (credentials / 'token').read_text().strip()
        self.context = ssl.create_default_context(cafile=str(credentials / 'ca.crt'))
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=self.context))

    def request(self, resource, name='', payload=None, method='GET'):
        group = 'apis/volsync.backube/v1alpha1' if resource == 'replicationsources' else 'apis/batch/v1'
        url = f'https://kubernetes.default.svc/{group}/namespaces/{self.namespace}/{resource}'
        if name:
            url += '/' + name
        if method == 'PATCH':
            url += '?fieldManager=backup-scheduler'
        req = urllib.request.Request(url, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + self.token,
                     'Content-Type': 'application/merge-patch+json' if method == 'PATCH' else 'application/json'})
        with self.client.open(req, timeout=30) as response:
            return json.load(response)


def wait(read, success, failure, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resource = read()
        if failure(resource):
            raise BackupError('Backup operation failed.')
        if success(resource):
            return resource
        time.sleep(3)
    raise BackupError('Backup operation timed out.')


def run(api, source, export_cronjob=None, replicate=None):
    current = api.request('replicationsources', source)
    if current['spec'].get('paused'):
        raise BackupError('Backup source is paused.')
    previous = current['spec'].get('trigger', {}).get('manual')
    if previous and current.get('status', {}).get('lastManualSync') != previous:
        raise BackupError('Previous backup has not finished.')
    trigger = str(uuid.uuid4())
    if export_cronjob:
        cronjob = api.request('cronjobs', export_cronjob)
        name = export_cronjob + '-' + trigger[:8]
        job = {'apiVersion': 'batch/v1', 'kind': 'Job',
               'metadata': {'name': name, 'namespace': api.namespace, 'ownerReferences': [{
                   'apiVersion': 'batch/v1', 'kind': 'CronJob', 'name': export_cronjob,
                   'uid': cronjob['metadata']['uid'], 'controller': True}]},
               'spec': cronjob['spec']['jobTemplate']['spec']}
        job['spec']['ttlSecondsAfterFinished'] = 86400
        api.request('jobs', payload=job, method='POST')
        wait(lambda: api.request('jobs', name),
             lambda r: r.get('status', {}).get('succeeded', 0) > 0,
             lambda r: any(c['type'] == 'Failed' and c['status'] == 'True'
                           for c in r.get('status', {}).get('conditions', [])), 300)
        print('Native export completed.')
    current = api.request('replicationsources', source)
    if current['spec'].get('paused') or current['spec'].get('trigger', {}).get('manual') != previous:
        raise BackupError('Backup source changed during export.')
    api.request('replicationsources', source, {'metadata': {'resourceVersion': current['metadata']['resourceVersion']},
                'spec': {'trigger': {'manual': trigger}}}, 'PATCH')
    def failed(resource):
        status = resource.get('status', {})
        return (resource['spec'].get('trigger', {}).get('manual') != trigger or
                (status.get('lastManualSync') == trigger and
                 status.get('latestMoverStatus', {}).get('result') != 'Successful'))
    wait(lambda: api.request('replicationsources', source),
         lambda r: r.get('status', {}).get('lastManualSync') == trigger and
                   r.get('status', {}).get('latestMoverStatus', {}).get('result') == 'Successful',
         failed, 1800)
    print('NAS backup completed successfully.')
    if replicate:
        replicate()


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('source')
        parser.add_argument('export_cronjob', nargs='?')
        parser.add_argument('--replicate', action='store_true')
        args = parser.parse_args()
        replicate = runpy.run_path(str(Path(__file__).with_name('replicate.py')))['sync'] if args.replicate else None
        run(Kubernetes(), args.source, args.export_cronjob, replicate)
    except Exception as error:
        print(str(error) if type(error) is BackupError else
              f'Backup workflow failed ({type(error).__name__}); diagnostic withheld.')
        raise SystemExit(1)
