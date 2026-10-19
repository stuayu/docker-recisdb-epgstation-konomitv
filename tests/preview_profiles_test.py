"""Exercise preview profile migration, SQLite writer locking and authenticated API reads."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('preview_profiles', ROOT / 'scripts/preview-profiles.py')
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)
SECRET = 'private-API-token-which-must-not-appear-on-command-lines'


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data/recisdb'
        self.data.mkdir(parents=True)
        self.path = self.data / 'recisdb-proxy.db'
        self.config = self.root / 'config/recisdb-proxy/recisdb-proxy.toml'
        self.config.parent.mkdir(parents=True)
        self.config.write_text('[web]\nauth_enabled = true\n')
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE encode_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    purpose TEXT NOT NULL, codec TEXT NOT NULL, container TEXT DEFAULT 'mpegts',
                    target_bitrate INTEGER, extra_args TEXT, is_enabled INTEGER DEFAULT 1,
                    created_at INTEGER DEFAULT (strftime('%s', 'now')));
                CREATE TABLE preview_encoder_config (id INTEGER, command_path TEXT);
                INSERT INTO preview_encoder_config VALUES (1, '/opt/thirdparty/FFmpeg/ffmpeg');
                CREATE TABLE web_auth_config (id INTEGER, auth_token TEXT);
                CREATE TABLE clients (id INTEGER, encode_profile_id INTEGER REFERENCES encode_profiles(id));
            ''')
            db.execute('INSERT INTO web_auth_config VALUES (1, ?)', (SECRET,))
            for name, purpose, bitrate, args in (
                    ('preview-h264', 'preview', 2000000, preview.RIGAYA),
                    ('preview-4k', 'preview4k', 4000000, preview.RIGAYA_4K),
                    ('manual-other', 'record', 9000000, 'custom')):
                db.execute('INSERT INTO encode_profiles (name,purpose,codec,container,target_bitrate,extra_args) '
                           'VALUES (?,?,?,?,?,?)', (name, purpose, 'h264', 'mpegts', bitrate, args))
            db.execute('INSERT INTO clients VALUES (50, 1)')

    def rows(self):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM encode_profiles ORDER BY id')]

    def edit(self, **fields):
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE encode_profiles SET ' + ','.join(key + '=?' for key in fields)
                       + ' WHERE id=1', tuple(fields.values()))

    def test_all_backends_and_vaapi_upload_path(self):
        for backend, encoder in preview.BACKENDS.items():
            with self.subTest(backend=backend):
                result = preview.apply_profiles(self.root, backend=backend, render_node='/dev/dri/renderD129')
                self.assertEqual(result['encoder'], encoder)
                for row in self.rows()[:2]:
                    args = row['extra_args']
                    self.assertIn('-c:v ' + encoder + ' ', args)
                    self.assertIn('-map 0:d? -copy_unknown', args)
                    self.assertIn('-c:d copy', args)
                    if backend == 'vaapi':
                        self.assertLess(args.index('-vaapi_device /dev/dri/renderD129'), args.index('-i pipe:0'))
                        self.assertIn(',setsar=1,format=nv12,hwupload ', args)
                    else:
                        self.assertNotIn('hwupload', args)
                self.assertNotIn('yadif', self.rows()[1]['extra_args'])
                self.assertIn('-skip_frame:v noref', self.rows()[1]['extra_args'])

    def test_backup_precedes_write_and_preserves_ids_references(self):
        before = self.rows()
        result = preview.apply_profiles(self.root, backend='qsv')
        self.assertEqual(result['updated'], ['preview-h264', 'preview-4k'])
        self.assertEqual(result['activation'], 'new-preview-session')
        self.assertEqual(result['restart_command'], 'docker compose restart recisdb-proxy')
        backup = Path(result['backup'])
        self.assertEqual(json.loads(backup.read_text())['profiles'], before)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        after = self.rows()
        for old, new in zip(before, after):
            self.assertEqual({key: value for key, value in old.items() if key != 'extra_args'},
                             {key: value for key, value in new.items() if key != 'extra_args'})
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT * FROM clients').fetchall(), [(50, 1)])
        again = preview.apply_profiles(self.root, backend='qsv')
        self.assertEqual(again['updated'], [])
        self.assertIsNone(again['backup'])
        self.assertIsNone(again['restart_command'])
        self.assertEqual(len(list(backup.parent.glob('*.json'))), 1)

    def test_existing_connection_reads_committed_profiles_and_notice_explains_sessions(self):
        # Model the server's per-request SELECT using a connection opened
        # before migration. No service restart/reopen is needed for new reads.
        with sqlite3.connect(self.path) as runtime:
            before = runtime.execute('SELECT extra_args FROM encode_profiles WHERE id=1').fetchone()[0]
            report = preview.apply_profiles(self.root, backend='qsv')
            after = runtime.execute('SELECT extra_args FROM encode_profiles WHERE id=1').fetchone()[0]
        self.assertNotEqual(before, after)
        self.assertEqual(after, preview.ffmpeg_args('h264_qsv'))
        output = io.StringIO()
        preview.print_activation_notice(report, file=output)
        notice = output.getvalue()
        self.assertIn('新規プレビュー', notice)
        self.assertIn('既存プレビュー', notice)
        self.assertIn('停止・再接続', notice)
        self.assertIn('docker compose restart recisdb-proxy', notice)
        output = io.StringIO()
        preview.print_activation_notice(preview.apply_profiles(self.root, backend='qsv'), file=output)
        self.assertEqual(output.getvalue(), '')

    def test_cli_emits_restart_advice_without_running_docker_or_changing_json_contract(self):
        command = [sys.executable, str(ROOT / 'scripts/preview-profiles.py'), '--root', str(self.root),
                   '--backend', 'qsv', '--docker-bin', '/nonexistent/docker']
        result = subprocess.run(command, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)['updated'], ['preview-h264', 'preview-4k'])
        self.assertIn('docker compose restart recisdb-proxy', result.stderr)
        unchanged = subprocess.run(command, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(unchanged.stdout)['updated'], [])
        self.assertEqual(unchanged.stderr, '')

    def test_manual_arguments_and_metadata_preserved(self):
        for field, value in (('extra_args', preview.ffmpeg_args('libx264') + ' -threads 2'),
                             ('extra_args', preview.ffmpeg_args('libx264').replace('-vf ', '-vf  ')),
                             ('target_bitrate', 3500000), ('is_enabled', 0), ('codec', 'hevc'),
                             ('purpose', 'view'), ('container', 'mp4'), ('name', 'my-preview')):
            with self.subTest(field=field):
                self.edit(name='preview-h264', purpose='preview', codec='h264', container='mpegts',
                          target_bitrate=2000000, is_enabled=1, extra_args=preview.RIGAYA)
                self.edit(**{field: value})
                before = self.rows()[0]
                preview.apply_profiles(self.root, backend='nvenc')
                self.assertEqual(self.rows()[0], before)

    def test_missing_and_duplicate_profiles_are_not_created_or_changed(self):
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM encode_profiles WHERE id=2')
            db.execute("INSERT INTO encode_profiles (name,purpose,codec) VALUES ('preview-h264','preview','h264')")
        before = self.rows()
        result = preview.apply_profiles(self.root, backend='amf')
        self.assertEqual(self.rows(), before)
        self.assertEqual(len(result['skipped']), 2)
        self.assertIsNone(result['backup'])

    def test_backup_failure_rolls_back(self):
        before = self.rows()
        with patch.object(preview, 'backup_profiles', side_effect=OSError('backup unavailable')):
            with self.assertRaises(OSError):
                preview.apply_profiles(self.root, backend='qsv')
        self.assertEqual(self.rows(), before)

    def test_unknown_schema_and_missing_database_are_never_written(self):
        with sqlite3.connect(self.path) as db:
            db.execute('ALTER TABLE encode_profiles ADD COLUMN future_field TEXT')
        before = self.rows()
        with self.assertRaisesRegex(preview.ProfileError, 'Unknown'):
            preview.apply_profiles(self.root, backend='qsv')
        self.assertEqual(self.rows(), before)
        self.path.unlink()
        with self.assertRaises(preview.ProfileError):
            preview.apply_profiles(self.root, backend='qsv')
        self.assertFalse(self.path.exists())

    def test_changed_command_path_and_invalid_vaapi_fail_before_backup(self):
        before = self.rows()
        with self.assertRaisesRegex(preview.ProfileError, 'changed'):
            preview.apply_profiles(self.root, backend='qsv', command_path='/wrong/ffmpeg')
        for node in (None, '/dev/dri/renderD128 -bad', '/tmp/device'):
            with self.assertRaises(preview.ProfileError):
                preview.apply_profiles(self.root, backend='vaapi', render_node=node)
        self.assertEqual(self.rows(), before)
        self.assertFalse((self.data / 'preview-profile-backups').exists())

    def test_concurrent_manual_edit_is_observed_after_writer_lock(self):
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE encode_profiles SET extra_args='concurrent administrator edit' WHERE id=1")
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/preview-profiles.py'),
                                    '--root', str(self.root), '--backend', 'qsv'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        # Keep the lock long enough to show the helper waits rather than taking
        # an old read snapshot and clobbering the edit once the lock is released.
        time.sleep(0.2)
        self.assertIsNone(process.poll())
        db.commit()
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(self.rows()[0]['extra_args'], 'concurrent administrator edit')
        self.assertEqual(json.loads(stdout)['updated'], ['preview-4k'])

    def test_api_stub_receives_auth_only_via_stdin_and_compose_environment(self):
        docker = self.root / 'docker-stub'
        docker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
config = sys.stdin.read()
assert args[:5] == ['compose', 'exec', '-T', 'recisdb-proxy', 'curl']
assert '--config' in args and args[args.index('--config')+1] == '-'
assert 'private-API-token' not in ' '.join(args)
assert json.loads(config.split(' = ', 1)[1]) == 'Authorization: Bearer ' + os.environ['TEST_TOKEN']
assert os.environ['COMPOSE_FILE'] == 'compose.yaml:compose.intel.yaml'
assert args[-1] == 'http://127.0.0.1:40080/api/preview-config'
print(json.dumps({'success':True, 'config':{'enabled':True,'command_path':'/native/ffmpeg','preprocessor_path':'/native/tsreadex'}}))
''')
        docker.chmod(0o755)
        env = {'TEST_TOKEN': SECRET, 'COMPOSE_FILE': 'compose.yaml:compose.intel.yaml'}
        result = preview.read_preview_config(self.root, env, str(docker))
        self.assertEqual(result['command_path'], '/native/ffmpeg')
        before = self.config.read_text()
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM web_auth_config')
        with self.assertRaisesRegex(preview.ProfileError, 'authentication'):
            preview.read_preview_config(self.root, env, str(docker))
        self.assertEqual(self.config.read_text(), before)

    def test_api_failures_redact_diagnostics_and_do_not_disable_auth(self):
        docker = self.root / 'docker-stub'
        docker.write_text('#!/bin/sh\ncat >&2\nexit 22\n')
        docker.chmod(0o755)
        with self.assertRaises(preview.ProfileError) as caught:
            preview.read_preview_config(self.root, {}, str(docker))
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertIn('auth_enabled = true', self.config.read_text())


class TemplateTest(unittest.TestCase):
    def test_upstream_golden_software_arguments(self):
        golden = ('-hide_banner -loglevel error -fflags +discardcorrupt+genpts '
                  '-analyzeduration 600000 -probesize 1000000 -f mpegts -i pipe:0 '
                  '-map 0:v:0 -map 0:a:0 -map 0:d? -copy_unknown '
                  '-vf yadif=0:-1:1,scale=1280:720,setsar=1 '
                  '-c:v libx264 -preset veryfast -tune zerolatency -profile:v high '
                  '-b:v 2000k -maxrate 3000k -bufsize 4000k -g 60 -aspect 16:9 '
                  '-c:a aac -b:a 192k -ar 48000 -ac 2 '
                  '-af aresample=async=1:min_hard_comp=0.100000:first_pts=0 '
                  '-c:d copy -f mpegts -flush_packets 1 -muxdelay 0 -muxpreload 0 pipe:1')
        self.assertEqual(preview.ffmpeg_args('libx264'), golden)
        self.assertTrue(preview.auto_generated(golden))
        self.assertFalse(preview.auto_generated(golden.replace('2000k', '2001k')))

    def test_all_current_and_legacy_templates_and_manual_edits(self):
        for four_k in (False, True):
            for encoder in preview.ENCODERS:
                for args in preview.legacy_args(encoder, four_k):
                    self.assertTrue(preview.auto_generated(args, four_k), args)
                args = preview.ffmpeg_args(encoder, four_k, '/dev/dri/renderD147')
                self.assertTrue(preview.auto_generated(args, four_k), args)
                self.assertFalse(preview.auto_generated(args + ' -threads 2', four_k))
                if four_k:
                    for decoder in preview.DECODERS:
                        args = preview.ffmpeg_args(encoder, True, '/dev/dri/renderD147', decoder)
                        self.assertTrue(preview.auto_generated(args, True), args)
        for empty in ('', ' \n', None):
            self.assertTrue(preview.auto_generated(empty))
            self.assertTrue(preview.auto_generated(empty, True))
        self.assertTrue(preview.auto_generated(preview.LEGACY_RIGAYA))
        self.assertFalse(preview.auto_generated(preview.RIGAYA_4K))
        self.assertFalse(preview.auto_generated(preview.RIGAYA, True))


if __name__ == '__main__':
    unittest.main()
