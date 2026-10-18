"""Download proxy ChSet files and translate to LinuxMirakc service indices."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def fetch(base, path, token=''):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    with urlopen(Request(base + path, headers=headers), timeout=10) as response:
        return response.read()


def rows(body, fields):
    result = []
    for line in body.decode('utf-8-sig').splitlines():
        if not line.strip():
            continue
        row = line.split('\t')
        if len(row) != fields:
            raise ValueError(f'invalid ChSet: expected {fields} fields')
        result.append(row)
    return result


def generate(base, token):
    services = json.loads(fetch(base, '/mirakurun/api/services'))
    targets = json.loads(fetch(base, '/api/client-view/targets', token))
    if not isinstance(services, list) or not services or not targets.get('success'):
        raise ValueError('チャンネルスキャン未完了、または targets API エラー')
    # Mirror InitChannel(): a new space on every consecutive type transition.
    indices = {}
    previous, space, channel = None, -1, 0
    for service in services:
        kind = service['channel'][0]['type']
        if kind != previous:
            space += 1
            channel = 0
            previous = kind
        if space >= 64:
            raise ValueError('LinuxMirakc supports at most 64 spaces')
        key = (int(service['networkId']), int(service['serviceId']))
        if key in indices:
            raise ValueError('duplicate Mirakurun service identity')
        indices[key] = (space, channel)
        channel += 1
    ch4, ch5 = {}, {}
    for target in targets['targets']:
        if target['type'] != 'driver' or not target['enabled_channels']:
            continue
        query = '?' + urlencode({'tuner': target['name']})
        source4 = rows(fetch(base, '/api/client-view/files/chset4' + query, token), 12)
        source5 = rows(fetch(base, '/api/client-view/files/chset5' + query, token), 9)
        for row in source4:
            nid, tsid, sid = map(int, row[5:8])
            index = indices.get((nid, sid))
            if index is None:
                continue
            row[3:5] = map(str, index)
            key = (nid, tsid, sid)
            ch4.setdefault(key, row)
        for row in source5:
            key = tuple(map(int, row[2:5]))
            if key in ch4:
                ch5.setdefault(key, row)
    if not ch4 or ch4.keys() != ch5.keys():
        raise ValueError('ChSet4/5 に一致するサービスがありません')
    missing = set(indices) - {(nid, sid) for nid, _, sid in ch4}
    if missing:
        raise ValueError('API 更新中、または ChSet にサービス不足。再取得してください')
    # A concurrent proxy scan changes the BonDriver's enumeration. Do not install
    # a mixture of two snapshots; a later refresh will use the completed scan.
    if services != json.loads(fetch(base, '/mirakurun/api/services')):
        raise ValueError('取得中にサービス一覧が変化しました。再取得してください')
    def encode(values):
        return ('\ufeff' + ''.join('\t'.join(row) + '\n' for row in values)).encode('utf-8')
    ordered = sorted(ch4.values(), key=lambda row: tuple(map(int, row[3:5])))
    return encode(ordered), encode(ch5.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    setting = Path(os.environ.get('EDCB_CONFIG_DIR', os.environ.get('EDCB_ROOT', '/var/local/edcb'))) / 'Setting'
    paths = [setting / 'BonDriver_LinuxMirakc(LinuxMirakc).ChSet4.txt', setting / 'ChSet5.txt']
    if not args.refresh and any(p.exists() for p in paths):
        if all(p.stat().st_size > 3 for p in paths if p.exists()) and all(p.exists() for p in paths):
            print('[edcb] 既存 ChSet を維持')
            return
        raise ValueError('ChSet の一部だけ存在。make edcb-chset で再取得してください')
    base = os.environ.get('RECISDB_URL', 'http://recisdb-proxy:40080').rstrip('/')
    result = None
    for attempt in range(3):
        try:
            # The token is persisted even when TOML supplies an explicit override.
            db_path = Path(os.environ.get('RECISDB_DATABASE', '/recisdb/recisdb-proxy.db'))
            with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True) as db:
                row = db.execute('SELECT auth_token FROM web_auth_config WHERE id = 1').fetchone()
            if not row or not row[0]:
                raise ValueError('recisdb-proxy API token がまだありません')
            result = generate(base, row[0])
            break
        except (OSError, ValueError, KeyError, IndexError, TypeError, sqlite3.Error) as error:
            print(f'[edcb] ChSet 取得失敗 ({attempt + 1}/3): {error}', file=sys.stderr)
            if attempt < 2:
                time.sleep(float(os.environ.get('EDCB_RETRY_SECONDS', '2')))
    if result is None:
        raise SystemExit(1)
    setting.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    for path, body in zip(paths, result):
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + '.bak.' + stamp))
        temp = path.with_name(path.name + '.tmp')
        temp.write_bytes(body)
        temp.replace(path)
    print('[edcb] ChSet4/5 取得・LinuxMirakc 列挙番号変換完了')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        print(f'[edcb] {error}', file=sys.stderr)
        sys.exit(1)
