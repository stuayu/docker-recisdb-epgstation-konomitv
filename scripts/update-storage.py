#!/usr/bin/env python3
"""Change storage selection only; retain existing service settings for review."""
from datetime import datetime
from pathlib import Path
import shutil
import sys
from storage import directories, mounts, warn_removed
from importlib.util import module_from_spec, spec_from_file_location

root, path = map(Path, sys.argv[1:3])
spec = spec_from_file_location('render', root / 'scripts/render-config.py')
render = module_from_spec(spec)
spec.loader.exec_module(render)
env = render.read_env(path)
previous = dict(env)
env['RECORDED_DIR'], env['RECORDED_DIRS_JSON'] = sys.argv[3:5]
warn_removed(root, previous, env)
compose = [p for p in env.get('COMPOSE_FILE', '').split(':') if p != 'compose.storage.yaml']
if len(directories(env)) > 1:
    compose.append('compose.storage.yaml')
env['COMPOSE_FILE'] = ':'.join(compose)
for directory in directories(env):
    (root / directory).mkdir(parents=True, exist_ok=True)
    if render.enabled('edcb', env):
        (root / directory / 'edcb').mkdir(exist_ok=True)
shutil.copy2(path, str(path) + '.bak.' + datetime.now().strftime('%Y%m%d%H%M%S%f'))
lines = path.read_text().splitlines()
keys = ('RECORDED_DIR', 'RECORDED_DIRS_JSON', 'COMPOSE_FILE')
lines = [line for line in lines if line.split('=', 1)[0] not in (*keys, 'EDCB_RECORDING_PATHS')]
path.write_text('\n'.join(lines + [k + '=' + env[k] for k in keys]) + '\n')
mounts(root, env)
print('録画先を更新しました。既存サービス設定は変更していません。')
print('make regen-config SERVICE=epgstation / konomitv / edcb で差分を確認し、make up でマウントを再作成してください。')
print('保存先の削除・順序変更前に既存録画 DB のパスを確認してください。')
