"""EDCB provisioning contract tests using an authenticated proxy HTTP stub."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory() as temp:
    base = Path(temp)
    env = dict(os.environ, EDCB_ROOT=str(base / 'edcb'), EDCB_LIB=str(base / 'lib'),
               EDCB_DEFAULTS=str(base / 'defaults'), EDCB_RECORDED=str(base / 'recorded'),
               EDCB_TUNER_COUNT='3', EDCB_RETRY_SECONDS='0')
    (base / 'defaults/HttpPublic/EMWUI').mkdir(parents=True)
    (base / 'defaults/HttpPublic/EMWUI/index.html').write_text('webui')
    configure = ['python3', str(ROOT / 'docker/edcb/configure.py')]
    subprocess.run(configure, env=env, check=True)
    ini = base / 'edcb/EpgTimerSrv.ini'
    assert 'Count=3' in ini.read_text() and 'RecMode=3' in ini.read_text()
    assert 'Scramble=0' in (base / 'edcb/EpgDataCap_Bon.ini').read_text()
    assert 'SERVICE_SPLIT=1' in (base / 'lib/BonDriver_LinuxMirakc.so.ini').read_text()
    ini.write_text('user settings\n')
    subprocess.run(configure, env=env, check=True)
    assert ini.read_text() == 'user settings\n'
    services = [
        {'networkId': 4, 'serviceId': 101, 'channel': [{'type': 'BS'}]},
        {'networkId': 32744, 'serviceId': 1024, 'channel': [{'type': 'GR'}]},
        {'networkId': 32744, 'serviceId': 1025, 'channel': [{'type': 'GR'}]},
        {'networkId': 4, 'serviceId': 102, 'channel': [{'type': 'BS'}]},
    ]
    # BNDP indices intentionally differ from service order, including type reentry.
    source4 = [f'ch\tsvc\tnet\t9\t8\t{nid}\t{tsid}\t{sid}\t1\t0\t1\t1'
               for nid, tsid, sid in [(32744, 32744, 1024), (4, 16400, 101),
                                       (32744, 32744, 1025), (4, 16401, 102)]]
    source5 = [f'svc\tnet\t{nid}\t{tsid}\t{sid}\t1\t0\t1\t1'
               for nid, tsid, sid in [(4, 16400, 101), (32744, 32744, 1024),
                                       (32744, 32744, 1025), (4, 16401, 102)]]
    state = {'empty': False, 'unauthorized': False, 'broken': False}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlsplit(self.path)
            requests.append(self.path)
            if path.path.startswith('/api/'):
                if state['unauthorized'] or self.headers.get('Authorization') != 'Bearer secret':
                    self.send_error(401)
                    return
            self.send_response(200)
            self.end_headers()
            if path.path == '/mirakurun/api/services':
                body = json.dumps([] if state['empty'] else services)
            elif path.path == '/api/client-view/targets':
                body = json.dumps({'success': True, 'targets': [
                    {'name': '/dev/driver one', 'type': 'driver', 'enabled_channels': 4},
                    {'name': 'empty', 'type': 'driver', 'enabled_channels': 0}]})
            else:
                assert parse_qs(path.query)['tuner'] == ['/dev/driver one']
                data = source4 if path.path.endswith('/chset4') else source5
                body = 'invalid' if state['broken'] else '\ufeff' + '\r\n'.join(data) + '\r\n'
            self.wfile.write(body.encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    db_path = base / 'proxy.db'
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE web_auth_config (id INTEGER, auth_token TEXT)')
        db.execute("INSERT INTO web_auth_config VALUES (1, 'secret')")
    env.update(RECISDB_DATABASE=str(db_path), RECISDB_URL=f'http://127.0.0.1:{server.server_port}')
    command = ['python3', str(ROOT / 'docker/edcb/chset.py')]
    ch4 = base / 'edcb/Setting/BonDriver_LinuxMirakc(LinuxMirakc).ChSet4.txt'
    ch5 = base / 'edcb/Setting/ChSet5.txt'
    try:
        state['empty'] = True
        assert subprocess.run(command, env=env, capture_output=True).returncode == 1
        assert not ch4.exists() and not ch5.exists()
        state['empty'] = False
        subprocess.run(command, env=env, check=True)
        actual = [line.split('\t') for line in ch4.read_text(encoding='utf-8-sig').splitlines()]
        assert [(r[3], r[4], r[7]) for r in actual] == [
            ('0', '0', '101'), ('1', '0', '1024'), ('1', '1', '1025'), ('2', '0', '102')]
        assert len(ch5.read_text(encoding='utf-8-sig').splitlines()) == 4
        assert any('tuner=%2Fdev%2Fdriver+one' in path for path in requests)
        saved = ch4.read_bytes(), ch5.read_bytes()
        requests.clear()
        subprocess.run(command, env=env, check=True)
        assert not requests  # Existing settings never overwritten at boot.
        for failure in ('unauthorized', 'broken'):
            state[failure] = True
            assert subprocess.run(command + ['--refresh'], env=env, capture_output=True).returncode == 1
            assert saved == (ch4.read_bytes(), ch5.read_bytes())
            state[failure] = False
        subprocess.run(command + ['--refresh'], env=env, check=True)
        assert list(ch4.parent.glob('*.bak.*'))
        env['EDCB_STACK'] = str(ROOT / 'docker/edcb')
        subprocess.run(['sh', str(ROOT / 'docker/edcb/entrypoint.sh'), 'true'],
                       env=env, check=True)
        assert ini.read_text() == 'user settings\n'
    finally:
        server.shutdown()
        server.server_close()
print('PASS: EDCB INI nonoverwrite, authenticated ChSet download, index translation, empty scan, failure preservation, refresh backup')
