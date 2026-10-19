#!/usr/bin/env python3
"""Apply a probed FFmpeg backend to untouched, seeded preview profiles.

The Web API has no conditional update operation. Writes therefore use SQLite's
writer lock, snapshot + JSON backup + UPDATE in one transaction. No executable
paths, profile IDs, client references, or administrator-edited rows are changed.
Call only after probing the *running image's configured FFmpeg* with the selected
backend and these filter/tuning options. Listing an encoder is not a probe.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile

BACKENDS = {'software': 'libx264', 'qsv': 'h264_qsv', 'amf': 'h264_amf',
            'vaapi': 'h264_vaapi', 'nvenc': 'h264_nvenc'}
ENCODERS = tuple(BACKENDS.values()) + ('h264_videotoolbox',)
DECODERS = ('hevc_qsv', 'hevc_cuvid', 'hevc_vaapi', 'hevc_videotoolbox')
COLUMNS = ('id', 'name', 'purpose', 'codec', 'container', 'target_bitrate',
           'extra_args', 'is_enabled', 'created_at')
TUNING = {
    'libx264': '-preset veryfast -tune zerolatency -profile:v high',
    'h264_qsv': '-preset veryfast -look_ahead 0 -async_depth 1 -profile:v high',
    'h264_nvenc': '-preset p4 -tune ll -rc vbr -profile:v high',
    'h264_amf': '-usage lowlatency -quality speed -profile:v high',
    'h264_videotoolbox': '-realtime 1 -allow_sw 1 -profile:v high',
    'h264_vaapi': '',
}
RIGAYA = ('--avhw -i - --input-format mpegts --input-analyze 0.6 --input-probesize 1000K '
          '--interlace tff --vpp-deinterlace normal -c h264 --profile high '
          '--vbr 2000 --max-bitrate 3000 --gop-len 60 --dar 16:9 '
          '--audio-codec aac --audio-bitrate 192 --audio-samplerate 48000 '
          '--data-copy timed_id3 --output-format mpegts -o -')
RIGAYA_4K = ('--avhw -i - --input-format mpegts --input-analyze 0.6 --input-probesize 1000K '
             '--vpp-resize algo=auto --output-res 1920x1080 -c h264 --profile high '
             '--vbr 4000 --max-bitrate 6000 --gop-len 60 --dar 16:9 '
             '--audio-codec aac --audio-bitrate 192 --audio-samplerate 48000 '
             '--data-copy timed_id3 --output-format mpegts -o -')
LEGACY_RIGAYA = ('-i - -o - --preserve-other-services -e QSVEncC64.exe -i - '
                 '--input-format mpegts --tff --vpp-deinterlace normal '
                 '-c h264 --vbr 2000 --max-bitrate 3000 --gop-len 60 '
                 '--output-format mpegts -o -')
PREFIX = ('-hide_banner -loglevel error -fflags +discardcorrupt+genpts '
          '-analyzeduration 600000 -probesize 1000000 ')
MAP = '-map 0:v:0 -map 0:a:0 -map 0:d? -copy_unknown '
AUDIO = '-c:a aac -b:a 192k -ar 48000 -ac 2 '
RESAMPLE = '-af aresample=async=1:min_hard_comp=0.100000:first_pts=0 '
OUTPUT = '-c:d copy -f mpegts -flush_packets 1 -muxdelay 0 -muxpreload 0 pipe:1'
THROTTLE = '-skip_loop_filter:v all -skip_frame:v noref '


class ProfileError(Exception):
    pass


def render_device(node):
    if not node or not re.fullmatch(r'/dev/dri/renderD[0-9]+', node):
        raise ProfileError('VA-API requires the render node that passed the FFmpeg probe')
    return node


def ffmpeg_args(encoder, four_k=False, render_node=None, decoder=None, vaapi_legacy=False):
    """Match origin/feature/proxy's current templates, including VA-API upload."""
    if encoder not in ENCODERS:
        raise ProfileError('Unsupported FFmpeg encoder')
    pre_input, suffix = '', ''
    if encoder == 'h264_vaapi' and not vaapi_legacy:
        pre_input = '-vaapi_device ' + render_device(render_node) + ' '
        suffix = ',format=nv12,hwupload'
    tuning = TUNING[encoder] or '-profile:v high'
    if decoder and decoder not in DECODERS:
        raise ProfileError('Unsupported HEVC decoder')
    if not four_k:
        return (PREFIX + pre_input + '-f mpegts -i pipe:0 ' + MAP
                + '-vf yadif=0:-1:1,scale=1280:720,setsar=1' + suffix + ' '
                + f'-c:v {encoder} {tuning} -b:v 2000k -maxrate 3000k -bufsize 4000k '
                + '-g 60 -aspect 16:9 ' + AUDIO + RESAMPLE + OUTPUT)
    decode = '-c:v ' + decoder + ' ' if decoder else THROTTLE
    scale = 'scale=1920:1080,setsar=1' if decoder else 'scale=1280:720:flags=fast_bilinear,setsar=1'
    bitrate = '4000k -maxrate 6000k -bufsize 8000k' if decoder else '3000k -maxrate 4500k -bufsize 6000k'
    return (PREFIX + decode + pre_input + '-f mpegts -i pipe:0 ' + MAP
            + '-vf ' + scale + suffix + ' ' + f'-c:v {encoder} {tuning} -b:v {bitrate} '
            + '-g 60 -aspect 16:9 ' + AUDIO + RESAMPLE + OUTPUT)


