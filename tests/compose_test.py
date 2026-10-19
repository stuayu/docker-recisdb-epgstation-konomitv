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
env = dict(os.environ, MARIADB_PASSWORD='compose-test', MARIADB_ROOT_PASSWORD='compose-root-test',
           TUNER_GIDS='44,45', VIDEO_GID='1044', RENDER_GID='1110')
# Ignore a caller's selected default overrides: this test supplies every file.
env.pop('COMPOSE_FILE', None)
env.pop('COMPOSE_PROFILES', None)


def compose_config(files, settings=env):
    command = [binary, '--env-file', str(root / '.env.example')]
    for file in files:
        command.extend(['-f', str(file)])
    output = subprocess.run(command + ['config', '--format', 'json'], cwd=root, env=settings,
                            capture_output=True, text=True, check=True)
    return json.loads(output.stdout)


with tempfile.TemporaryDirectory() as temp:
    tuner_override = Path(temp) / 'compose.tuners.yaml'
    tuner_devices = ['/dev/px4video0', '/dev/dvb/adapter0/frontend0']
    tuner_override.write_text('services:\n  recisdb-proxy:\n    devices:\n' +
                              ''.join(f'      - "{node}:{node}"\n' for node in tuner_devices) +
                              '    group_add: ["44", "45"]\n')
    for relay, edcb, amatsukaze, https, gpu, amd_kfd in itertools.product((False, True), (False, True), (False, True), (False, True), ('none', 'intel', 'amd', 'nvidia'), (False, True)):
        files = ['compose.yaml', str(tuner_override)]
        if gpu != 'none':
            files.append(f'compose.{gpu}.yaml')
            if gpu == 'amd' and amd_kfd:
                files.append('compose.amd.kfd.yaml')
        if https:
            files.append('compose.https.yaml')
        if amatsukaze:
            files.append('compose.amatsukaze.yaml')
            if gpu != 'none':
                files.append(f'compose.amatsukaze.{gpu}.yaml')
                if gpu == 'amd' and amd_kfd:
                    files.append('compose.amatsukaze.amd.kfd.yaml')
        if edcb:
            files.append('compose.edcb.yaml')
            if https:
                files.append('compose.edcb.https.yaml')
        if relay:
            files.append('compose.boncasrelay.yaml')
        config = compose_config(files)
        services = config['services']
        gpu_devices = {'intel': ['/dev/dri'], 'amd': ['/dev/dri'] + (['/dev/kfd'] if amd_kfd else [])}.get(gpu, [])
        gpu_groups = {'intel': {'1110'}, 'amd': {'1044', '1110'}}.get(gpu, set())
        gpu_services = ['recisdb-proxy', 'epgstation', 'konomitv'] + (['amatsukaze'] if amatsukaze else [])
        for name in gpu_services:
            service = services[name]
            expected_devices = (tuner_devices if name == 'recisdb-proxy' else []) + gpu_devices
            devices = service.get('devices', [])
            assert {device['target'] for device in devices} == set(expected_devices), (gpu, name, devices)
            assert len(devices) == len(expected_devices), (gpu, name, devices)
            assert all(device['source'] == device['target'] and device['permissions'] == 'rwm' for device in devices)
            expected_groups = ({'44', '45'} if name == 'recisdb-proxy' else set()) | gpu_groups
            assert set(service.get('group_add', [])) == expected_groups, (gpu, name, service.get('group_add'))
            reservations = service.get('deploy', {}).get('resources', {}).get('reservations', {}).get('devices', [])
            if gpu == 'nvidia':
                assert len(reservations) == 1, (name, reservations)
                assert reservations[0]['driver'] == 'nvidia' and reservations[0]['count'] == -1
                assert set(reservations[0]['capabilities']) == {'compute', 'utility', 'video'}
            else:
                assert not reservations, (gpu, name, reservations)
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
        capture = next(v for v in services['konomitv']['volumes'] if v['target'] == '/host-rootfs/data/konomitv-capture')
        assert capture['source'].endswith('/data/konomitv-capture') and not capture.get('read_only', False)
        if edcb:
            assert services['edcb']['build']['args']['EDCB_REF'] == 'my-build'
            assert services['edcb']['build']['args']['EDCB_WEBUI_REF'] == 'E3'
            assert services['edcb']['environment']['RECISDB_CONFIG'] == '/recisdb-proxy.toml'
            auth_config = next(v for v in services['edcb']['volumes'] if v['target'] == '/recisdb-proxy.toml')
            assert auth_config['read_only']
            assert any(v['target'] == '/recorded' for v in services['edcb']['volumes'])
            assert services['edcb']['stop_grace_period'] == '50s'
        if https:
            gateway = services['https-gateway']
            assert ('edcb' in gateway['depends_on']) == edcb
            assert ('8553=http://edcb:5510/' in gateway['environment']['AKEBI_ROUTES']) == edcb
            assert any(p['target'] == 8553 for p in gateway['ports']) == edcb
        if amatsukaze:
            assert services['epgstation']['environment']['AMATSUKAZE_ENABLED'] == '1'
    # setup.sh may place generated tuner overrides after GPU overlays. Preserve both
    # device sets in that order too, including a duplicate /dev/dri mapping.
    tuner_text = tuner_override.read_text()
    for gpu in ('intel', 'amd', 'nvidia'):
        tuner_override.write_text(tuner_text.replace('    group_add:',
            ('      - "/dev/dri:/dev/dri"\n' if gpu != 'nvidia' else '') + '    group_add:'))
        config = compose_config(['compose.yaml', f'compose.{gpu}.yaml', str(tuner_override)])
        proxy = config['services']['recisdb-proxy']
        extra_devices = {'intel': ['/dev/dri'], 'amd': ['/dev/dri']}.get(gpu, [])
        assert {device['target'] for device in proxy['devices']} == set(tuner_devices + extra_devices)
        assert len(proxy['devices']) == len(tuner_devices + extra_devices)
        assert set(proxy['group_add']) >= {'44', '45'}
