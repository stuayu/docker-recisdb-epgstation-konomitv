"""Preserve legacy editable settings before seeding defaults."""
from datetime import datetime
from pathlib import Path
import re
import shutil

AMATSUKAZE_DIRS = ('avs', 'bat', 'config', 'drcs', 'JL', 'logo', 'profile')


def edcb_editable(path):
    return path.suffix.lower() == '.ini' or path.name.endswith('.ChSet4.txt') or path.name == 'ChSet5.txt'


def backup(path):
    destination = path.with_name(path.name + '.pre-config-migration')
    while destination.exists() or destination.is_symlink():
        destination = path.with_name(path.name + '.pre-config-migration.' + datetime.now().strftime('%Y%m%d%H%M%S%f'))
    shutil.copy2(path, destination)
    return destination


def migrate_edcb(old, config):
    if old == config:
        return
    for src in old.rglob('*'):
        if not src.is_file() or src.is_symlink() or not edcb_editable(src):
            continue
        relative = src.relative_to(old)
        if 'backup' in relative.parts or 'upload' in relative.parts:
            continue
        dst = config / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and src.read_bytes() == dst.read_bytes():
            continue
        if dst.exists():
            saved = backup(dst)
            print(f'[edcb] data 側の実体を優先: {src}; config 側を退避: {saved}', flush=True)
        shutil.copy2(src, dst)
        print(f'[edcb] 設定を移行: {src} -> {dst}', flush=True)


def migrate_edcb_access_defaults(config):
    old_acl = '+127.0.0.1,+10.0.0.0/8,+172.16.0.0/12,+192.168.0.0/16'
    new_acl = old_acl + ',+100.64.0.0/10'
    timer = config / 'EpgTimerSrv.ini'
    if timer.is_file():
        text = timer.read_bytes()
        pattern = re.compile(rb'(?m)^(HttpAccessControlList=)([^\r\n]*)$')
        match = pattern.search(text)
        if match and match.group(2) == old_acl.encode():
            saved = backup(timer)
            timer.write_bytes(text[:match.start(2)] + new_acl.encode() + text[match.end(2):])
            print(f'[edcb] HttpAccessControlList の既定値を移行: {timer}; 退避: {saved}', flush=True)
        elif match and b'+100.64.0.0/10' not in match.group(2):
            print('[edcb] EpgTimerSrv.ini は変更済みです。Tailscale から使う場合は '
                  '+100.64.0.0/10 を HttpAccessControlList に追加してください。', flush=True)

    public = config / 'Setting/HttpPublic.ini'
    if public.is_file():
        text = public.read_bytes()
        pattern = re.compile(rb'(?m)^(ALLOW_SETTING_LIST=)([^\r\n]*)$')
        match = pattern.search(text)
        if match and match.group(2) == b'127.0.0.1,::1':
            saved = backup(public)
            public.write_bytes(text[:match.start(2)] + text[match.end(2):])
            print(f'[edcb] HttpPublic.ini の接続元既定値を移行: {public}; 退避: {saved}', flush=True)
        elif match and match.group(2):
            print('[edcb] HttpPublic.ini の ALLOW_SETTING_LIST は接続元 IP の完全一致です。'
                  '許可する接続元を列挙するか、空欄にすると EDCB の HttpAccessControlList が接続を制限します。', flush=True)


def migrate_amatsukaze(old, config):
    for name in AMATSUKAZE_DIRS:
        for src in (old / name).rglob('*'):
            dst = config / name / src.relative_to(old / name)
            if src.is_file() and not dst.exists() and not dst.is_symlink():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
