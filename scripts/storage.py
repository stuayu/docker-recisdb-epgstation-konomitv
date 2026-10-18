#!/usr/bin/env python3
"""Discover mounted recording storage and render additional shared mounts."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def run(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return ''


def candidates():
    rows = []
    try:
        def walk(items):
            for item in items:
                yield item
                yield from walk(item.get('children', []))
        for item in walk(json.loads(run('findmnt', '--json', '--bytes', '-o', 'TARGET,FSTYPE,AVAIL')).get('filesystems', [])):
            rows.append((item.get('target'), item.get('fstype'), item.get('avail')))
    except (ValueError, AttributeError):
        pass
    if not rows:
        try:
            def blocks(items):
                for item in items:
                    for mount in item.get('mountpoints', [item.get('mountpoint')]) or []:
                        if mount:
                            yield mount, item.get('fstype'), item.get('fsavail')
                    yield from blocks(item.get('children', []))
            rows.extend(blocks(json.loads(run('lsblk', '--json', '--bytes', '-o', 'MOUNTPOINTS,FSTYPE,FSAVAIL')).get('blockdevices', [])))
        except (ValueError, AttributeError):
            pass
    if not rows:
        for line in run('df', '-PTk').splitlines()[1:]:
            parts = line.split(None, 6)
            if len(parts) == 7:
                rows.append((parts[6], parts[1], int(parts[4]) * 1024))
    seen = set()
    for mount, kind, available in rows:
        if not mount or mount in seen or kind in ('tmpfs', 'devtmpfs', 'overlay', 'squashfs', 'proc', 'sysfs', 'devfs'):
            continue
        if mount == '/' or re.match(r'^/(boot|snap|proc|sys|dev|run|var/lib/(docker|containerd))(/|$)', mount):
            continue
        seen.add(mount)
        try:
            free = f'{int(available) / 1e9:.1f} GB'
        except (TypeError, ValueError):
            free = '空き不明'
        yield mount, f'{kind or "不明"} / {free}'


def directories(env):
    primary = env.get('RECORDED_DIR', './data/recorded')
    extra = json.loads(env.get('RECORDED_DIRS_JSON', '[]') or '[]')
    if not isinstance(extra, list) or any(not isinstance(p, str) for p in extra):
        raise ValueError('RECORDED_DIRS_JSON must be a JSON array of paths')
    result = list(dict.fromkeys([primary] + extra))
    for path in result:
        if not path or any(c in path for c in '\n\r\x00$'):
            raise ValueError('録画先に改行・NUL・$ は使用できません')
    return result


def targets(env):
    return ['/recorded' if i == 0 else f'/recorded{i + 1}' for i, _ in enumerate(directories(env))]


def mounts(root, env):
    paths = directories(env)
    services = {}
    for name in ('epgstation', 'konomitv', 'edcb', 'amatsukaze'):
        if name in ('edcb', 'amatsukaze') and f'compose.{name}.yaml' not in env.get('COMPOSE_FILE', '').split(':'):
            continue
        volumes = []
        for source, target in zip(paths[1:], targets(env)[1:]):
            volumes.append({'type': 'bind', 'source': str((root / source).resolve()),
                            'target': '/host-rootfs' + target if name == 'konomitv' else target,
                            'read_only': name == 'konomitv'})
        if volumes:
            services[name] = {'volumes': volumes}
    # JSON is also YAML. A stable generated file is backed up with the settings.
    output = root / 'compose.storage.yaml'
    output.write_text(json.dumps({'services': services}, indent=2) + '\n')


def warn_removed(root, previous, current):
    old = dict(zip(directories(previous), targets(previous)))
    new = dict(zip(directories(current), targets(current)))
    for source, target in old.items():
        if new.get(source) == target:
            continue
        print(f'注意: 録画先の削除・対応変更: {source} ({target})。既存録画 DB のパスも確認してください。')
        for service in ('epgstation', 'konomitv', 'edcb'):
            for path in (root / 'config' / service).rglob('*'):
                if path.is_file() and 'backup' not in path.parts:
                    if re.search(re.escape(target) + r'(?![0-9])', path.read_text(errors='replace')):
                        print(f'警告: {path} が {target} を参照しています。設定の更新が必要です。')


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ('mounts', 'warn-removed'):
        import importlib.util
        spec = importlib.util.spec_from_file_location('render', Path(__file__).with_name('render-config.py'))
        render = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(render)
        root, path = map(Path, sys.argv[2:4])
        env = render.read_env(path)
        if sys.argv[1] == 'mounts':
            mounts(root, env)
        else:
            warn_removed(root, env, dict(env, RECORDED_DIR=sys.argv[4], RECORDED_DIRS_JSON=sys.argv[5]))
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument('command', choices=['candidates'])
        parser.parse_args()
        for path, description in candidates():
            print(path + '\t' + description)
