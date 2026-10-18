#!/usr/bin/env python3
"""Create and regenerate host-side service configuration from templates.

first-run: creates a file only when it is missing. Existing files are never overwritten.
           Old locations are copied (not moved) to the new location when found.
regen:     replaces one service file on request. The current file is first copied to
           config/<service>/backup/<name>.<timestamp>, and the diff is shown before replacing.
           The file is rewritten in place so that existing bind mounts keep working.
"""
import argparse
import difflib
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import sys
import json

SERVICES = {
    'recisdb-proxy': {
        'template': 'templates/recisdb-proxy/recisdb-proxy.toml.example',
        'output': 'config/recisdb-proxy/recisdb-proxy.toml',
        'mode': 0o644,
        # The old entrypoint rendered into data/recisdb (the file the service actually read).
        'legacy': ['data/recisdb/recisdb-proxy.toml', 'config/recisdb-proxy.toml'],
    },
    'epgstation': {
        'template': 'templates/epgstation/config.yml.example',
        'output': 'config/epgstation/config.yml',
        # Contains the database password.
        'mode': 0o600,
        'legacy': ['config/config.yml'],
    },
    'konomitv': {
        'template': 'templates/konomitv/config.yaml.example',
        'output': 'config/konomitv/config.yaml',
        'mode': 0o644,
        'legacy': ['config/config.yaml'],
    },
}

AMATSUKAZE_ENCODE = """    - id: amatsukaze
      name: Amatsukaze
      cmd: '%NODE% %ROOT%/dist/AmatsukazeEncodeTool.js EPGStation'
      suffix: .mp4
      rate: 12.0"""
AMATSUKAZE_CONFIG = """amatsukaze:
    host: amatsukaze
    port: 32768
    addTaskPath: /opt/amatsukaze/AmatsukazeAddTask
    profile: EPGStation
    priority: 3
    noMove: true
    connectTimeoutMs: 60000
    taskTimeoutMs: 0
    pathMappings: []"""


def read_env(path):
    values = {}
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value
    return values


def amatsukaze_enabled(env):
    return 'compose.amatsukaze.yaml' in env.get('COMPOSE_FILE', '').split(':')


def fail(message):
    print(f'エラー: {message}', file=sys.stderr)
    sys.exit(1)


def render_recisdb(text, env):
    values = {key: env.get(key, '') for key in ('BONCAS_B25_HOST', 'BONCAS_B25_PORT', 'BONCAS_4K_HOST', 'BONCAS_4K_PORT')}
    if not values['BONCAS_B25_HOST'] or not values['BONCAS_B25_PORT']:
        fail('BONCAS_B25_HOST と BONCAS_B25_PORT が .env にありません。setup.sh を実行してください。')
    for key, value in values.items():
        if re.search(r'["\\\n\r]', value):
            fail(f'{key} に使えない文字が含まれています。')
    out = re.sub(r'\$\{(BONCAS_[A-Z0-9_]+)\}', lambda m: values[m.group(1)], text)
    if not values['BONCAS_4K_HOST']:
        # Without a 4K relay, drop the [mmttlv] table header and its boncaslink_server line.
        kept, in_section = [], False
        for line in out.split('\n'):
            if line == '[mmttlv]':
                in_section = True
                continue
            if in_section and line.startswith('['):
                in_section = False
            if in_section and re.match(r'boncaslink_server\s*=', line):
                continue
            kept.append(line)
        out = '\n'.join(kept)
    return out


def render_epgstation(text, env):
    password = env.get('MARIADB_PASSWORD', '')
    if not password:
        fail('MARIADB_PASSWORD が .env にありません。setup.sh を実行してください。')
    # JSON strings are valid YAML double-quoted scalars and keep quotes and backslashes intact.
    out = text.replace('${MARIADB_PASSWORD_YAML}', json.dumps(password))
    if amatsukaze_enabled(env):
        out = out.replace('${AMATSUKAZE_ENCODE}', AMATSUKAZE_ENCODE).replace('${AMATSUKAZE_CONFIG}', AMATSUKAZE_CONFIG)
    else:
        out = out.replace('${AMATSUKAZE_ENCODE}', '').replace('${AMATSUKAZE_CONFIG}', '')
    if re.search(r'\$\{[A-Z_]+\}', out):
        fail('EPGStation テンプレートに未置換の変数があります。')
    return out


