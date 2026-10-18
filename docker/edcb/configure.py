"""Seed missing EDCB settings. Existing files always win."""
import os
import json
from pathlib import Path
import shutil

root = Path(os.environ.get('EDCB_ROOT', '/var/local/edcb'))
defaults = Path(os.environ.get('EDCB_DEFAULTS', '/opt/edcb-defaults'))
recorded = Path(os.environ.get('EDCB_RECORDED', '/recorded/edcb'))
config = Path(os.environ.get('EDCB_CONFIG_DIR', str(root)))
config.mkdir(parents=True, exist_ok=True)
count = int(os.environ.get('EDCB_TUNER_COUNT', '2'))
if not 1 <= count <= 99:
    raise SystemExit('EDCB_TUNER_COUNT must be 1..99')
root.mkdir(parents=True, exist_ok=True)
recorded.mkdir(parents=True, exist_ok=True)
for src in defaults.rglob('*'):
    relative = src.relative_to(defaults)
    editable = src.suffix.lower() == '.ini' or src.name.endswith('.ChSet4.txt') or src.name == 'ChSet5.txt'
    dst = (config if editable else root) / relative
    if src.is_dir():
        dst.mkdir(exist_ok=True)
    elif not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
# WebUI code is not user configuration: refresh it from the image on every start.
# Settings under Setting/ are seeded above and never overwritten.
web_defaults = defaults / 'HttpPublic'
for src in web_defaults.rglob('*') if web_defaults.is_dir() else []:
    dst = root / 'HttpPublic' / src.relative_to(web_defaults)
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
(root / 'Setting').mkdir(exist_ok=True)

def seed(name, body):
    try:
        with (config / name).open('x', encoding='utf-8') as f:
            f.write(body)
    except FileExistsError:
        pass

recording_paths = json.loads(os.environ.get('EDCB_RECORDING_PATHS', json.dumps([str(recorded)])))
folders = f'RecFolderNum={len(recording_paths)}\n' + '\n'.join(f'RecFolderPath{i}={p}' for i, p in enumerate(recording_paths))
seed('Common.ini', f'''[SET]
DataSavePath={root}/Setting
{folders}
''')
seed('EpgTimerSrv.ini', f'''[SET]
EnableHttpSrv=1
HttpPort=5510
HttpPublicFolder={root}/HttpPublic
HttpAccessControlList=+127.0.0.1,+10.0.0.0/8,+172.16.0.0/12,+192.168.0.0/16
# Material WebUI (E3) keeps one Civetweb thread per SSE view; the default 5 stalls tabs.
HttpNumThreads=50
EnableTCPSrv=0
RecEndMode=0
[BonDriver_LinuxMirakc.so]
Count={count}
Priority=1
GetEpg=1
EPGCount=1
[EPG_CAP]
Count=2
0=06:00
0Select=1
1=18:00
1Select=1
[TVTEST]
Num=1
0=BonDriver_LinuxMirakc.so
[REC_DEF]
RecMode=3
{'BatFilePath=/opt/edcb-stack/post-record.sh' if os.environ.get('EDCB_EPGSTATION_ENABLED') == '1' else ''}
''')
seed('EpgDataCap_Bon.ini', '''[SET]
Scramble=0
EMM=0
''')
# This INI belongs alongside the .so: upstream uses dladdr(), not Common.ini.
lib = Path(os.environ.get('EDCB_LIB', '/usr/local/lib/edcb'))
lib.mkdir(parents=True, exist_ok=True)
ini = config / 'BonDriver_LinuxMirakc.so.ini'
seed(ini.name, '''[GLOBAL]
SERVER_HOST="recisdb-proxy"
SERVER_PORT=40080
SERVER_TYPE="http"
DECODE_B25=0
PRIORITY=2
SERVICE_SPLIT=1
''')
link = lib / ini.name
if not link.exists() and not link.is_symlink():
    link.symlink_to(ini)

# EDCB writes INIs in place (Common/PathUtil.cpp); symlinks keep editable settings
# in config/ while Reserve/RecInfo/EpgAutoAdd and EpgData stay in data/Setting.
if config != root:
    for src in config.rglob('*'):
        if not src.is_file() or 'backup' in src.relative_to(config).parts:
            continue
        dst = root / src.relative_to(config)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink():
            continue
        if dst.exists():
            # Retain the old data-side copy once. Never destroy an old configuration.
            legacy = dst.with_name(dst.name + '.pre-config-migration')
            if legacy.exists():
                raise SystemExit(f'旧設定退避先が既に存在します: {legacy}')
            dst.rename(legacy)
        dst.symlink_to(src)

if os.environ.get('EDCB_EPGSTATION_ENABLED') == '1':
    runtime = root / 'upload'
    runtime.mkdir(exist_ok=True)
    binary = Path(os.environ.get('EDCB_UPLOAD_BINARY', '/opt/edcb-upload/edcb_to_epgstation_ts'))
    shutil.copy2(binary, runtime / binary.name)
    link = runtime / 'config.yml'
    if not link.exists() and not link.is_symlink():
        link.symlink_to('/config/edcb-to-epgstation/config.yml')
