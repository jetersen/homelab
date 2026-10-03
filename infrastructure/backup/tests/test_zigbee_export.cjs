const {test} = require('node:test');
const assert = require('node:assert/strict');
const {zipSync, unzipSync} = require('fflate');
const {prepareArchive} = require('../../../kubernetes/apps/home-assistant/backup/export-zigbee.cjs');

function fixture() {
  return {
    'configuration.yaml': Buffer.from('version: 4'),
    'database.db': Buffer.from('{"id":1,"type":"Coordinator"}\n{"id":2,"type":"EndDevice"}\n'),
    'coordinator_backup.json': Buffer.from(JSON.stringify({metadata: {format: 'zigpy/open-coordinator-backup'},
      network_key: {key: 'offline-fixture'}, pan_id: 'fixture', extended_pan_id: 'fixture'})),
    'state.json': Buffer.from('{"device":{"state":"ON"}}'),
    'configuration_backup_v4.yaml': Buffer.from('version: 4'),
    'external_converters/example.js': Buffer.from('module.exports = {};'),
    'log/today/log.log': Buffer.from('log'),
    'migration-3-to-4.log': Buffer.from('log'),
    'ota/firmware.bin': Buffer.from('firmware'),
    'unfinished.tmp': Buffer.from('partial'),
  };
}

test('export preserves network, devices, custom configuration and deployment overrides, excluding logs and firmware', () => {
  const environment = {ZIGBEE2MQTT_CONFIG_ADVANCED_NETWORK_KEY: 'offline-test-value'};
  const restored = unzipSync(prepareArchive(zipSync(fixture()), environment));
  assert.deepEqual(Object.keys(restored).sort(), ['configuration.yaml', 'configuration_backup_v4.yaml',
    'coordinator_backup.json', 'database.db', 'deployment-environment.json',
    'external_converters/example.js', 'state.json'].sort());
  assert.deepEqual(JSON.parse(Buffer.from(restored['deployment-environment.json'])), environment);
});

test('export rejects missing or malformed device and coordinator recovery data', () => {
  for (const mutation of [files => delete files['database.db'],
    files => files['database.db'] = Buffer.from('broken'),
    files => files['coordinator_backup.json'] = Buffer.from('{}')]) {
    const files = fixture(); mutation(files);
    assert.throws(() => prepareArchive(zipSync(files), {}));
  }
});

test('export rejects paths outside the recovery directory', () => {
  const files = fixture(); files['../outside'] = Buffer.from('invalid');
  assert.throws(() => prepareArchive(zipSync(files), {}));
});
