// Run through the Kopiur pre-backup Job. Never log MQTT payloads or ZIP contents.
const fs = require('node:fs');
const crypto = require('node:crypto');
const {unzipSync, zipSync} = require('fflate');

class BackupError extends Error {}

const required = ['configuration.yaml', 'database.db', 'coordinator_backup.json', 'state.json'];

function prepareArchive(bytes, environment) {
  const files = unzipSync(bytes);
  for (const name of Object.keys(files)) {
    if (name.startsWith('/') || name.includes('\\') || name.split('/').includes('..')) {
      throw new BackupError('Unsafe archive path');
    }
    if (name.startsWith('log/') || name.startsWith('ota/') || /\.(log|tmp)$/.test(name)) {
      delete files[name];
    }
  }
  for (const name of required) {
    if (!files[name]?.length) throw new BackupError(`Missing recovery file: ${name}`);
  }
  const coordinator = JSON.parse(Buffer.from(files['coordinator_backup.json']));
  if (coordinator.metadata?.format !== 'zigpy/open-coordinator-backup' ||
      !coordinator.network_key?.key || coordinator.pan_id === undefined ||
      !coordinator.extended_pan_id) throw new BackupError('Incomplete coordinator backup');
  JSON.parse(Buffer.from(files['state.json']));
  for (const line of Buffer.from(files['database.db']).toString().split('\n').filter(Boolean)) {
    JSON.parse(line);
  }
  // The native export does not include overrides injected by Kubernetes.
  // Preserve these separately; restoration must map them back to environment variables.
  files['deployment-environment.json'] = Buffer.from(JSON.stringify(environment));
  return Buffer.from(zipSync(files, {level: 6}));
}

async function main() {
  const mqtt = require('mqtt');
  const environment = Object.fromEntries(Object.entries(process.env)
    .filter(([key]) => key.startsWith('ZIGBEE2MQTT_CONFIG_')));
  for (const key of ['MQTT_USER', 'MQTT_PASSWORD', 'ADVANCED_NETWORK_KEY', 'ADVANCED_PAN_ID', 'ADVANCED_EXT_PAN_ID']) {
    if (!environment[`ZIGBEE2MQTT_CONFIG_${key}`]) throw new BackupError('Missing recovery environment');
  }
  const transaction = crypto.randomUUID();
  const topic = 'zigbee2mqtt/bridge/response/backup';
  const client = mqtt.connect(process.env.MQTT_SERVER, {
    username: environment.ZIGBEE2MQTT_CONFIG_MQTT_USER,
    password: environment.ZIGBEE2MQTT_CONFIG_MQTT_PASSWORD,
    clientId: `backup-export-${transaction}`, reconnectPeriod: 0,
    connectTimeout: 15000, clean: true,
  });
  try {
    const archive = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new BackupError('Backup request timed out')), 180000);
      function finish(error, result) {
        clearTimeout(timer);
        if (error) reject(error); else resolve(result);
      }
      client.on('error', () => finish(new BackupError('MQTT connection failed')));
      client.on('message', (receivedTopic, payload, packet) => {
        if (receivedTopic !== topic || packet.retain) return;
        try {
          const response = JSON.parse(payload);
          if (response.transaction !== transaction) return;
          if (response.status !== 'ok' || typeof response.data?.zip !== 'string') {
            return finish(new BackupError('Native backup failed'));
          }
          const encoded = response.data.zip;
          if (encoded.length > 32 * 1024 * 1024 || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) {
            return finish(new BackupError('Invalid archive response'));
          }
          finish(null, prepareArchive(Buffer.from(encoded, 'base64'), environment));
        } catch (error) { finish(error instanceof BackupError ? error : new BackupError('Recovery archive validation failed')); }
      });
      client.on('connect', () => client.subscribe(topic, {qos: 1}, (error, granted) => {
        if (error || !granted?.length || granted.some(item => item.qos > 1)) {
          return finish(new BackupError('MQTT subscription failed'));
        }
        client.publish('zigbee2mqtt/bridge/request/backup', JSON.stringify({transaction}),
          {qos: 1, retain: false}, error => { if (error) finish(new BackupError('MQTT publish failed')); });
      }));
    });
    fs.mkdirSync('/exports/backups', {recursive: true, mode: 0o700});
    const temporary = `/exports/backups/${transaction}.tmp`;
    const fd = fs.openSync(temporary, 'wx', 0o600);
    try { fs.writeFileSync(fd, archive); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temporary, '/exports/backups/zigbee2mqtt.zip');
    console.log('Validated Zigbee recovery export saved; logs and firmware excluded.');
  } finally { client.end(true); }
}

module.exports = {prepareArchive};
if (require.main === module) main().catch(error => {
  const reason = error instanceof BackupError ? error.message :
    ['EACCES', 'EROFS', 'ENOSPC', 'ENOENT'].includes(error.code) ? error.code : 'Unexpected failure';
  console.error(`Zigbee recovery export failed: ${reason}; payload and credentials withheld.`);
  process.exitCode = 1;
});