def legacy_args(encoder, four_k=False):
    tuning = TUNING[encoder]
    if four_k:
        for decode, scale in (('', 'scale=1920:1080'),
                              (THROTTLE, 'scale=1920:1080:flags=fast_bilinear')):
            yield (PREFIX + decode + '-f mpegts -i pipe:0 ' + MAP + '-vf ' + scale + ' '
                   + f'-c:v {encoder} {tuning} -b:v 4000k -maxrate 6000k -bufsize 8000k '
                   + '-g 60 -aspect 16:9 ' + AUDIO + RESAMPLE + OUTPUT)
    else:
        yield (PREFIX + '-f mpegts -i pipe:0 ' + MAP + '-vf yadif=0:-1:1 '
               + f'-c:v {encoder} {tuning} -b:v 2000k -maxrate 3000k -bufsize 4000k '
               + '-g 60 -aspect 16:9 ' + AUDIO + RESAMPLE + OUTPUT)
        yield (PREFIX.replace('+discardcorrupt+genpts', '+discardcorrupt')
               + '-f mpegts -i pipe:0 ' + MAP + '-vf yadif=0:-1:1 '
               + f'-c:v {encoder} -b:v 2000k -maxrate 3000k -bufsize 4000k '
               + '-g 60 -aspect 16:9 ' + AUDIO + '-c:d copy -f mpegts -flush_packets 1 pipe:1')


def auto_generated(args, four_k=False):
    """Exact template matching; arbitrary whitespace changes are manual edits."""
    if args is None or not args.strip():
        return True
    args = args.strip()
    if args in ((RIGAYA_4K,) if four_k else (RIGAYA, LEGACY_RIGAYA)):
        return True
    node = re.search(r'(?:^| )-vaapi_device (/dev/dri/renderD[0-9]+)(?: |$)', args)
    for encoder in ENCODERS:
        if args in legacy_args(encoder, four_k):
            return True
        variants = [None] + list(DECODERS) if four_k else [None]
        for decoder in variants:
            if encoder == 'h264_vaapi':
                # No render node was available in older generators; retain
                # their plain template as a migration sentinel too.
                if args == ffmpeg_args(encoder, four_k, decoder=decoder, vaapi_legacy=True):
                    return True
                if node and args == ffmpeg_args(encoder, four_k, node[1], decoder):
                    return True
            elif args == ffmpeg_args(encoder, four_k, decoder=decoder):
                return True
    return False


def database_path(root):
    # entrypoint.sh fixes this location irrespective of [database] in TOML.
    database = Path(root).resolve() / 'data/recisdb/recisdb-proxy.db'
    if not database.is_file() or database.is_symlink():
        raise ProfileError('Existing data/recisdb/recisdb-proxy.db is required')
    return database


def connect_existing(root, writable=False):
    database = database_path(root)
    return sqlite3.connect(database.as_uri() + ('?mode=rw' if writable else '?mode=ro'),
                           uri=True, timeout=10)


def read_preview_config(root, env=None, docker_bin='docker'):
    """Read runtime paths through authenticated loopback curl inside the service.

    Send the token on curl's stdin, never its argv or diagnostic output. The
    effective TOML override is persisted in web_auth_config by recisdb startup.
    Missing credentials are allowed only for explicit auth_enabled=false.
    """
    with closing(connect_existing(root)) as db:
        try:
            row = db.execute('SELECT auth_token FROM web_auth_config WHERE id = 1').fetchone()
        except sqlite3.Error:
            row = None
    token = row[0] if row and row[0] else ''
    if not token:
        config = Path(root) / 'config/recisdb-proxy/recisdb-proxy.toml'
        text = config.read_text(encoding='utf-8-sig')
        web = re.search(r'(?ms)^\[web\][ \t]*\r?\n(.*?)(?=^\[|\Z)', text)
        if not web or not re.search(r'(?mi)^\s*auth_enabled\s*=\s*false\s*(?:#.*)?$', web[1]):
            raise ProfileError('API authentication token is unavailable; authentication was preserved')
    if any(char in token for char in '\r\n'):
        raise ProfileError('Invalid API authentication token')
    curl_config = 'header = ' + json.dumps('Authorization: Bearer ' + token) + '\n' if token else ''
    env_values = load_env(env) if isinstance(env, (str, Path)) else env or {}
    try:
        result = subprocess.run(
            [docker_bin, 'compose', 'exec', '-T', 'recisdb-proxy', 'curl', '--config', '-',
             '--fail', '--silent', '--show-error', '--max-time', '15', '--noproxy', '*',
             'http://127.0.0.1:40080/api/preview-config'],
            cwd=root, env={**os.environ, **env_values}, input=curl_config,
            text=True, capture_output=True, timeout=25)
        if result.returncode:
            raise ProfileError('Runtime preview config API request failed')
        payload = json.loads(result.stdout)
        config = payload['config']
        if payload.get('success') is not True or not isinstance(config.get('command_path'), str):
            raise ValueError()
        return config
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        raise ProfileError('Runtime preview config API response is unavailable') from None


