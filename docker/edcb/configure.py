"""Seed missing EDCB settings. Existing files always win."""
import os
from pathlib import Path
import shutil

root = Path(os.environ.get('EDCB_ROOT', '/var/local/edcb'))
defaults = Path(os.environ.get('EDCB_DEFAULTS', '/opt/edcb-defaults'))
recorded = Path(os.environ.get('EDCB_RECORDED', '/recorded/edcb'))
count = int(os.environ.get('EDCB_TUNER_COUNT', '2'))
if not 1 <= count <= 99:
    raise SystemExit('EDCB_TUNER_COUNT must be 1..99')
root.mkdir(parents=True, exist_ok=True)
recorded.mkdir(parents=True, exist_ok=True)
for src in defaults.rglob('*'):
    dst = root / src.relative_to(defaults)
    if src.is_dir():
        dst.mkdir(exist_ok=True)
    elif not dst.exists():
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
        with (root / name).open('x', encoding='utf-8') as f:
            f.write(body)
    except FileExistsError:
        pass

seed('Common.ini', f'''[SET]
DataSavePath={root}/Setting
RecFolderNum=1
RecFolderPath0={recorded}
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
''')
seed('EpgDataCap_Bon.ini', '''[SET]
Scramble=0
EMM=0
''')
# This INI belongs alongside the .so: upstream uses dladdr(), not Common.ini.
lib = Path(os.environ.get('EDCB_LIB', '/usr/local/lib/edcb'))
lib.mkdir(parents=True, exist_ok=True)
ini = root / 'BonDriver_LinuxMirakc.so.ini'
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
