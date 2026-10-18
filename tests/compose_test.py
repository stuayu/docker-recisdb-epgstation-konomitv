"""Validate optional-service combinations with a real standalone Compose CLI."""
import itertools
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
binary = os.environ.get('COMPOSE_BIN', 'docker-compose')
env = dict(os.environ, MARIADB_PASSWORD='compose-test', MARIADB_ROOT_PASSWORD='compose-root-test')
# Ignore a caller's selected default overrides: this test supplies every file.
env.pop('COMPOSE_FILE', None)
env.pop('COMPOSE_PROFILES', None)
for edcb, amatsukaze, https, gpu in itertools.product((False, True), (False, True), (False, True), ('none', 'intel', 'nvidia')):
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
    command = [binary, '--env-file', '.env.example']
    for file in files:
        command.extend(['-f', file])
    output = subprocess.run(command + ['config', '--format', 'json'], cwd=root, env=env,
                            capture_output=True, text=True, check=True)
    services = json.loads(output.stdout)['services']
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
print('PASS: real Docker Compose config matrix (24 combinations: EDCB x Amatsukaze x HTTPS x GPU)')
