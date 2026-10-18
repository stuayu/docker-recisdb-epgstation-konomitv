"""Prepare per-disk uploader executables and settings at container startup."""
import copy
import json
from pathlib import Path
import shutil
import yaml


def prepare(runtime, paths):
    routes = {}
    manifest = runtime / 'routes.json'
    manifest.write_text('{}\n')
    config = runtime / 'config.yml'
    if not config.is_file():
        print(f'[edcb] 自動登録設定なし: {config}; 設定後にコンテナを再起動してください。')
        return
    settings = yaml.safe_load(config.read_text())
    if settings['epgstationUpload']['parentDirectoryName'] != 'edcb':
        return
    for index, path in enumerate(paths[1:], 2):
        directory = runtime / Path(path).parent.name
        directory.mkdir(exist_ok=True)
        routes[path.rstrip('/') + '/'] = directory.name
        shutil.copy2(runtime / 'edcb_to_epgstation_ts', directory / 'edcb_to_epgstation_ts')
        current = copy.deepcopy(settings)
        current['epgstationUpload']['parentDirectoryName'] = f'edcb{index}'
        (directory / 'config.yml').write_text(yaml.safe_dump(current, allow_unicode=True))

    manifest.write_text(json.dumps(routes) + '\n')
