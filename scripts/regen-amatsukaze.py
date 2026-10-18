#!/usr/bin/env python3
"""Review image defaults and restore selected editable Amatsukaze files."""
from datetime import datetime
import difflib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
directories = ('avs', 'bat', 'config', 'drcs', 'JL', 'logo', 'profile')
with tempfile.TemporaryDirectory() as temp:
    destination = Path(temp)
    # No service entrypoint, USB access or published ports. Export packaged defaults only.
    command = [os.environ.get('DOCKER_BIN', 'docker'), 'compose', 'run', '--rm', '--no-deps', '-T',
               '--entrypoint', 'tar', 'amatsukaze', '-C', '/opt/amatsukaze-defaults', '-cf', '-', *directories]
    archive = destination / 'defaults.tar'
    with archive.open('wb') as stream:
        subprocess.run(command, cwd=root, stdout=stream, check=True)
    import tarfile
    with tarfile.open(archive) as source:
        # Python 3.10/early 3.11 lack extraction filters. Export regular files
        # explicitly; never follow archive links or accept a path traversal.
        for member in source.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0] not in directories:
                raise SystemExit(f'不正な既定値アーカイブのパス: {member.name}')
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as data, target.open('wb') as stream:
                    shutil.copyfileobj(data, stream)
                target.chmod(member.mode & 0o777)

    output = root / 'config/amatsukaze'
    changed = []
    for name in directories:
        for src in (destination / name).rglob('*'):
            if not src.is_file() or src.is_symlink():
                continue
            relative = src.relative_to(destination)
            dst = output / relative
            if dst.is_file() and dst.read_bytes() == src.read_bytes():
                continue
            print(f'再生成対象: {relative}')
            if dst.is_file():
                try:
                    sys.stdout.writelines(difflib.unified_diff(dst.read_text().splitlines(True), src.read_text().splitlines(True), fromfile=str(dst), tofile=str(relative)))
                except UnicodeError:
                    print('バイナリーファイルを置き換えます。')
            changed.append((src, dst))
    # These files are created by EncodeServer.LoadAppData/LoadUIState and
    # LoadAutoSelectData, and may be absent from a release archive. Removing
    # them after backup requests the application's own defaults on next start.
    for filename in ('AmatsukazeServer.xml', 'UIState.xml', 'AutoSelectProfile.xml'):
        relative = Path('config') / filename
        dst = output / relative
        if dst.is_file() and not (destination / relative).exists():
            print(f'再生成対象 (次回起動で既定値を生成): {relative}')
            sys.stdout.writelines(difflib.unified_diff(dst.read_text().splitlines(True), [], fromfile=str(dst), tofile='次回起動時の既定値'))
            changed.append((None, dst))
    if not changed:
        print('変更はありません。')
        sys.exit(0)
    if not sys.stdin.isatty() or input('Amatsukaze の停止を確認しました。現在の設定を退避し、表示したファイルを既定値に戻しますか？ [y/N] ').lower() not in ('y', 'yes'):
        sys.exit('再生成を中止しました。')
    backup = output / 'backup' / datetime.now().strftime('%Y%m%d-%H%M%S%f')
    for src, dst in changed:
        if dst.exists():
            saved = backup / dst.relative_to(output)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, saved)
        if src is None:
            dst.unlink()
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Existing bind mounts keep their inode.
        with dst.open('wb') as stream:
            stream.write(src.read_bytes())
        dst.chmod(src.stat().st_mode & 0o777)
    print(f'退避: {backup}。docker compose restart amatsukaze で反映してください。')
