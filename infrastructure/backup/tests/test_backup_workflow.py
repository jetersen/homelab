import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('backup_workflow', ROOT / 'kubernetes/components/application-backup/run-backup.py')
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


class API:
    namespace = 'media'

    def __init__(self, export_failed=False, mover_failed=False):
        self.calls = []
        self.trigger = 'previous'
        self.export_failed = export_failed
        self.mover_failed = mover_failed

    def request(self, resource, name='', payload=None, method='GET'):
        self.calls.append((resource, name, payload, method))
        if resource == 'cronjobs':
            return {'metadata': {'uid': 'fixture-uid'}, 'spec': {'jobTemplate': {'spec': {'template': {'spec': {}}}}}}
        if resource == 'jobs':
            return {'status': {'conditions': [{'type': 'Failed', 'status': 'True'}]}} if self.export_failed else {'status': {'succeeded': 1}}
        if method == 'PATCH':
            self.trigger = payload['spec']['trigger']['manual']
        return {'metadata': {'resourceVersion': '7'}, 'spec': {'paused': False, 'trigger': {'manual': self.trigger}},
                'status': {'lastManualSync': self.trigger,
                           'latestMoverStatus': {'result': 'Failed' if self.mover_failed else 'Successful'}}}


class WorkflowTests(unittest.TestCase):
    def test_export_finishes_before_trigger_and_matching_mover_success(self):
        api = API()
        with patch.object(workflow.uuid, 'uuid4', return_value='fresh-trigger'):
            workflow.run(api, 'sonarr-backup', 'sonarr-backup-export')
        methods = [(resource, method) for resource, _, _, method in api.calls]
        self.assertLess(methods.index(('jobs', 'POST')), methods.index(('replicationsources', 'PATCH')))
        self.assertIn(('jobs', 'GET'), methods[:methods.index(('replicationsources', 'PATCH'))])
        self.assertEqual(api.trigger, 'fresh-trigger')
        patch_request = next(payload for resource, _, payload, method in api.calls if method == 'PATCH')
        self.assertEqual(patch_request['metadata']['resourceVersion'], '7')

    def test_failed_export_never_triggers_upload(self):
        api = API(export_failed=True)
        with self.assertRaises(workflow.BackupError):
            workflow.run(api, 'sonarr-backup', 'sonarr-backup-export')
        self.assertFalse(any(method == 'PATCH' for _, _, _, method in api.calls))

    def test_failed_mover_fails_workflow(self):
        with self.assertRaises(workflow.BackupError):
            workflow.run(API(mover_failed=True), 'sonarr-backup', 'sonarr-backup-export')

    def test_old_success_does_not_finish_wait(self):
        resources = iter([{'trigger': 'old'}, {'trigger': 'new'}])
        with patch.object(workflow.time, 'sleep'):
            result = workflow.wait(lambda: next(resources), lambda r: r['trigger'] == 'new', lambda r: False, 30)
        self.assertEqual(result['trigger'], 'new')

    def test_replication_runs_after_successful_primary_backup(self):
        api = API()
        called = []
        def replicate():
            self.assertNotEqual(api.trigger, 'previous')
            self.assertEqual(api.calls[-1][0], 'replicationsources')
            called.append(True)
        workflow.run(api, 'sonarr-backup', 'sonarr-backup-export', replicate)
        self.assertEqual(called, [True])
        called.clear()
        with self.assertRaises(workflow.BackupError):
            workflow.run(API(mover_failed=True), 'sonarr-backup', replicate=replicate)
        self.assertFalse(called)

    def test_nas_failure_fails_the_workflow(self):
        def failed_replication():
            raise workflow.BackupError('NAS replica failed.')
        with self.assertRaises(workflow.BackupError):
            workflow.run(API(), 'sonarr-backup', replicate=failed_replication)


if __name__ == '__main__':
    unittest.main()
