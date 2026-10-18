#!/bin/sh
set -eu

# Bind mounts hide the release defaults. Copy only missing files, including EPGStation.profile.
app_root=${AMATSUKAZE_APP_ROOT:-/app}
defaults=${AMATSUKAZE_DEFAULTS:-/opt/amatsukaze-defaults}
python3 - "$defaults" "$app_root" <<'PYSEED'
import os
from pathlib import Path
import shutil
import sys

source, target = map(Path, sys.argv[1:])
for directory in ('avs', 'bat', 'config', 'data', 'drcs', 'JL', 'logo', 'profile', 'input', 'output'):
    (target / directory).mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(source / directory):
        destination = target / Path(root).relative_to(source)
        destination.mkdir(parents=True, exist_ok=True)
        for name in dirs + files:
            src, dst = Path(root) / name, destination / name
            if os.path.lexists(dst):
                continue
            if src.is_symlink():
                dst.symlink_to(os.readlink(src))
            elif src.is_dir():
                dst.mkdir()
            else:
                shutil.copy2(src, dst)
PYSEED
# Upstream config fixer, GPU groups and UID/GID handling run after seeding.
exec "$app_root/entrypoint.sh" "$@"
