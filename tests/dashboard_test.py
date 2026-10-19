"""Dashboard provisioning and Lua delivery contracts; Node is not required."""
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dashboard

spec = importlib.util.spec_from_file_location('http_public', ROOT / 'docker/edcb/http_public.py')
http_public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(http_public)


class DashboardTest(unittest.TestCase):
    def test_service_matrix(self):
        for edcb, amatsukaze, https, local in itertools.product((False, True), repeat=4):
            with self.subTest(edcb=edcb, amatsukaze=amatsukaze, https=https, local=local):
                files = ['compose.yaml']
                for active, name in [(edcb, 'edcb'), (amatsukaze, 'amatsukaze'),
                                     (https, 'https'), (local, 'boncasrelay'), (edcb and https, 'edcb.https')]:
                    if active:
                        files.append(f'compose.{name}.yaml')
                env = {'COMPOSE_FILE': ':'.join(files), 'BONCAS_MODE': 'local' if local else 'remote'}
                config = dashboard.configuration(env, '192.168.1.30')
                services = {s['id']: s for s in config['services']}
                self.assertEqual(set(services), {'epgstation', 'recisdb'} |
                                 ({'edcb'} if edcb else set()) | ({'amatsukaze'} if amatsukaze else set()) |
                                 ({'konomitv'} if https else set()) | ({'boncasrelay'} if local else set()))
                self.assertEqual(config['title'], '録画サーバー')
                self.assertEqual(config['host'], '192.168.1.30')
                self.assertEqual(config['httpsHost'], '192-168-1-30.local.konomi.tv' if https else None)
                self.assertEqual(config['edcb']['api'], edcb)
                self.assertEqual(services['epgstation']['http'], 8888)
                self.assertEqual(services['recisdb']['http'], 40080)
                if edcb:
                    self.assertEqual(services['edcb']['path'], '/E3/')
                    self.assertEqual(services['edcb']['http'], 5510)
                if https:
                    self.assertEqual(services['epgstation']['https'], 8443)
                    self.assertEqual(services['recisdb']['https'], 40443)
                    self.assertEqual(services['konomitv']['https'], 7000)
                else:
                    self.assertFalse(any('https' in s for s in services.values()))
                if local:
                    self.assertEqual(services['boncasrelay']['local'], 'http://127.0.0.1:6980/')
                    self.assertNotIn('http', services['boncasrelay'])
                    self.assertNotIn('https', services['boncasrelay'])

    def test_custom_ports_title_and_disabled_routes(self):
        env = dict(COMPOSE_FILE='compose.yaml:compose.edcb.yaml:compose.https.yaml:compose.edcb.https.yaml:compose.amatsukaze.yaml:compose.boncasrelay.yaml',
                   BONCAS_MODE='local', DASHBOARD_TITLE='居間 "録画" \\ server',
                   EPGSTATION_PORT='18888', EPGSTATION_HTTPS_PORT='18443', KONOMITV_PORT='17000',
                   EDCB_WEB_PORT='15510', EDCB_HTTPS_PORT='18553', RECISDB_WEB_PORT='48080',
                   RECISDB_HTTPS_PORT='48443', AMATSUKAZE_WEBUI_PORT='42769', BONCASRELAY_WEB_PORT='16980')
        config = dashboard.configuration(env, '192.168.1.30')
        self.assertEqual(config['title'], env['DASHBOARD_TITLE'])
        services = {s['id']: s for s in config['services']}
        for id_, http, https in [('epgstation', 18888, 18443), ('edcb', 15510, 18553), ('recisdb', 48080, 48443),
                                 ('konomitv', None, 17000), ('amatsukaze', 42769, None)]:
            self.assertEqual(services[id_].get('http'), http)
            self.assertEqual(services[id_].get('https'), https)
        self.assertEqual(services['boncasrelay']['local'], 'http://127.0.0.1:16980/')
        self.assertNotIn('boncasrelay', {s['id'] for s in dashboard.configuration(dict(env, BONCAS_MODE='remote'), 'localhost')['services']})
        no_route = dict(env, COMPOSE_FILE=env['COMPOSE_FILE'].replace(':compose.edcb.https.yaml', ''))
        self.assertNotIn('https', next(s for s in dashboard.configuration(no_route, 'localhost')['services'] if s['id'] == 'edcb'))
        for value in ('0', '65536', 'invalid'):
            with self.assertRaises(ValueError):
                dashboard.configuration(dict(env, EDCB_WEB_PORT=value), 'localhost')

    def test_host_detection(self):
        def result(text):
            return subprocess.CompletedProcess([], 0, stdout=text)
        with patch('dashboard.subprocess.run', return_value=result('1.1.1.1 via 192.168.1.1 dev eth0 src 192.168.1.30')):
            self.assertEqual(dashboard.detect_host(), '192.168.1.30')
        with patch('dashboard.subprocess.run', side_effect=[FileNotFoundError(), result('192.168.1.31 10.0.0.1')]):
            self.assertEqual(dashboard.detect_host(), '192.168.1.31')
        with patch('dashboard.subprocess.run', side_effect=FileNotFoundError()):
            self.assertEqual(dashboard.detect_host(), 'localhost')

    def test_generation_and_regeneration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(ROOT / 'templates', root / 'templates')
            env = root / '.env'
            text = ('COMPOSE_FILE=compose.yaml:compose.edcb.yaml\nMARIADB_PASSWORD=test\n'
                    'BONCAS_B25_HOST=relay\nBONCAS_B25_PORT=6900\n')
            env.write_text(text)
            command = [sys.executable, str(ROOT / 'scripts/render-config.py'), '--root', str(root), '--env', str(env)]
            process_env = dict(os.environ, DASHBOARD_HOST='192.168.1.30')

            def run(*args):
                subprocess.run(command + list(args), env=process_env, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True)

            run('first-run')
            out = root / 'data/edcb/dashboard.json'
            ini = root / 'config/edcb/EpgTimerSrv.ini'
            before = ini.read_bytes()
            self.assertEqual(json.loads(out.read_text())['title'], '録画サーバー')
            self.assertEqual(out.stat().st_mode & 0o777, 0o644)
            out.write_text('manual edits are disposable')
            env.write_text(text + 'DASHBOARD_TITLE=書斎\nEDCB_WEB_PORT=5520\n')
            run('first-run')
            self.assertEqual(json.loads(out.read_text())['title'], '書斎')
            self.assertEqual(ini.read_bytes(), before)
            env.write_text(text + 'DASHBOARD_TITLE=再生成\nEDCB_WEB_PORT=5530\n')
            run('regen', '--service', 'edcb')
            data = json.loads(out.read_text())
            self.assertEqual(data['title'], '再生成')
            self.assertEqual(next(s for s in data['services'] if s['id'] == 'edcb')['http'], 5530)
            self.assertEqual(ini.read_bytes(), before)
            self.assertFalse((root / 'config/edcb/dashboard.json').exists())
            dashboard.generate(root / 'disabled', {'COMPOSE_FILE': 'compose.yaml'})
            self.assertFalse((root / 'disabled/data/edcb/dashboard.json').exists())
        makefile = (ROOT / 'Makefile').read_text()
        self.assertIn('scripts/render-config.py --root . --env .env first-run', makefile.split('update:', 1)[1].split('test:', 1)[0])

    def test_install_and_mime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            public = root / 'HttpPublic'
            (public / 'legacy').mkdir(parents=True)
            (public / 'E3').mkdir()
            (public / 'index.html').write_text('standard Lua top')
            (public / 'legacy/index.html').write_text('ct=[=[\n  <ul>\n  </ul>\n]=]')
            (public / 'E3/index.html').write_text('E3 unchanged')
            (public / 'favicon.ico').write_bytes(b'icon')
            (root / 'ContentTypeText.txt').write_text('; keep comment\n.ts\tvideo/mp2t\n.woff2\tapplication/font-woff2\n')
            dist = root / 'dist'
            (dist / 'dash-assets').mkdir(parents=True)
            (dist / 'dash-assets/app-hash.js').write_text('js')
            (dist / 'index.html').write_text('<html>録画</html>')
            http_public.install(dist, root)
            self.assertIn('mg.write(', (public / 'index.html').read_text())
            self.assertEqual((public / 'server.html').read_text(), 'standard Lua top')
            self.assertIn('../server.html', (public / 'legacy/index.html').read_text())
            self.assertEqual((public / 'E3/index.html').read_text(), 'E3 unchanged')
            self.assertEqual((public / 'favicon.ico').read_bytes(), b'icon')
            self.assertEqual((public / 'dash-assets/app-hash.js').read_text(), 'js')
            self.assertEqual((dist / 'index.html').read_text(), '<html>録画</html>')
            mime = (root / 'ContentTypeText.txt').read_text()
            self.assertIn('; keep comment\n.ts\tvideo/mp2t\n', mime)
            self.assertIn('.woff2\tfont/woff2\n', mime)
            self.assertEqual(mime.count('.woff2\t'), 1)
            http_public.update_mime(root / 'ContentTypeText.txt')
            self.assertEqual((root / 'ContentTypeText.txt').read_text(), mime)

    def test_startup_refresh_and_json_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            defaults = base / 'defaults/HttpPublic'
            defaults.mkdir(parents=True)
            (defaults / 'index.html').write_text('new dashboard wrapper')
            public = base / 'edcb/HttpPublic'
            public.mkdir(parents=True)
            (public / 'index.html').write_text('old standard top')
            (base / 'edcb/ContentTypeText.txt').write_text('.ts\tcustom/ts\n.woff2\told/font\n')
            env = dict(os.environ, EDCB_ROOT=str(base / 'edcb'), EDCB_CONFIG_DIR=str(base / 'config'),
                       EDCB_DEFAULTS=str(base / 'defaults'), EDCB_LIB=str(base / 'lib'),
                       EDCB_RECORDED=str(base / 'recorded'), EDCB_EPGSTATION_ENABLED='0')
            for _ in range(2):
                subprocess.run([sys.executable, str(ROOT / 'docker/edcb/configure.py')], env=env, check=True, capture_output=True)
                self.assertEqual((public / 'index.html').read_text(), 'new dashboard wrapper')
                link = public / 'dashboard.json'
                self.assertTrue(link.is_symlink())
                self.assertFalse(link.exists())
                self.assertIn('.ts\tcustom/ts', (base / 'edcb/ContentTypeText.txt').read_text())
                self.assertIn('.woff2\tfont/woff2', (base / 'edcb/ContentTypeText.txt').read_text())
            (base / 'edcb/dashboard.json').write_text('first')
            self.assertEqual(link.read_text(), 'first')
            replacement = base / 'edcb/new.json'
            replacement.write_text('second')
            replacement.replace(base / 'edcb/dashboard.json')
            self.assertEqual(link.read_text(), 'second')

    def test_build_contract(self):
        dockerfile = (ROOT / 'docker/edcb/Dockerfile').read_text()
        stage = dockerfile.split('FROM ubuntu:24.04 AS dashboard-builder\n')[1].split('\nFROM ')[0]
        self.assertLess(stage.index('npm ci'), stage.index('npm run typecheck'))
        self.assertIn('npm run typecheck && npm test && npm run build', stage)
        self.assertIn('COPY --from=dashboard-builder /dashboard/dist/', dockerfile)
        self.assertIn('RUN python3 /tmp/dashboard-install/http_public.py /tmp/dashboard-dist /var/local/edcb', dockerfile)
        self.assertIn('COPY --from=builder /var/local/edcb/ /opt/edcb-defaults/', dockerfile)
        self.assertIn('FROM uploader-${EDCB_EPGSTATION_ENABLED} AS uploader', dockerfile)
        disabled = dockerfile.split(' AS uploader-0\n')[1].split('\nFROM ')[0]
        self.assertNotIn('git', disabled)
        self.assertNotIn('uploader-1', disabled)
        compose = (ROOT / 'compose.edcb.yaml').read_text()
        self.assertIn('context: .\n', compose)
        self.assertIn('./data/edcb:/var/local/edcb', compose)
        ignore = (ROOT / '.dockerignore').read_text().splitlines()
        self.assertIn('dashboard/node_modules/', ignore)
        self.assertIn('dashboard/dist/', ignore)
        self.assertNotIn('dashboard/', ignore)

    def test_lua_wrapper(self):
        html = '\n<!DOCTYPE html>\n録画 ]=] ]==] ]]\n<script src="./dash-assets/test-hash.js"></script>\n'
        script = http_public.wrap_html(html)
        self.assertIn('local ct = [===[\n' + html + ']===]', script)
        self.assertIn('Content-Type: text/html; charset=utf-8', script)
        self.assertIn('Cache-Control: no-cache', script)
        self.assertIn("mg.request_info.request_method~='HEAD'", script)
        self.assertIn('Content-Length: ', script)
        self.assertNotIn('__DASHBOARD_BODY__', script)
        lua = os.environ.get('LUA_BIN') or shutil.which('lua5.2') or shutil.which('lua')
        if not lua:
            print('PASS: Lua wrapper static checks (Lua unavailable; runtime emulation skipped)', flush=True)
            return
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'index.html').write_text(script)
            (root / 'harness.lua').write_text("""mg = {
  request_info = { request_method = arg[2] },
  keep_alive = function(value) assert(value == true); return arg[3] == 'yes' end,
  write = function(value) io.write(value) end
}
dofile(arg[1])
""")
            for method, keep in itertools.product(('GET', 'HEAD'), ('yes', 'no')):
                response = subprocess.check_output([lua, str(root / 'harness.lua'), str(root / 'index.html'), method, keep])
                header, body = response.split(b'\r\n\r\n', 1)
                self.assertTrue(header.startswith(b'HTTP/1.1 200 OK\r\nDate: '))
                self.assertIn(b'Content-Type: text/html; charset=utf-8', header)
                self.assertIn(b'Cache-Control: no-cache', header)
                self.assertEqual(b'Connection: close' in header, keep == 'no')
                self.assertEqual(body, html.encode() if method == 'GET' else b'')
                if method == 'GET':
                    self.assertIn(f'Content-Length: {len(html.encode())}'.encode(), header)
                else:
                    self.assertNotIn(b'Content-Length:', header)
            print('PASS: Lua GET/HEAD and keep-alive emulation, UTF-8 length and delimiter collision', flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
