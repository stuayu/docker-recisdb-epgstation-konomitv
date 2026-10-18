"""Adapt EDCB Unix macros to the unmodified Rust registration tool."""
from datetime import datetime, timedelta, timezone
import os
import json
from pathlib import Path
import sys


def environment(source):
    result = dict(source)
    for original, target in [('FilePath', 'FILEPATH'), ('FileName', 'FILENAME'), ('Title', 'TITLE')]:
        result[target] = source[original]
    start = datetime.fromisoformat(source['StartTime']).astimezone(timezone(timedelta(hours=9)))
    end = start + timedelta(seconds=int(source['DurationSecond']))
    for prefix, moment in [('S', start), ('E', end)]:
        for suffix, fmt in [('DYYYY', '%Y'), ('DMM', '%m'), ('DDD', '%d'), ('THH', '%H'), ('TMM', '%M'), ('TSS', '%S')]:
            result[prefix + suffix] = moment.strftime(fmt)
    return result


def runtime_for_recording(runtime, filepath):
    # Startup writes the selected paths; no mount-layout knowledge lives here.
    manifest = runtime / 'routes.json'
    routes = json.loads(manifest.read_text()) if manifest.is_file() else {}
    for prefix, directory in routes.items():
        if filepath.startswith(prefix):
            return runtime / directory
    return runtime


if __name__ == '__main__':
    runtime = Path(os.environ.get('EDCB_UPLOAD_RUNTIME', '/var/local/edcb/upload'))
    if (runtime.parent / 'upload.disabled').exists():
        print('[edcb] 自動登録は無効です。', file=sys.stderr)
        sys.exit(0)
    if len(sys.argv) == 1:
        runtime = runtime_for_recording(runtime, os.environ['FilePath'])
    tool = runtime / 'edcb_to_epgstation_ts'
    if not tool.is_file():
        print('[edcb] 自動登録無効: make build / docker compose build edcb で再ビルドが必要。', file=sys.stderr)
        sys.exit(0)
    env = dict(os.environ) if len(sys.argv) > 1 else environment(os.environ)
    os.execve(str(tool), [str(tool), *sys.argv[1:]], env)
