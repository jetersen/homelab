import contextlib
import datetime
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pilot_restore', Path(__file__).parents[1] / 'prepare-pilot-restore.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class RestoreTests(unittest.TestCase):
    def setUp(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.cutoff = (now - datetime.timedelta(minutes=1)).isoformat()
        self.source = {'spec': {'trigger': {'manual': 'pilot-1'}},
                       'status': {'lastManualSync': 'pilot-1',
                                  'latestMoverStatus': {'result': 'Successful'},
                                  'lastSyncTime': (now - datetime.timedelta(minutes=2)).isoformat()}}

    def render(self, application, existing=False):
        def read(*args):
            if args[1] == 'replicationsource':
                return json.dumps(self.source)
            return 'persistentvolumeclaim/existing' if existing else ''
        with patch.object(restore, 'kubectl', side_effect=read), \
                patch('sys.argv', ['prepare-pilot-restore.py', application, '--as-of', self.cutoff]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            restore.main()
        return [json.loads(part) for part in output.getvalue().split('\n---\n')]

    def test_restore_targets_new_pvcs_with_matching_snapshot_identity_and_explicit_cutoff(self):
        for application in ['home-assistant', 'zigbee2mqtt']:
            pvc, destination = self.render(application)
            target = f'{application}-kopia-pilot-restore'
            self.assertEqual(pvc['metadata']['name'], target)
            self.assertEqual(destination['spec']['kopia']['destinationPVC'], target)
            self.assertEqual(destination['spec']['kopia']['username'], application)
            self.assertEqual(destination['spec']['kopia']['restoreAsOf'], self.cutoff)
            self.assertIs(destination['spec']['kopia']['enableFileDeletion'], False)
            self.assertNotIn(target, ['home-assistant-pvc', 'zigbee2mqtt'])

    def test_existing_restore_target_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            self.render('home-assistant', existing=True)

    def test_incomplete_or_outdated_manual_backup_is_rejected(self):
        self.source['status']['lastManualSync'] = 'older-trigger'
        with self.assertRaisesRegex(RuntimeError, 'not completed'):
            self.render('zigbee2mqtt')

    def test_manual_status_without_a_successful_mover_is_rejected(self):
        self.source['status']['latestMoverStatus'] = {}
        with self.assertRaisesRegex(RuntimeError, 'not completed'):
            self.render('home-assistant')


if __name__ == '__main__':
    unittest.main()
