"""Preserve legacy editable settings before seeding defaults."""
from datetime import datetime
from pathlib import Path
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


def migrate_amatsukaze(old, config):
    for name in AMATSUKAZE_DIRS:
        for src in (old / name).rglob('*'):
            dst = config / name / src.relative_to(old / name)
            if src.is_file() and not dst.exists() and not dst.is_symlink():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