print('PASS: real Docker Compose config matrix (128 combinations: BonCasRelay x EDCB x Amatsukaze x HTTPS x GPU x optional AMD KFD) and tuner/GPU merge order')

with tempfile.TemporaryDirectory() as temp:
    directory = Path(temp).resolve()
    settings = {'RECORDED_DIR': str(directory / 'disk one'),
                'RECORDED_DIRS_JSON': json.dumps([str(directory / 'disk one'), str(directory / 'disk two')]),
                'COMPOSE_FILE': 'compose.yaml:compose.edcb.yaml:compose.amatsukaze.yaml'}
    mounts(directory, settings)
    config = compose_config((root / 'compose.yaml', root / 'compose.edcb.yaml', root / 'compose.amatsukaze.yaml', directory / 'compose.storage.yaml'),
                            dict(env, RECORDED_DIR=settings['RECORDED_DIR'], RECORDED_DIRS_JSON=settings['RECORDED_DIRS_JSON']))
    services = config['services']
    assert services['edcb']['environment']['RECORDED_DIR'] == settings['RECORDED_DIR']
    assert json.loads(services['edcb']['environment']['RECORDED_DIRS_JSON']) == json.loads(settings['RECORDED_DIRS_JSON'])
    assert 'EDCB_RECORDING_PATHS' not in services['edcb']['environment']
    for name in ('epgstation', 'edcb', 'amatsukaze', 'konomitv'):
        target = '/host-rootfs/recorded2' if name == 'konomitv' else '/recorded2'
        volume = next(v for v in services[name]['volumes'] if v['target'] == target)
        assert volume['source'] == str(directory / 'disk two')
        assert volume.get('read_only', False) == (name == 'konomitv')
print('PASS: real Compose merge of multiple recording folders with spaces across EPGStation/EDCB/KonomiTV/Amatsukaze')
