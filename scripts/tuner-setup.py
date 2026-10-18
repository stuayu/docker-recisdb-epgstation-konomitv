#!/usr/bin/env python3
"""Register mapped Linux tuners, await scan history, and refresh consumers."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]


class SetupError(Exception):
    pass


def say(message):
    print('[tuners] ' + message, flush=True)


def settings(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines()
                if '=' in line and not line.lstrip().startswith('#'))


def canonical(path):
    # adapterN and adapterN/frontend0 identify the same physical frontend.
    return path + '/frontend0' if re.fullmatch(r'/dev/dvb/adapter\d+', path) else path


def devices(path):
    """Read only gen-tuners.sh's short device mappings, never parse arbitrary YAML."""
    nodes = set()
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'\s*- "([^"\n]+):(/dev/[^"\n]+)"\s*', line)
        if match:
            nodes.add(match[2])
    result = []
    for node in sorted(nodes):
        frontend = re.fullmatch(r'(/dev/dvb/adapter\d+)/frontend(\d+)', node)
        if frontend:
            if not all(f'{frontend[1]}/{kind}{frontend[2]}' in nodes for kind in ('demux', 'dvr')):
                raise SetupError('DVB frontend に対応する demux/dvr がありません: ' + node)
            result.append(node)
        elif re.fullmatch(r'/dev/(px4video|pt[13]video|pxmlt\d*video|pxm1urvideo|pxs1urvideo|isdbt2071video|isdb2056video)\d+', node):
            result.append(node)
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, base, token):
        parsed = urlsplit(base)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username:
            raise SetupError('管理 API はホストの loopback HTTP URL を指定してください')
        self.base, self.token = base.rstrip('/'), token
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, path, payload=None):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = Request(self.base + path, headers=headers,
                          data=None if payload is None else json.dumps(payload).encode())
        try:
            with self.opener.open(request, timeout=10) as response:
                result = json.load(response)
        except HTTPError as error:
            # Never print bodies/reason/URLs: a server can echo credentials.
            raise SetupError(f'管理 API HTTP {error.code} ({path.split("?")[0]})') from None
        except (OSError, ValueError) as error:
            raise SetupError(f'管理 API 応答取得失敗 ({type(error).__name__})') from None
        if isinstance(result, dict) and result.get('success') is False:
            raise SetupError('管理 API が失敗を返しました: ' + path.split('?')[0])
        return result


def read_token(database, ready_timeout, config):
    settings_text = config.read_text(encoding='utf-8-sig') if config.is_file() else ''
    web = re.search(r'(?ms)^\[web\][ \t]*\r?\n(.*?)(?=^\[|\Z)', settings_text)
    auth = re.search(r'(?m)^\s*auth_enabled\s*=\s*(true|false)\b', web.group(1), re.I) if web else None
    if auth and auth.group(1).lower() == 'false':
        return ''
    deadline = time.monotonic() + ready_timeout
    while True:
        try:
            with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
                row = db.execute('SELECT auth_token FROM web_auth_config WHERE id = 1').fetchone()
            if row and row[0]:
                return row[0]
        except sqlite3.Error:
            pass
        if time.monotonic() >= deadline:
            raise SetupError('token DB を読めません。recisdb-proxy の起動・data/recisdb の所有 UID/GID を確認してください')
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def private_database(database):
    # Existing installations may predate umask 077. Never change another owner's files.
    if database.parent.exists() and database.parent.stat().st_uid == os.getuid():
        database.parent.chmod(0o700)
    for path in (database, Path(str(database) + '-wal'), Path(str(database) + '-shm')):
        if path.exists() and path.stat().st_uid == os.getuid():
            path.chmod(0o600)


