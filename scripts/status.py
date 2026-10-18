#!/usr/bin/env python3
"""Show endpoints without treating .env values (including JSON/paths) as shell code."""
from pathlib import Path
import os
import subprocess

root = Path(__file__).resolve().parents[1]
env_path = Path(os.environ.get('ENV_FILE', root / '.env'))
values = dict(line.split('=', 1) for line in env_path.read_text().splitlines()
              if '=' in line and not line.lstrip().startswith('#'))
try:
    host = subprocess.check_output(['hostname', '-I'], stderr=subprocess.DEVNULL, text=True).split()[0]
except (OSError, subprocess.CalledProcessError, IndexError):
    host = 'localhost'
name = host.replace('.', '-') + '.local.konomi.tv'
files = values.get('COMPOSE_FILE', '').split(':')
urls = [('recisdb-proxy HTTP', f'http://{host}:' + values.get('RECISDB_WEB_PORT', '40080') + '/'),
        ('EPGStation HTTP', f'http://{host}:' + values.get('EPGSTATION_PORT', '8888') + '/'),
        ('KonomiTV HTTPS', f'https://{name}:' + values.get('KONOMITV_PORT', '7000') + '/')]
for file, label, scheme, endpoint_host, key, port, path in [
    ('compose.https.yaml', 'recisdb-proxy HTTPS', 'https', name, 'RECISDB_HTTPS_PORT', '40443', '/'),
    ('compose.https.yaml', 'EPGStation HTTPS', 'https', name, 'EPGSTATION_HTTPS_PORT', '8443', '/'),
    ('compose.edcb.yaml', 'EDCB WebUI', 'http', host, 'EDCB_WEB_PORT', '5510', '/E3/'),
    ('compose.edcb.https.yaml', 'EDCB HTTPS', 'https', name, 'EDCB_HTTPS_PORT', '8553', '/E3/'),
    ('compose.amatsukaze.yaml', 'Amatsukaze WebUI', 'http', host, 'AMATSUKAZE_WEBUI_PORT', '32769', '/'),
]:
    if file in files:
        urls.append((label, f'{scheme}://{endpoint_host}:{values.get(key, port)}{path}'))
if 'compose.boncasrelay.yaml' in files:
    urls.append(('BonCasRelay WebUI (録画ホスト上)', 'http://127.0.0.1:' + values.get('BONCASRELAY_WEB_PORT', '6980') + '/'))
for label, url in urls:
    print(f'{label}: {url}')
