"""Validate optional-service combinations with a real standalone Compose CLI."""
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from storage import mounts

root = Path(__file__).resolve().parents[1]
binary = os.environ.get('COMPOSE_BIN', 'docker-compose')
env = dict(os.environ, MARIADB_PASSWORD='compose-test', MARIADB_ROOT_PASSWORD='compose-root-test')
# Ignore a caller's selected default overrides: this test supplies every file.
env.pop('COMPOSE_FILE', None)
env.pop('COMPOSE_PROFILES', None)
for relay, edcb, amatsukaze, https, gpu in itertools.product((False, True), (False, True), (False, True), (False, True), ('none', 'intel', 'nvidia')):
    files = ['compose.yaml']
    if gpu != 'none':
        files.append(f'compose.{gpu}.yaml')
    if https:
        files.append('compose.https.yaml')
    if amatsukaze:
        files.append('compose.amatsukaze.yaml')
        if gpu != 'none':
            files.append(f'compose.amatsukaze.{gpu}.yaml')
    if edcb:
        files.append('compose.edcb.yaml')
        if https:
            files.append('compose.edcb.https.yaml')
    if relay:
        files.append('compose.boncasrelay.yaml')
    command = [binary, '--env-file', '.env.example']
    for file in files:
        command.extend(['-f', file])
    output = subprocess.run(command + ['config', '--format', 'json'], cwd=root, env=env,
                            capture_output=True, text=True, check=True)
    config = json.loads(output.stdout)
    services = config['services']
    assert ('boncasrelay' in services) == relay
    if relay:
        card = services['boncasrelay']
        assert [p['target'] for p in card['ports']] == [6980]
        assert card['ports'][0]['host_ip'] == '127.0.0.1'
        assert 'c 189:* rw' in card['device_cgroup_rules']
        assert not config['networks']['default'].get('ipam')
        assert not card.get('privileged')
    assert ('edcb' in services) == edcb
    assert ('amatsukaze' in services) == amatsukaze
    assert ('https-gateway' in services) == https
    db = services['mariadb']
    assert db['image'] == 'mariadb:latest' and not db.get('profiles')
    assert db['environment']['MARIADB_AUTO_UPGRADE'] == '1'
    assert not db.get('ports')
    assert services['epgstation']['depends_on']['mariadb']['condition'] == 'service_healthy'
    if edcb:
        assert services['edcb']['build']['args']['EDCB_REF'] == 'my-build'
        assert services['edcb']['build']['args']['EDCB_WEBUI_REF'] == 'E3'
        assert any(v['target'] == '/recorded' for v in services['edcb']['volumes'])
        assert services['edcb']['stop_grace_period'] == '50s'
    if https:
        gateway = services['https-gateway']
        assert ('edcb' in gateway['depends_on']) == edcb
        assert ('8553=http://edcb:5510/' in gateway['environment']['AKEBI_ROUTES']) == edcb
        assert any(p['target'] == 8553 for p in gateway['ports']) == edcb
    if amatsukaze:
        assert services['epgstation']['environment']['AMATSUKAZE_ENABLED'] == '1'
        ama = services['amatsukaze']
        assert bool(ama.get('devices')) == (gpu == 'intel')
        assert bool(ama.get('deploy', {}).get('resources', {}).get('reservations', {}).get('devices')) == (gpu == 'nvidia')
print('PASS: real Docker Compose config matrix (48 combinations: BonCasRelay x EDCB x Amatsukaze x HTTPS x GPU)')

with tempfile.TemporaryDirectory() as temp:
    directory = Path(temp).resolve()
    settings = {'RECORDED_DIR': str(directory / 'disk one'),
                'RECORDED_DIRS_JSON': json.dumps([str(directory / 'disk one'), str(directory / 'disk two')]),
                'COMPOSE_FILE': 'compose.yaml:compose.edcb.yaml:compose.amatsukaze.yaml'}
    mounts(directory, settings)
    command = [binary, '--env-file', str(root / '.env.example')]
    for file in (root / 'compose.yaml', root / 'compose.edcb.yaml', root / 'compose.amatsukaze.yaml', directory / 'compose.storage.yaml'):
        command.extend(['-f', str(file)])
    output = subprocess.run(command + ['config', '--format', 'json'], cwd=root,
                            env=dict(env, RECORDED_DIR=settings['RECORDED_DIR'], RECORDED_DIRS_JSON=settings['RECORDED_DIRS_JSON']), capture_output=True, text=True, check=True)
    services = json.loads(output.stdout)['services']
    assert services['edcb']['environment']['RECORDED_DIR'] == settings['RECORDED_DIR']
    assert json.loads(services['edcb']['environment']['RECORDED_DIRS_JSON']) == json.loads(settings['RECORDED_DIRS_JSON'])
    assert 'EDCB_RECORDING_PATHS' not in services['edcb']['environment']
    for name in ('epgstation', 'edcb', 'amatsukaze', 'konomitv'):
        target = '/host-rootfs/recorded2' if name == 'konomitv' else '/recorded2'
        volume = next(v for v in services[name]['volumes'] if v['target'] == target)
        assert volume['source'] == str(directory / 'disk two')
        assert volume.get('read_only', False) == (name == 'konomitv')
print('PASS: real Compose merge of multiple recording folders with spaces across EPGStation/EDCB/KonomiTV/Amatsukaze')