def render(name, text, env):
    if name == 'recisdb-proxy':
        return render_recisdb(text, env)
    if name == 'epgstation':
        return render_epgstation(text, env)
    return text


def check_amatsukaze_section(name, path, env):
    if name != 'epgstation' or not amatsukaze_enabled(env):
        return
    text = path.read_text(encoding='utf-8')
    if not (re.search(r'^amatsukaze:', text, re.M) and 'id: amatsukaze' in text):
        print(f'注意: {path} に Amatsukaze の設定がありません。'
              '「make regen-config SERVICE=epgstation」を実行してください (差分を確認してから置き換えます)。')


def write_new(path, text, mode):
    with path.open('x', encoding='utf-8') as file:
        file.write(text)
    os.chmod(path, mode)


def first_run(root, env):
    for name, spec in SERVICES.items():
        out = root / spec['output']
        if out.exists():
            print(f'既存の設定を維持: {spec["output"]}')
            check_amatsukaze_section(name, out, env)
            continue
        legacy = next((root / p for p in spec['legacy'] if (root / p).is_file()), None)
        out.parent.mkdir(parents=True, exist_ok=True)
        if legacy is not None:
            shutil.copy2(legacy, out)
            os.chmod(out, spec['mode'])
            print(f'旧設定を移行: {legacy.relative_to(root)} -> {spec["output"]} (旧ファイルは残しています)')
        else:
            write_new(out, render(name, (root / spec['template']).read_text(encoding='utf-8'), env), spec['mode'])
            print(f'作成: {spec["output"]} (テンプレート {spec["template"]} から生成)')
        check_amatsukaze_section(name, out, env)


def regen(root, env, name, assume_yes):
    spec = SERVICES[name]
    out = root / spec['output']
    new = render(name, (root / spec['template']).read_text(encoding='utf-8'), env)
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        write_new(out, new, spec['mode'])
        print(f'作成: {spec["output"]}')
        return
    old = out.read_text(encoding='utf-8')
    diff = list(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                     fromfile=spec['output'], tofile=f'{spec["output"]} (再生成後)'))
    if not diff:
        print(f'変更はありません: {spec["output"]}')
        return
    sys.stdout.writelines(diff)
    if not assume_yes:
        if not sys.stdin.isatty():
            fail('対話できないため置き換えを中止しました。確認後に --yes を付けて再実行してください。')
        answer = input('差分を確認しました。現在のファイルを退避して置き換えますか? [y/N] ').strip().lower()
        if answer not in ('y', 'yes'):
            print('置き換えを中止しました。')
            return
    backup_dir = out.parent / 'backup'
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = backup_dir / f'{out.name}.{stamp}'
    counter = 1
    while backup.exists():
        backup = backup_dir / f'{out.name}.{stamp}-{counter}'
        counter += 1
    shutil.copy2(out, backup)
    # Rewrite in place: a bind-mounted file must keep its inode.
    with out.open('w', encoding='utf-8') as file:
        file.write(new)
    os.chmod(out, spec['mode'])
    print(f'退避: {backup.relative_to(root)}')
    print(f'置き換え: {spec["output"]}')
    print(f'反映には docker compose restart {name} を実行してください。')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--env', required=True, type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('first-run')
    regen_parser = sub.add_parser('regen')
    regen_parser.add_argument('--service', required=True, choices=sorted(SERVICES))
    regen_parser.add_argument('--yes', action='store_true', help='確認なしで置き換える')
    args = parser.parse_args()
    root = args.root.resolve()
    env = read_env(args.env)
    if args.command == 'first-run':
        first_run(root, env)
    else:
        regen(root, env, args.service, args.yes)


if __name__ == '__main__':
    main()