def register(api, paths):
    existing = api.call('/api/bondrivers')['bondrivers']
    by_path = {}
    for row in existing:
        key = canonical(row['dll_path'])
        if key in by_path and key in paths:
            raise SetupError('同じ物理デバイスが複数登録済み。BonDriver 画面で整理してください: ' + key)
        by_path[key] = row
        if row['dll_path'].startswith('/dev/') and key not in paths:
            say('警告: Compose にない登録を保持: ' + row['dll_path'] + ' (USB・デバイス番号を確認)')
    added = 0
    for path in paths:
        if path in by_path:
            # Keep user names, groups, disabled capacity and scan preferences.
            continue
        api.call('/api/bondriver', {
            'dll_path': path, 'driver_name': path.removeprefix('/dev/'),
            'max_instances': 1, 'stream_format': 'ts', 'disable_b25': False,
            'auto_scan_enabled': False, 'scan_interval_hours': 24,
            'scan_priority': 0, 'passive_scan_enabled': False,
        })
        added += 1
        say('登録: ' + path + ' (TS / 最大同時数 1 / グループ未指定)')
    rows = api.call('/api/bondrivers')['bondrivers']
    selected = [row for row in rows if canonical(row['dll_path']) in paths]
    if len(selected) != len(paths):
        raise SetupError('登録後のデバイス数が一致しません。make scan を再実行してください')
    for row in selected:
        if row['max_instances'] != 1:
            say('警告: ' + row['dll_path'] + ' の max_instances != 1。既存設定を保持。物理デバイスの二重利用に注意')
    say(f'登録済み {len(selected)} 台 (今回追加 {added} 台)')
    return selected, added


def history(api, driver):
    rows = api.call(f'/api/scan-history?bondriver_id={driver["id"]}')['history']
    return max(rows, key=lambda row: row['id'], default=None)


def scanned(row):
    return bool(row and row['success'] and (row.get('channel_count') or 0) > 0)


class Progress:
    def __init__(self, tui=None):
        self.process = None
        if tui:
            self.process = subprocess.Popen([tui, '--title', 'チューナー登録・チャンネルスキャン',
                                             '--gauge', 'スキャン待機', '12', '78', '0'],
                                            stdin=subprocess.PIPE, text=True)

    def show(self, done, total, text):
        say(f'{done}/{total} 台完了: {text}')
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(f'XXX\n{done * 100 // max(total, 1)}\n{text}\nXXX\n')
                self.process.stdin.flush()
            except BrokenPipeError:
                pass

    def close(self):
        if self.process:
            self.process.stdin.close()
            self.process.wait(timeout=10)


def scan(api, rows, automatic, timeout, poll, progress):
    latest = {row['id']: history(api, row) for row in rows}
    pending = [row for row in rows if not automatic or not scanned(latest[row['id']]) or row.get('is_scanning') or row.get('next_scan_at') == 0]
    for index, row in enumerate(pending):
        if row['max_instances'] != 1:
            raise SetupError('物理デバイスの max_instances を 1 に直してから再実行してください: ' + row['dll_path'])
        previous = latest[row['id']]
        baseline = previous['id'] if previous else 0
        if not row.get('is_scanning') and row.get('next_scan_at') != 0:
            api.call(f'/api/bondriver/{row["id"]}/scan', {})
        started = time.monotonic()
        while True:
            status = api.call(f'/api/bondriver/{row["id"]}')['bondriver']
            result = history(api, row)
            elapsed = int(time.monotonic() - started)
            progress.show(index, len(pending), f'{row["dll_path"]}: ' +
                          ('スキャン中' if status.get('is_scanning') else '開始/終了待機') + f' ({elapsed} 秒)')
            if result and result['id'] > baseline:
                if not scanned(result):
                    raise SetupError(f'{row["dll_path"]}: スキャン失敗または受信 0 局 (履歴 ID {result["id"]})。アンテナ・権限・DVB firmware を確認')
                if not status.get('is_scanning') and status.get('next_scan_at') != 0:
                    latest[row['id']] = result
                    progress.show(index + 1, len(pending), f'{row["dll_path"]}: {result["channel_count"]} 局')
                    break
            if time.monotonic() - started >= timeout:
                raise SetupError(f'{row["dll_path"]}: {timeout:g} 秒でタイムアウト。サーバーのスキャン予約は継続します。履歴・録画状態を確認してから再実行')
            time.sleep(poll)
    return latest


