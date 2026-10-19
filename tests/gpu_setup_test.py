"""GPU selection, real command contracts, fallback and editable-config protection."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import gpu_setup as gpu
from generated_config import remember, replace_generated


class GPUSetupTest(unittest.TestCase):
    def test_detect_vendor_priority_and_pci_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(gpu.detect(root, 'Audio device: NVIDIA [10de:abcd]'), 'none')
            for i, vendor in enumerate(('0x8086', '0x1002', '0x10de')):
                node = root / f'card{i}/device/vendor'
                node.parent.mkdir(parents=True)
                node.write_text(vendor + '\n')
                self.assertEqual(gpu.detect(root, ''), ('intel', 'amd', 'nvidia')[i])
            self.assertEqual(gpu.detect(Path(temp) / 'missing', 'VGA compatible controller: AMD [1002:1234]'), 'amd')

    def test_detect_intel_is_not_misread_as_amd(self):
        intel_line = ('00:02.0 VGA compatible controller [0300]: Intel Corporation '
                      'HD Graphics 530 [8086:1912] (rev 06)')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for node in ('card0', 'renderD128'):
                path = root / f'{node}/device/vendor'
                path.parent.mkdir(parents=True)
                path.write_text('0x8086\n')
            # (a) sysfs reports Intel; the lspci line must not add a false AMD match.
            self.assertEqual(gpu.detect(root, intel_line), 'intel')
            # (b) sysfs empty: the lspci fallback alone must return Intel.
            self.assertEqual(gpu.detect(Path(temp) / 'missing', intel_line), 'intel')
        # (c) AMD identified by PCI vendor ID and by name.
        amd_line = ('06:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. '
                    '[AMD/ATI] Navi 10 [Radeon RX 5700 XT] [1002:731f] (rev c1)')
        self.assertEqual(gpu.detect(Path(temp) / 'missing', amd_line), 'amd')
        self.assertEqual(gpu.detect(Path(temp) / 'missing', amd_line.replace('[1002:731f]', '')), 'amd')

    def test_probe_run_never_passes_no_build(self):
        probe = gpu.Probe(ROOT, {}, 'docker')
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
        with mock.patch('gpu_setup.subprocess.run', return_value=completed) as run:
            self.assertTrue(probe.run('epgstation', 'true'))
        args = run.call_args[0][0]
        self.assertNotIn('--no-build', args)
        self.assertIn('--no-deps', args)
        self.assertIn('-T', args)

    def test_render_node_selection_and_vaapi_never_crosses_vendor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for node, vendor in (('renderD128', '0x8086'), ('renderD129', '0x1002')):
                path = root / f'{node}/device/vendor'
                path.parent.mkdir(parents=True)
                path.write_text(vendor)
            self.assertEqual(gpu.selected_render_node('intel', root), '/dev/dri/renderD128')
            self.assertEqual(gpu.selected_render_node('amd', root), '/dev/dri/renderD129')
            self.assertIsNone(gpu.selected_render_node('nvidia', root))
            self.assertIsNone(gpu.selected_render_node('none', root))

            probe = gpu.Probe(ROOT, {}, 'docker')
            commands = []
            probe.run = lambda service, command: commands.append(command) or ('h264_amf' not in command)
            probe.configured_encode = lambda *args, **kwargs: True
            result = probe.ffmpeg('recisdb-proxy', 'amd', render_node=gpu.selected_render_node('amd', root))
            self.assertEqual(result['backend'], 'vaapi')
            self.assertIn('-vaapi_device /dev/dri/renderD129', commands[1])
            self.assertNotIn('renderD128', commands[1])

            commands.clear()
            probe.run = lambda service, command: commands.append(command) or True
            result = probe.ffmpeg('recisdb-proxy', 'amd', render_node=None)
            self.assertEqual(result['backend'], 'amf')
            self.assertFalse(any('-vaapi_device' in command for command in commands))
            with self.assertRaises(ValueError):
                gpu.ffmpeg_args('vaapi', 'h264')

    def test_probe_actual_docker_stub_and_independent_hevc(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stub = root / 'docker'
            calls = root / 'calls.jsonl'
            stub.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
p=Path(__file__).with_name('calls.jsonl')
with p.open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
# Intel QSV fails; software fallback succeeds.
cmd=sys.argv[-1]
sys.exit(1 if 'h264_qsv' in cmd else 0)
''')
            stub.chmod(0o755)
            probe = gpu.Probe(root, {'COMPOSE_FILE': 'compose.yaml:compose.intel.yaml'}, str(stub))
            result = probe.ffmpeg('epgstation', 'intel')
            self.assertEqual(result['backend'], 'software')
            self.assertTrue(result['h264'])
            self.assertTrue(result['hevc'])
            entries = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(len(entries), 5)
            for entry in entries:
                self.assertIn('--no-deps', entry)
                self.assertIn('--entrypoint', entry)
            self.assertIn('-t 1', entries[0][-1])
            self.assertIn('libx264', entries[1][-1])
            self.assertIn('node "$d/enc.js" h264 720', entries[2][-1])
            self.assertIn('FFPROBE=ffprobe', entries[2][-1])
            self.assertNotIn('enc.js.template', entries[2][-1])
            self.assertNotIn('-vaapi_device', entries[1][-1])

    def test_amd_epg_uses_amf_and_recisdb_prefers_amf(self):
        probe = gpu.Probe(ROOT, {}, 'docker')
        commands = []
        probe.run = lambda service, command: commands.append(command) or True
        self.assertEqual(probe.ffmpeg('epgstation', 'amd')['backend'], 'amf')
        self.assertTrue(any('h264_amf' in command for command in commands))
        commands.clear()
        self.assertEqual(probe.ffmpeg('recisdb-proxy', 'amd')['backend'], 'amf')
        self.assertTrue(any('_amf' in command for command in commands))

    def test_all_encoders_fail_preserves_config(self):
        probe = gpu.Probe(ROOT, {}, 'docker')
        probe.run = lambda *args: False
        self.assertIsNone(probe.ffmpeg('epgstation', 'nvidia')['backend'])

    def test_provenance_backup_inode_and_manual_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'config/epgstation/config.yml'
            path.parent.mkdir(parents=True)
            path.write_text('generated\n')
            remember(root, path)
            inode = path.stat().st_ino
            self.assertTrue(replace_generated(root, path, 'gpu\n'))
            self.assertEqual(inode, path.stat().st_ino)
            self.assertEqual(path.with_name('config.yml.pre-config-migration').read_text(), 'generated\n')
            path.write_text('manual\n')
            self.assertFalse(replace_generated(root, path, 'software\n'))
            self.assertEqual(path.read_text(), 'manual\n')
            # Untracked custom file is never adopted based on a partial match.
            self.assertFalse(replace_generated(root, path, 'gpu\n', 'generated\n'))
            path.write_text('generated\n')
            self.assertFalse(replace_generated(root, path, 'gpu\n', 'generated\n'))
            self.assertEqual(path.read_text(), 'generated\n')

    def test_corrupt_provenance_never_authorizes_custom_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'config/custom.yml'
            path.parent.mkdir()
            path.write_text('manual\n')
            for content in ('[]', 'null', '{"config/custom.yml": 42}', 'broken'):
                (root / 'config/.generated-configs.json').write_text(content)
                self.assertFalse(replace_generated(root, path, 'gpu\n'))
                self.assertEqual(path.read_text(), 'manual\n')

    def test_configured_profile_failure_falls_back(self):
        probe = gpu.Probe(ROOT, {}, 'docker')
        probe.run = lambda *args: True
        attempts = []
        def configured(service, binary, backend, codec, render_node=None):
            attempts.append((backend, codec))
            return backend != 'qsv'
        probe.configured_encode = configured
        self.assertEqual(probe.ffmpeg('epgstation', 'intel')['backend'], 'software')
        self.assertEqual(attempts[0], ('qsv', 'h264'))
        self.assertIn(('software', 'hevc'), attempts)

    def test_cli_applies_all_services_and_preserves_later_manual_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(ROOT / 'templates', root / 'templates')
            env = root / '.env'
            env.write_text('COMPOSE_FILE=compose.yaml:compose.amd.yaml:compose.amatsukaze.yaml:compose.amatsukaze.amd.yaml\n'
                           'MARIADB_PASSWORD=test-only\nBONCAS_B25_HOST=relay\nBONCAS_B25_PORT=6900\n')
            subprocess.run([sys.executable, str(ROOT / 'scripts/render-config.py'), '--root', str(root),
                            '--env', str(env), 'first-run'], check=True, capture_output=True)
            preview = gpu.module('gpu_cli_test_profiles', 'preview-profiles.py')
            database = root / 'data/recisdb/recisdb-proxy.db'
            database.parent.mkdir(parents=True, exist_ok=True)
            binary = '/opt/recisdb-proxy/thirdparty/ffmpeg/ffmpeg'
            with sqlite3.connect(database) as db:
                db.executescript('''CREATE TABLE encode_profiles (
                    id INTEGER PRIMARY KEY, name TEXT, purpose TEXT, codec TEXT, container TEXT,
                    target_bitrate INTEGER, extra_args TEXT, is_enabled INTEGER, created_at INTEGER);
                    CREATE TABLE preview_encoder_config (id INTEGER, command_path TEXT);
                    CREATE TABLE web_auth_config (id INTEGER, auth_token TEXT);''')
                db.execute('INSERT INTO preview_encoder_config VALUES (1, ?)', (binary,))
                db.execute('INSERT INTO web_auth_config VALUES (1, ?)', ('secret-not-in-logs',))
                for i, name, purpose, bitrate, four_k in ((1, 'preview-h264', 'preview', 2000000, False),
                                                         (2, 'preview-4k', 'preview4k', 4000000, True)):
                    db.execute('INSERT INTO encode_profiles VALUES (?,?,?,?,?,?,?,?,?)',
                               (i, name, purpose, 'h264', 'mpegts', bitrate,
                                preview.ffmpeg_args('libx264', four_k), 1, 0))
            stub = root / 'docker'
            stub.write_text('#!/usr/bin/env python3\nimport json,sys\n'
                            'if "run" in sys.argv and "recisdb-proxy" in sys.argv and "_amf" in sys.argv[-1]: sys.exit(1)\n'
                            'if "exec" in sys.argv:\n'
                            f' print(json.dumps({{"success": True, "config": {{"command_path": {binary!r}}}}}))\n')
            stub.chmod(0o755)
            drm = root / 'sys-drm'
            for node, vendor in (('renderD128', '0x8086'), ('renderD129', '0x1002')):
                path = drm / node / 'device/vendor'
                path.parent.mkdir(parents=True)
                path.write_text(vendor)
            command = [sys.executable, str(ROOT / 'scripts/gpu_setup.py'), 'probe', '--root', str(root),
                       '--env', str(env), '--docker-bin', str(stub), '--sys-drm', str(drm), '--gpu', 'amd']
            output = subprocess.run(command, check=True, capture_output=True, text=True).stdout
            self.assertIn('警告: 選択した GPU の render node は /dev/dri/renderD129', output)
            self.assertIn('docker compose restart recisdb-proxy', output)
            report = json.loads((root / 'config/gpu-probe.json').read_text())
            self.assertEqual(report['services']['epgstation']['backend'], 'amf')
            self.assertEqual(report['services']['konomitv']['encoder'], 'VCEEncC')
            self.assertEqual(report['services']['amatsukaze']['encoder'], 'VCEEncC')
            self.assertEqual(report['services']['recisdb-proxy']['profiles']['updated'], ['preview-h264', 'preview-4k'])
            self.assertEqual(report['services']['recisdb-proxy']['backend'], 'vaapi')
            with sqlite3.connect(database) as db:
                for (args,) in db.execute('SELECT extra_args FROM encode_profiles'):
                    self.assertIn('-vaapi_device /dev/dri/renderD129', args)
                    self.assertNotIn('renderD128', args)
            summary = subprocess.run([sys.executable, str(ROOT / 'scripts/gpu_setup.py'), 'summary',
                                      '--root', str(root)], check=True, capture_output=True, text=True)
            self.assertIn('docker compose restart recisdb-proxy', summary.stdout)
            self.assertIn('<EncoderType>VCEEnc</EncoderType>', (root / 'config/amatsukaze/profile/EPGStation.profile').read_text())
            self.assertIn('encoder: "VCEEncC"', (root / 'config/konomitv/config.yaml').read_text())
            path = root / 'config/epgstation/config.yml'
            manual = path.read_text() + '# edited by user\n'
            path.write_text(manual)
            command[-1] = 'none'
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(path.read_text(), manual)
            report = json.loads((root / 'config/gpu-probe.json').read_text())
            self.assertEqual(report['services']['epgstation']['configuration'], 'manual-preserved')
            self.assertNotIn('secret-not-in-logs', (root / 'config/gpu-probe-log.json').read_text())

    def test_render_presets_match_upstream_shape(self):
        spec = importlib.util.spec_from_file_location('render_test_gpu', ROOT / 'scripts/render-config.py')
        render = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(render)
        env = {'MARIADB_PASSWORD': 'safe', 'RECORDED_DIR': '/recorded',
               'COMPOSE_FILE': 'compose.yaml:compose.amatsukaze.yaml'}
        baseline = render.render('epgstation', (ROOT / 'templates/epgstation/config.yml.example').read_text(), env)
        baseline_yaml = json.loads(subprocess.run(['ruby', '-ryaml', '-rjson', '-e',
                                                  'puts JSON.generate(YAML.load(STDIN.read))'], input=baseline,
                                     text=True, capture_output=True, check=True).stdout)
        for backend, hw_encoder in (('qsv', 'qsv'), ('amf', 'vce'), ('nvenc', 'nvenc'), ('software', 'auto')):
            text = gpu.epg_preset(baseline, {'backend': backend, 'hevc': True}, 4)
            parsed = subprocess.run(['ruby', '-ryaml', '-rjson', '-e',
                                     'puts JSON.generate(YAML.load(STDIN.read))'], input=text,
                                    text=True, capture_output=True, check=True)
            config = json.loads(parsed.stdout)
            self.assertEqual(config['stream'], baseline_yaml['stream'])
            self.assertEqual(config['hardwareEncoder'], hw_encoder)
            original_h264 = next(entry for entry in baseline_yaml['encode'] if entry['id'] == 'h264-720p')
            generated_h264 = next(entry for entry in config['encode'] if entry['id'] == 'h264-720p')
            self.assertEqual(generated_h264, original_h264)
            self.assertEqual([entry for entry in config['encode'] if entry['id'] != 'hevc-720p'],
                             baseline_yaml['encode'])
            self.assertEqual(gpu.epg_preset(text, {'backend': backend, 'hevc': True}, 4), text)
            self.assertNotIn('encodePresets', config)
            self.assertEqual(config['concurrentEncodeNum'], 2)
            self.assertIn('amatsukaze', [entry['id'] for entry in config['encode']])
            self.assertIn('h264-720p', [entry['id'] for entry in config['encode']])
            self.assertIn('hevc-720p', [entry['id'] for entry in config['encode']])
        text = gpu.epg_preset(baseline, {'backend': 'qsv', 'hevc': False}, 1)
        self.assertNotIn('id: hevc-720p', text)
        self.assertIn('encodeProcessNum: 1', text)

    def test_epgstation_image_materializes_enc_js(self):
        dockerfile = (ROOT / 'docker/epgstation/Dockerfile').read_text()
        self.assertIn('COPY --from=builder /src/ /app/', dockerfile)
        self.assertRegex(dockerfile, r'RUN cp /app/config/enc\.js\.template /app/config/enc\.js')


if __name__ == '__main__':
    unittest.main()
