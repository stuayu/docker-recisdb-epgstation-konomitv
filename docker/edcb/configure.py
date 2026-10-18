"""Seed missing EDCB settings. Existing files always win."""
import os
from pathlib import Path
import shutil
import sys
stack_root = Path(os.environ.get("EDCB_STACK_ROOT", str(Path(__file__).resolve().parents[2])))
sys.path.insert(0, str(stack_root / "scripts"))
from editable import migrate_edcb, edcb_editable, backup
from storage import targets
from importlib.util import module_from_spec, spec_from_file_location
spec = spec_from_file_location("render", stack_root / "scripts/render-config.py")
render = module_from_spec(spec)
spec.loader.exec_module(render)

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
migrate_edcb(root, config)

upload_enabled = os.environ.get('EDCB_EPGSTATION_ENABLED') == '1'
binary = Path(os.environ.get('EDCB_UPLOAD_BINARY', '/opt/edcb-upload/edcb_to_epgstation_ts'))
if upload_enabled and not binary.is_file():
    print('[edcb] 自動登録バイナリなし。make build / docker compose build edcb で再ビルドが必要。自動登録を無効化して起動を続行。', file=sys.stderr)
    upload_enabled = False

# Stack INIs come from the same templates as host provisioning.
template_root = Path(os.environ.get('EDCB_TEMPLATES', str(stack_root / 'templates/edcb')))
stack_names = {p.name.removesuffix('.example') for p in template_root.glob('*.example')}
for src in defaults.rglob('*'):
    relative = src.relative_to(defaults)
    editable = edcb_editable(src)
    if relative.as_posix() in stack_names:
        continue
    dst = (config if editable else root) / relative
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
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

recording_paths = [p + '/edcb' for p in targets(os.environ)]
if 'EDCB_RECORDED' in os.environ and 'RECORDED_DIRS_JSON' not in os.environ:
    recording_paths = [str(recorded)]
values = dict(os.environ, COMPOSE_FILE='compose.edcb.yaml', EDCB_EPGSTATION_ENABLED='1' if upload_enabled else '0')
for template in template_root.glob('*.example'):
    destination = config / template.name.removesuffix('.example')
    if not destination.exists():
        body = render.render('edcb', template.read_text(), values)
        body = body.replace('/var/local/edcb', str(root))
        # EDCB_RECORDED is a test/custom single-volume override.
        if 'EDCB_RECORDED' in os.environ and 'RECORDED_DIRS_JSON' not in os.environ:
            body = body.replace('/recorded/edcb', str(recorded))
        destination.write_text(body)
lib = Path(os.environ.get('EDCB_LIB', '/usr/local/lib/edcb'))
lib.mkdir(parents=True, exist_ok=True)
ini = config / 'BonDriver_LinuxMirakc.so.ini'
link = lib / ini.name
if not link.exists() and not link.is_symlink():
    link.symlink_to(ini)

# EDCB writes INIs in place (Common/PathUtil.cpp); symlinks keep editable settings
# in config/ while Reserve/RecInfo/EpgAutoAdd and EpgData stay in data/Setting.
if config != root:
    for src in config.rglob('*'):
        if not src.is_file() or not edcb_editable(src) or 'backup' in src.relative_to(config).parts:
            continue
        dst = root / src.relative_to(config)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink():
            continue
        if dst.exists():
            # Retain the old data-side copy once. Never destroy an old configuration.
            backup(dst)
            dst.unlink()
        dst.symlink_to(src)

disabled = root / 'upload.disabled'
if upload_enabled:
    disabled.unlink(missing_ok=True)
else:
    disabled.touch()

if upload_enabled and os.environ.get('EDCB_PREPARE_UPLOAD', '1') == '1':
    runtime = root / 'upload'
    runtime.mkdir(exist_ok=True)
    shutil.copy2(binary, runtime / binary.name)
    link = runtime / 'config.yml'
    if not link.exists() and not link.is_symlink():
        link.symlink_to(os.environ.get('EDCB_UPLOAD_CONFIG', '/config/edcb-to-epgstation/config.yml'))

    # Prepare every recording-disk runtime once at startup.
    from upload_runtime import prepare
    prepare(runtime, recording_paths)