def compose(env, *args, extra=None):
    process_env = {**os.environ, **env, **(extra or {})}
    # Compose diagnostics can include interpolated config. Keep output internal.
    result = subprocess.run([os.environ.get('DOCKER_BIN', 'docker'), 'compose', *args],
                            cwd=ROOT, env=process_env, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise SetupError('docker compose ' + ' '.join(args) + f' が失敗 (終了 {result.returncode})。サービス状態を確認')
    return result.stdout


def backup_write(path, text):
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        shutil.copy2(path, path.with_name(path.name + '.bak.' + stamp))
    # INIs may be bind-mounted or symlinked by EDCB. Preserve their inodes.
    with path.open('w') as output:
        output.write(text)


def sync_count(env_file, count):
    if not 1 <= count <= 99:
        raise SetupError('EDCB チューナー数は 1〜99 が必要')
    body = env_file.read_text()
    updated = re.sub(r'^EDCB_TUNER_COUNT=.*\n?', '', body, flags=re.M).rstrip() + f'\nEDCB_TUNER_COUNT={count}\n'
    if updated != body:
        backup_write(env_file, updated)
        env_file.chmod(0o600)
    path = ROOT / 'config/edcb/EpgTimerSrv.ini'
    legacy = ROOT / 'data/edcb/EpgTimerSrv.ini'
    # configure.py gives a data-side regular INI precedence after EDCB replaces
    # its symlink atomically. Update that authoritative copy while stopped too.
    authoritative = legacy if legacy.is_file() and not legacy.is_symlink() else path
    if not authoritative.exists():
        return
    body = authoritative.read_text(encoding='utf-8-sig')
    section = re.search(r'(?m)^\[BonDriver_LinuxMirakc\.so\]\s*\n([^\[]*)', body)
    if not section:
        raise SetupError('EDCB INI に BonDriver_LinuxMirakc.so 節がありません')
    replacement = re.sub(r'(?m)^Count=.*$', f'Count={count}', section[1])
    if not re.search(r'(?m)^Count=', section[1]):
        replacement = f'Count={count}\n' + section[1]
    updated = body[:section.start(1)] + replacement + body[section.end(1):]
    path.parent.mkdir(parents=True, exist_ok=True)
    for target in dict.fromkeys((path, authoritative)):
        if not target.exists() or target.read_text(encoding='utf-8-sig') != updated:
            backup_write(target, updated)


def count_matches(env, count):
    path = ROOT / 'config/edcb/EpgTimerSrv.ini'
    legacy = ROOT / 'data/edcb/EpgTimerSrv.ini'
    if legacy.is_file() and not legacy.is_symlink():
        path = legacy
    if env.get('EDCB_TUNER_COUNT') != str(count) or not path.exists():
        return False
    section = re.search(r'(?m)^\[BonDriver_LinuxMirakc\.so\]\s*\n([^\[]*)', path.read_text(encoding='utf-8-sig'))
    return bool(section and re.search(r'(?m)^Count=' + str(count) + r'\s*$', section[1]))


def refresh(api, token, env, env_file, count):
    if 'compose.edcb.yaml' in env.get('COMPOSE_FILE', '').split(':'):
        # Fetch/validate all ChSet data before stopping the recorder. Reuse the
        # same generator as make edcb-chset without sharing credentials via argv.
        spec = importlib.util.spec_from_file_location('chset', ROOT / 'docker/edcb/chset.py')
        chset = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(chset)
        chset.generate(api.base, token)
        say(f'EDCB Count を実デバイス数 {count} に同期して ChSet 再取得・再起動')
        result = subprocess.run(['sh', str(ROOT / 'scripts/edcb-chset.sh')], cwd=ROOT,
                                env={**os.environ, **env, 'ENV_FILE': str(env_file), 'EDCB_TUNER_COUNT': str(count)},
                                capture_output=True, text=True)
        if result.returncode:
            raise SetupError('EDCB ChSet 反映/再起動に失敗。make edcb-chset で再試行')
    for service in ('epgstation', 'konomitv'):
        compose(env, 'restart', service)
        say(service + ': 再起動を要求。局一覧・EPG の更新開始')


@contextmanager
def lock():
    path = ROOT / 'data/tuner-setup.lock'
    path.parent.mkdir(exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError('別の make scan / make tuners が実行中') from None
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('scan', 'register', 'edcb-count'), nargs='?', default='scan')
    parser.add_argument('--automatic', action='store_true', help='成功済みスキャンは省略 (setup 用)')
    parser.add_argument('--yes', action='store_true')
    parser.add_argument('--tui')
    parser.add_argument('--timeout', type=float, help='1台ごとの待機上限秒 (既定: サーバー設定 + 待機余裕)')
    parser.add_argument('--poll', type=float, default=float(os.environ.get('TUNER_SCAN_POLL_SECONDS', '5')))
    parser.add_argument('--ready-timeout', type=float, default=30)
    args = parser.parse_args()
    if args.poll <= 0 or (args.timeout is not None and args.timeout <= 0):
        raise SetupError('timeout / poll は正数を指定してください')
    env_file = Path(os.environ.get('ENV_FILE', str(ROOT / '.env'))).resolve()
    if args.command == 'edcb-count':
        sync_count(env_file, int(os.environ['EDCB_TUNER_COUNT']))
        return
    with lock():
        env = settings(env_file)
        if args.command == 'register':
            result = subprocess.run(['sh', str(ROOT / 'scripts/gen-tuners.sh')], cwd=ROOT, capture_output=True)
            if result.returncode:
                raise SetupError('デバイス Compose を再生成できません')
            compose(env, 'up', '-d', '--no-deps', 'recisdb-proxy')
        paths = devices(Path(os.environ.get('TUNERS_COMPOSE_FILE', str(ROOT / 'compose.tuners.yaml'))))
        if not paths:
            say('チューナー未検出。USB・ドライバーを確認して make tuners && make scan')
            return
        database = Path(os.environ.get('RECISDB_DATABASE', str(ROOT / 'data/recisdb/recisdb-proxy.db')))
        private_database(database)
        config = Path(os.environ.get('RECISDB_CONFIG', str(ROOT / 'config/recisdb-proxy/recisdb-proxy.toml')))
        token = read_token(database, args.ready_timeout, config)
        api = API(os.environ.get('RECISDB_URL', 'http://127.0.0.1:' + env.get('RECISDB_WEB_PORT', '40080')), token)
        deadline = time.monotonic() + args.ready_timeout
        while True:
            try:
                api.call('/api/bondrivers')
                break
            except SetupError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        rows, added = register(api, paths)
        if args.command == 'register':
            say('登録完了。続けて make scan でスキャン・各サービスに反映')
            return
        if args.automatic and added and len(rows) > added and not args.yes and sys.stdin.isatty():
            say('デバイス追加を検出。新規デバイスをスキャンして各サービスに反映します')
            declined = (subprocess.run([args.tui, '--yesno', '追加チューナーのスキャンと各サービスへの反映を実行しますか？', '12', '78']).returncode != 0
                        if args.tui else input('実行しますか？ [Y/n]: ').strip().lower() in ('n', 'no'))
            if declined:
                say('登録のみ完了。後で make scan を実行してください')
                return
        config = api.call('/api/scan-config')['config']
        timeout = args.timeout or max(1200, config['scan_timeout_secs'] + 2 * config['check_interval_secs'] + 120)
        progress = Progress(args.tui)
        try:
            latest = scan(api, rows, args.automatic, timeout, args.poll, progress)
        finally:
            progress.close()
        services = api.call('/mirakurun/api/services')
        channels = api.call('/mirakurun/api/channels')
        if not services or not channels:
            raise SetupError('Mirakurun API に受信局がありません')
        signature = {'drivers': [[row['id'], row['dll_path'], latest[row['id']]['id']] for row in rows],
                     'services': hashlib.sha256(json.dumps(services, sort_keys=True).encode()).hexdigest(),
                     'edcb': 'compose.edcb.yaml' in env.get('COMPOSE_FILE', '').split(':')}
        state = ROOT / 'data/tuner-setup.json'
        chsets = [ROOT / 'config/edcb/Setting' / name for name in ('ChSet5.txt', 'BonDriver_LinuxMirakc(LinuxMirakc).ChSet4.txt')]
        try:
            applied = json.loads(state.read_text())
        except (OSError, ValueError):
            applied = None
        if args.automatic and signature == applied and (not signature['edcb'] or
                (count_matches(env, len(rows)) and all(p.exists() and p.stat().st_size > 3 for p in chsets))):
            say('登録・スキャン・反映済み。再スキャンは make scan')
            return
        refresh(api, token, env, env_file, len(rows))
        state.write_text(json.dumps(signature, indent=2) + '\n')
        say(f'完了: {len(channels)} チャンネル / {len(services)} サービス。EPG 取得はバックグラウンドで継続')


if __name__ == '__main__':
    try:
        main()
    except (SetupError, OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.TimeoutExpired) as error:
        # Unexpected exceptions can carry server data; expose only our own messages.
        say('警告: ' + (str(error) if isinstance(error, SetupError) else type(error).__name__))
        say('再実行: make scan (デバイス変更時: make tuners && make scan)。失敗時は既存 ChSet を保持')
        sys.exit(1)