def backup_profiles(database, rows):
    directory = database.parent / 'preview-profile-backups'
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink():
        raise ProfileError('Preview backup directory must not be a symlink')
    fd, name = tempfile.mkstemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'),
                                suffix='.json', dir=directory)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump({'format': 1, 'profiles': rows}, output, ensure_ascii=False, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    # Ensure the backup's directory entry is durable before touching the DB.
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return name


def apply_profiles(root, env=None, docker_bin='docker', backend='software', render_node=None,
                   command_path=None):
    """Apply a successful external probe under a single SQLite writer lock.

    env/docker_bin are accepted for the same integration contract as the API
    reader. origin/feature/proxy's POST /api/encode-profiles/:id has no
    conditional update, so it cannot protect an intervening manual edit.
    Keep the check and write under one SQLite writer lock instead.
    Profiles are loaded from SQLite for each new preview request; existing
    encoder sessions retain their arguments until disconnected/restarted.
    command_path, when supplied, guards against a changed runtime executable.
    """
    if backend not in BACKENDS:
        raise ProfileError('Unsupported preview backend')
    if backend == 'vaapi':
        render_device(render_node)
    encoder = BACKENDS[backend]
    with closing(connect_existing(root, writable=True)) as db:
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            schema = {row['name'] for row in db.execute('PRAGMA table_info(encode_profiles)')}
            if schema != set(COLUMNS):
                raise ProfileError('Unknown encode_profiles schema; no profiles were changed')
            if command_path is not None:
                config = db.execute('SELECT command_path FROM preview_encoder_config WHERE id = 1').fetchone()
                if not config or config[0] != command_path:
                    raise ProfileError('Runtime FFmpeg path changed since probing; repeat the probe')
            rows = [dict(row) for row in db.execute('SELECT * FROM encode_profiles ORDER BY id')]
            changes, skipped = [], []
            for name, purpose, bitrate, four_k in (('preview-h264', 'preview', 2000000, False),
                                                  ('preview-4k', 'preview4k', 4000000, True)):
                candidates = [row for row in rows if row['name'] == name]
                if len(candidates) != 1:
                    skipped.append({'name': name, 'reason': 'missing or duplicate seeded name'})
                    continue
                row = candidates[0]
                if (row['purpose'] != purpose or row['codec'] != 'h264'
                        or row['container'] != 'mpegts' or row['target_bitrate'] != bitrate
                        or row['is_enabled'] != 1 or not auto_generated(row['extra_args'], four_k)):
                    skipped.append({'name': name, 'reason': 'administrator-edited profile'})
                    continue
                desired = ffmpeg_args(encoder, four_k, render_node)
                if row['extra_args'] != desired:
                    changes.append({'id': row['id'], 'name': name, 'extra_args': desired})
            backup = backup_profiles(database_path(root), rows) if changes else None
            for change in changes:
                db.execute('UPDATE encode_profiles SET extra_args = ? WHERE id = ?',
                           (change['extra_args'], change['id']))
            db.commit()
            return {'backend': backend, 'encoder': encoder, 'updated': [row['name'] for row in changes],
                    'skipped': skipped, 'backup': backup,
                    'activation': 'new-preview-session',
                    'restart_command': 'docker compose restart recisdb-proxy' if changes else None}
        except BaseException:
            db.rollback()
            raise


def load_env(path):
    return dict(line.split('=', 1) for line in Path(path).read_text().splitlines()
                if '=' in line and not line.lstrip().startswith('#'))


def print_activation_notice(report, file=None):
    if report.get('updated'):
        print('recisdb-proxy: プロファイルは DB に反映済み。新規プレビューは再読込します。'
              '既存プレビューへの反映には停止・再接続、またはサービス再起動が必要です。'
              '録画・視聴への影響を確認してから実行: docker compose restart recisdb-proxy', file=file)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--env', type=Path)
    parser.add_argument('--docker-bin', default=os.environ.get('DOCKER_BIN', 'docker'))
    parser.add_argument('--backend', choices=BACKENDS)
    parser.add_argument('--render-node')
    parser.add_argument('--command-path')
    parser.add_argument('--read-config', action='store_true')
    args = parser.parse_args()
    try:
        if args.read_config:
            result = read_preview_config(args.root, args.env, args.docker_bin)
        else:
            if not args.backend:
                parser.error('--backend is required unless --read-config is used')
            result = apply_profiles(args.root, args.env, args.docker_bin, args.backend,
                                    args.render_node, args.command_path)
        print(json.dumps(result, ensure_ascii=False))
        if not args.read_config:
            print_activation_notice(result, file=sys.stderr)
    except (ProfileError, OSError, sqlite3.Error) as error:
        # SQLite/OSError can include paths, but never credentials/API bodies.
        print('[preview] ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
