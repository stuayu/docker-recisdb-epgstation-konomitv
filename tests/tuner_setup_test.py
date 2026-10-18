"""Exercise tuner provisioning against real HTTP and Docker command stubs."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'private-token-' + 'f' * 64


class ProvisionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        for folder in ('scripts', 'docker/edcb'):
            shutil.copytree(ROOT / folder, self.repo / folder, ignore=shutil.ignore_patterns('__pycache__'))
        (self.repo / 'data/recisdb').mkdir(parents=True)
        (self.repo / 'config/edcb').mkdir(parents=True)
        (self.repo / 'config/edcb/EpgTimerSrv.ini').write_text('[SET]\nCustom=keep\n[BonDriver_LinuxMirakc.so]\nCount=2\nPriority=1\n[TVTEST]\nNum=1\n')
        self.config = self.repo / 'config/recisdb-proxy/recisdb-proxy.toml'
        self.config.parent.mkdir(parents=True)
        self.config.write_text('[web]\nauth_enabled = true\n')
        self.env_file = self.repo / '.env'
        self.env_file.write_text('COMPOSE_FILE=compose.yaml:compose.tuners.yaml:compose.edcb.yaml\nEDCB_TUNER_COUNT=2\nCUSTOM=keep\n')
        self.db = self.repo / 'data/recisdb/recisdb-proxy.db'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE web_auth_config (id INTEGER, auth_token TEXT)')
            db.execute('INSERT INTO web_auth_config VALUES (1, ?)', (SECRET,))
        self.dev = Path(self.temp.name) / 'dev'
        self.dev.mkdir()
        for name in ('px4video0', 'px4video1', 'px4video2', 'px4video3',
                     'dvb/adapter0/frontend0', 'dvb/adapter0/demux0', 'dvb/adapter0/dvr0'):
            path = self.dev / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.log = self.repo / 'commands.jsonl'
        self.docker = self.repo / 'docker-stub'
        self.docker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
with open(os.environ['COMMAND_LOG'], 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[-1] == 'edcb-chset':
    result = subprocess.run([sys.executable, 'docker/edcb/chset.py', '--refresh'], env=dict(os.environ, EDCB_CONFIG_DIR=str(pathlib.Path('config/edcb').resolve())))
    sys.exit(result.returncode)
if os.environ.get('FAIL_RESTART') == '1' and 'restart' in sys.argv:
    print('server echoed ' + os.environ['TEST_SECRET'], file=sys.stderr)
    sys.exit(7)
''')
        self.docker.chmod(0o755)
        self.drivers, self.histories, self.active, self.posts = [], {}, {}, []
        self.auth_enabled = True
        self.mode = 'ok'
        self.invalid = False
        self.redirect = ''
        self.history_id = 0
        self.progress_reads = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, body):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body.encode() if isinstance(body, str) else json.dumps(body).encode())

            def authorized(self):
                if self.path.startswith('/api/'):
                    expected = 'Bearer ' + SECRET if owner.auth_enabled else None
                    if self.headers.get('Authorization') != expected:
                        self.send_error(401, SECRET)
                        return False
                return True

            def do_GET(self):
                if not self.authorized():
                    return
                parsed = urlsplit(self.path)
                path = parsed.path
                if owner.redirect and path.startswith(owner.redirect):
                    self.send_response(302)
                    self.send_header('Location', owner.redirect_url)
                    self.end_headers()
                    return
                if owner.invalid:
                    self.send_error(500, SECRET)
                    return
                if path == '/api/bondrivers':
                    self.reply({'success': True, 'bondrivers': owner.drivers})
                elif path == '/api/scan-config':
                    self.reply({'success': True, 'config': {'scan_timeout_secs': 1, 'check_interval_secs': 1}})
                elif path == '/api/scan-history':
                    key = int(parse_qs(parsed.query)['bondriver_id'][0])
                    self.reply({'success': True, 'history': owner.histories.get(key, [])})
                elif path.startswith('/api/bondriver/'):
                    key = int(path.rsplit('/', 1)[1])
                    row = next(row for row in owner.drivers if row['id'] == key)
                    if key in owner.active:
                        owner.progress_reads += 1
                        owner.active[key] += 1
                        if owner.mode != 'timeout' and owner.active[key] >= 3:
                            owner.history_id += 1
                            owner.histories.setdefault(key, []).append({'id': owner.history_id,
                                'bon_driver_id': key, 'success': owner.mode != 'failure',
                                'channel_count': 0 if owner.mode in ('zero', 'failure') else 1,
                                'error_message': SECRET})
                            row.update(is_scanning=False, next_scan_at=None, last_scan=int(time.time()))
                            del owner.active[key]
                    self.reply({'success': True, 'bondriver': row})
                elif path == '/mirakurun/api/services':
                    self.reply([{'networkId': 32744, 'serviceId': 1024, 'channel': [{'type': 'GR'}]}])
                elif path == '/mirakurun/api/channels':
                    self.reply([{'type': 'GR', 'channel': '27'}])
                elif path == '/api/client-view/targets':
                    self.reply({'success': True, 'targets': [{'name': 'driver', 'type': 'driver', 'enabled_channels': 1}]})
                elif path.endswith('/chset4'):
                    self.reply('ch\tsvc\tnet\t9\t8\t32744\t32744\t1024\t1\t0\t1\t1\n')
                elif path.endswith('/chset5'):
                    self.reply('svc\tnet\t32744\t32744\t1024\t1\t0\t1\t1\n')
                else:
                    self.send_error(404)

            def do_POST(self):
                if not self.authorized():
                    return
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.posts.append((self.path, payload))
                if self.path == '/api/bondriver':
                    row = dict(payload, id=len(owner.drivers) + 1, next_scan_at=None, is_scanning=False, last_scan=None)
                    owner.drivers.append(row)
                elif self.path.endswith('/scan'):
                    key = int(self.path.split('/')[-2])
                    owner.active[key] = 0
                    next(row for row in owner.drivers if row['id'] == key).update(is_scanning=True, next_scan_at=0)
                else:
                    raise AssertionError(self.path)
                self.reply({'success': True})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = dict(os.environ, DOCKER_BIN=str(self.docker), ENV_FILE=str(self.env_file),
                        DEV_DIR=str(self.dev), TUNERS_COMPOSE_FILE=str(self.repo / 'compose.tuners.yaml'),
                        RECISDB_DATABASE=str(self.db), RECISDB_CONFIG=str(self.config),
                        RECISDB_URL=f'http://127.0.0.1:{self.server.server_port}',
                        COMMAND_LOG=str(self.log), TEST_SECRET=SECRET, EDCB_RETRY_SECONDS='0')
        self.env.pop('COMPOSE_FILE', None)
        subprocess.run(['sh', str(self.repo / 'scripts/gen-tuners.sh')], env=self.env, check=True, capture_output=True)

    def run_cli(self, *args, success=True, extra=None):
        result = subprocess.run(['python3', str(self.repo / 'scripts/tuner-setup.py'), *args,
                                 '--poll', '.01', '--timeout', '.15', '--ready-timeout', '.05'],
                                env=dict(self.env, **(extra or {})), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        if self.log.exists():
            self.assertNotIn(SECRET, self.log.read_text())
        return result.stdout

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_register_types_idempotence_and_missing(self):
        self.run_cli('register')
        self.assertEqual(len(self.drivers), 5)
        self.assertEqual(self.drivers[-1]['dll_path'], '/dev/px4video3')
        self.assertEqual(self.drivers[0]['dll_path'], '/dev/dvb/adapter0/frontend0')
        for row in self.drivers:
            self.assertEqual(row['max_instances'], 1)
            self.assertEqual(row['stream_format'], 'ts')
            self.assertFalse(row['auto_scan_enabled'])
            self.assertFalse(row['disable_b25'])
            self.assertNotIn('group_name', row)
        self.drivers[0]['dll_path'] = '/dev/dvb/adapter0'
        self.drivers[0]['driver_name'] = 'custom'
        self.run_cli('register')
        self.assertEqual(len(self.posts), 5)
        self.assertEqual(self.drivers[0]['driver_name'], 'custom')
        (self.dev / 'px4video0').unlink()
        output = self.run_cli('register')
        self.assertIn('Compose にない登録を保持', output)
        self.assertEqual(len(self.drivers), 5)
        self.assertIn(['compose', 'up', '-d', '--no-deps', 'recisdb-proxy'], self.commands())

    def test_scan_wait_chset_reload_and_setup_second_run(self):
        output = self.run_cli('--automatic')
        self.assertIn('5/5 台完了', output)
        self.assertGreaterEqual(self.progress_reads, 15)
        commands = self.commands()
        self.assertIn(['compose', 'stop', 'edcb'], commands)
        self.assertIn(['compose', 'run', '--rm', '--no-deps', 'edcb', 'edcb-chset'], commands)
        self.assertIn(['compose', 'up', '-d', '--no-deps', 'edcb'], commands)
        self.assertIn(['compose', 'restart', 'epgstation'], commands)
        self.assertIn(['compose', 'restart', 'konomitv'], commands)
        self.assertIn('EDCB_TUNER_COUNT=5', self.env_file.read_text())
        ini = (self.repo / 'config/edcb/EpgTimerSrv.ini').read_text()
        self.assertIn('Count=5', ini)
        self.assertIn('Custom=keep', ini)
        self.assertIn('Num=1', ini)
        chset = self.repo / 'config/edcb/Setting/ChSet5.txt'
        self.assertTrue(chset.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        posts = len(self.posts)
        output = self.run_cli('--automatic')
        self.assertIn('登録・スキャン・反映済み', output)
        self.assertEqual(len(self.posts), posts)
        self.assertEqual(self.commands(), commands)
        # Explicit scan always rescans, even after successful setup.
        self.run_cli('scan')
        self.assertEqual(len(self.posts), posts + 5)
        self.assertTrue(list(chset.parent.glob('*.bak.*')))
        # A newly mapped device gets registered and scanned on automatic setup.
        (self.dev / 'px4video4').touch()
        subprocess.run(['sh', str(self.repo / 'scripts/gen-tuners.sh')], env=self.env, check=True, capture_output=True)
        self.run_cli('--automatic', '--yes')
        self.assertEqual(len(self.posts), posts + 7)

    def test_scan_failure_zero_timeout_keep_chset(self):
        path = self.repo / 'config/edcb/Setting/ChSet5.txt'
        path.parent.mkdir()
        path.write_text('existing')
        for mode, expected in [('failure', 'スキャン失敗'), ('zero', '受信 0 局'), ('timeout', 'タイムアウト')]:
            with self.subTest(mode=mode):
                self.mode = mode
                output = self.run_cli('scan', success=False)
                self.assertIn(expected, output)
                self.assertIn('make scan', output)
                self.assertEqual(path.read_text(), 'existing')
                self.assertFalse(self.commands())
                # Simulate operator resolving the prior pending server scan.
                self.active.clear()
                for row in self.drivers:
                    row.update(is_scanning=False, next_scan_at=None)

    def test_api_errors_and_failed_service_refresh_retry(self):
        self.invalid = True
        self.run_cli(success=False)
        self.invalid = False
        self.run_cli('--automatic', success=False, extra={'FAIL_RESTART': '1'})
        self.assertFalse((self.repo / 'data/tuner-setup.json').exists())
        posts = len(self.posts)
        self.run_cli('--automatic')
        self.assertEqual(len(self.posts), posts)
        self.assertTrue((self.repo / 'data/tuner-setup.json').exists())

    def test_disabled_capacity_and_duplicate_alias(self):
        self.run_cli('register')
        self.drivers[0]['max_instances'] = 0
        self.assertIn('max_instances', self.run_cli(success=False))
        self.assertFalse(self.active)
        self.drivers[0]['max_instances'] = 1
        self.drivers.append(dict(self.drivers[0], id=99, dll_path='/dev/dvb/adapter0'))
        self.assertIn('複数登録済み', self.run_cli(success=False))

    def test_missing_token_and_dvb_nodes(self):
        self.db.unlink()
        self.assertIn('token DB', self.run_cli(success=False))
        (self.dev / 'dvb/adapter0/dvr0').unlink()
        subprocess.run(['sh', str(self.repo / 'scripts/gen-tuners.sh')], env=self.env, check=True, capture_output=True)
        self.assertIn('demux/dvr', self.run_cli(success=False))

    def test_auth_disabled_register_and_scan_without_token_or_db(self):
        self.auth_enabled = False
        self.config.write_text('[web]\nauth_enabled = false\n')
        self.db.unlink()
        self.run_cli('register')
        self.assertEqual(len(self.drivers), 5)
        output = self.run_cli('scan')
        self.assertIn('5/5 台完了', output)
        self.assertTrue((self.repo / 'config/edcb/Setting/ChSet5.txt').is_file())

    def test_real_setup_no_scan_first_second_and_failure(self):
        # Run setup.sh itself with fake host inventory and Docker, but real HTTP
        # registration, history polling, ChSet generation and config writes.
        shutil.copy2(ROOT / 'setup.sh', self.repo / 'setup.sh')
        shutil.copy2(ROOT / '.env.example', self.repo / '.env.example')
        shutil.copytree(ROOT / 'templates', self.repo / 'templates')
        for path in ROOT.glob('compose*.yaml'):
            shutil.copy2(path, self.repo / path.name)
        source = self.repo / 'konomitv'
        source.mkdir()
        (source / 'Dockerfile').write_text('FROM scratch\n')
        binaries = self.repo / 'bin'
        binaries.mkdir()
        scripts = {
            'curl': 'exit 0', 'getent': 'echo video:x:44:', 'systemctl': 'exit 1',
            'id': 'case $1 in -u|-g) echo 1000;; -un) echo tester;; esac',
            'lsusb': 'exit 0', 'lspci': 'exit 0', 'modinfo': 'exit 0',
            'ip': 'echo "1.1.1.1 via 192.168.1.1 dev eth0 src 192.168.1.30"',
            'hostname': 'echo 192.168.1.30', 'ufw': 'exit 0',
        }
        for name, body in scripts.items():
            path = binaries / name
            path.write_text('#!/bin/sh\n' + body + '\n')
            path.chmod(0o755)
        with self.docker.open('a') as output:
            output.write("\nif sys.argv[1:] == ['compose', 'ps', '--status', 'running', '--services']:\n    print('recisdb-proxy\\nepgstation\\nkonomitv\\nedcb')\n")
        env = dict(self.env, PATH=str(binaries) + ':' + os.environ['PATH'], SETUP_OS='Linux',
                   BONCAS_MODE='remote', BONCAS_HOST='127.0.0.1', BONCAS_PORT=str(self.server.server_port),
                   BONCAS_4K_SAME='yes', RECORDED_DIR=str(self.repo / 'recorded'),
                   GPU='none', HTTPS='no', AMATSUKAZE='no', EDCB='yes',
                   EDCB_EPGSTATION_ENABLED='0', KONOMITV_SOURCE=str(source), TUNER_SCAN_POLL_SECONDS='.01')
        self.auth_enabled = False
        self.db.unlink()

        def setup(*args):
            result = subprocess.run(['bash', './setup.sh', '--yes', '--no-build', *args],
                                    cwd=self.repo, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn(SECRET, result.stdout + result.stderr)
            return result.stdout

        setup('--no-scan')
        self.assertEqual(self.posts, [])
        self.assertFalse((self.repo / 'data/tuner-setup.json').exists())
        self.assertIn('チューナー登録・チャンネルスキャン', setup())
        posts = len(self.posts)
        self.assertEqual(posts, 10)
        self.assertIn('登録・スキャン・反映済み', setup())
        self.assertEqual(len(self.posts), posts)
        self.mode = 'failure'
        self.histories.clear()
        # setup tolerates scan failure and still prints access URLs.
        output = setup()
        self.assertIn('セットアップは続行', output)
        self.assertIn('セットアップ完了', output)

    def test_edcb_restart_failure_propagates(self):
        with self.docker.open('a') as output:
            output.write("\nif sys.argv[1:] == ['compose', 'up', '-d', '--no-deps', 'edcb']:\n    sys.exit(9)\n")
        self.assertIn('EDCB ChSet 反映/再起動に失敗', self.run_cli(success=False))
        self.assertNotIn(['compose', 'restart', 'epgstation'], self.commands())

    def test_legacy_edcb_ini_and_count_drift(self):
        self.run_cli('--automatic')
        legacy = self.repo / 'data/edcb/EpgTimerSrv.ini'
        legacy.parent.mkdir(parents=True)
        legacy.write_text('[SET]\nUserEdit=from-runtime\n[BonDriver_LinuxMirakc.so]\nCount=2\n')
        posts = len(self.posts)
        self.run_cli('--automatic')
        self.assertEqual(len(self.posts), posts)
        self.assertIn('Count=5', legacy.read_text())
        self.assertEqual(legacy.read_bytes(), (self.repo / 'config/edcb/EpgTimerSrv.ini').read_bytes())
        self.assertIn('UserEdit=from-runtime', legacy.read_text())
        self.assertTrue(list(legacy.parent.glob('*.bak.*')))

    def test_scan_adopts_active_job_and_progress_gauge(self):
        self.run_cli('register')
        row = self.drivers[0]
        row.update(is_scanning=True, next_scan_at=0)
        self.active[row['id']] = 0
        gauge = self.repo / 'dialog'
        gauge.write_text('#!/bin/sh\ncat > "$GAUGE_LOG"\n')
        gauge.chmod(0o755)
        log = self.repo / 'gauge.log'
        self.run_cli('--automatic', '--tui', str(gauge), extra={'GAUGE_LOG': str(log)})
        self.assertTrue(log.exists())
        self.assertIn('XXX\n100\n', log.read_text())
        self.assertFalse(any(path == f'/api/bondriver/{row["id"]}/scan' for path, _ in self.posts))

    def test_authentication_redirects_are_not_followed(self):
        received = []

        class Sink(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                received.append(self.headers.get('Authorization'))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

        sink = ThreadingHTTPServer(('127.0.0.1', 0), Sink)
        threading.Thread(target=sink.serve_forever, daemon=True).start()
        self.addCleanup(sink.server_close)
        self.addCleanup(sink.shutdown)
        self.redirect_url = f'http://127.0.0.1:{sink.server_port}/capture'
        self.redirect = '/api/bondrivers'
        self.run_cli(success=False)
        self.redirect = '/api/client-view'
        self.run_cli(success=False)
        # Exercise the standalone ChSet fetcher too, where stderr is visible.
        result = subprocess.run(['python3', str(self.repo / 'docker/edcb/chset.py'), '--refresh'],
                                env=dict(self.env, EDCB_CONFIG_DIR=str(self.repo / 'config/edcb')),
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertEqual(received, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
