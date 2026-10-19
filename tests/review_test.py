"""Regression coverage for the ten upgrade/storage/relay review findings."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import socket
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from storage import targets, warn_removed


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


render = module('render', ROOT / 'scripts/render-config.py')
relay = module('relay', ROOT / 'docker/boncasrelay/runtime.py')
post = module('post', ROOT / 'docker/edcb/post-record.py')


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


with tempfile.TemporaryDirectory() as temp:
    base = Path(temp)
    # 1, 3, 9: direct startup and host first-run preserve exactly the same bytes.
    for mode in ('direct', 'host'):
        repo = base / mode
        shutil.copytree(ROOT / 'templates', repo / 'templates')
        data, config = repo / 'data/edcb', repo / 'config/edcb'
        (data / 'Setting').mkdir(parents=True)
        original = {'Common.ini': b'[SET]\nuser=true\n', 'EpgTimerSrv.ini': b'custom timer',
                    'BonDriver_LinuxMirakc.so.ini': b'custom driver',
                    'Setting/user.ChSet4.txt': b'custom ch4', 'Setting/ChSet5.txt': b'custom ch5'}
        for name, body in original.items():
            (data / name).write_bytes(body)
        defaults = repo / 'defaults'
        (defaults / 'Setting').mkdir(parents=True)
        for name in original:
            (defaults / name).write_bytes(b'IMAGE DEFAULT')
        env = dict(os.environ, EDCB_ROOT=str(data), EDCB_CONFIG_DIR=str(config),
                   EDCB_DEFAULTS=str(defaults), EDCB_LIB=str(repo / 'lib'),
                   EDCB_RECORDED=str(repo / 'recorded'), EDCB_EPGSTATION_ENABLED='0')
        settings = dict(COMPOSE_FILE='compose.edcb.yaml', MARIADB_PASSWORD='test',
                        BONCAS_B25_HOST='relay', BONCAS_B25_PORT='6900')
        if mode == 'host':
            render.first_run(repo, settings)
        run('python3', str(ROOT / 'docker/edcb/configure.py'), env=env)
        for name, body in original.items():
            assert (config / name).read_bytes() == body
            assert (data / name).is_symlink()
        # Atomic rename by EDCB replaces a symlink, with an existing backup.
        for edit in ('new edit 1', 'new edit 2'):
            (data / 'Common.ini').unlink()
            (data / 'Common.ini').write_text(edit)
            log = run('python3', str(ROOT / 'docker/edcb/configure.py'), env=env)
            assert 'data 側の実体を優先' in log.stdout
            assert (config / 'Common.ini').read_text() == edit
            assert (data / 'Common.ini').is_symlink()
        assert len(list((data).glob('Common.ini.pre-config-migration*'))) == 3
        assert original['Common.ini'] in [p.read_bytes() for p in config.glob('Common.ini.pre-config-migration*')]
        # 4: enabling without a rebuilt image never fails or seeds the hook.
        (config / 'EpgTimerSrv.ini').unlink()
        log = run('python3', str(ROOT / 'docker/edcb/configure.py'), env=dict(env,
                  EDCB_EPGSTATION_ENABLED='1', EDCB_UPLOAD_BINARY=str(repo / 'missing')))
        assert 'make build / docker compose build edcb' in log.stderr
        assert 'BatFilePath=' not in (config / 'EpgTimerSrv.ini').read_text()
        assert (data / 'upload.disabled').is_file()
        # A stale persisted executable must not bypass the disabled state.
        stale = data / 'upload'; stale.mkdir(exist_ok=True)
        (stale / 'edcb_to_epgstation_ts').write_text('must not run')
        skipped = run('python3', str(ROOT / 'docker/edcb/post-record.py'),
                      env=dict(os.environ, EDCB_UPLOAD_RUNTIME=str(stale)))
        assert '自動登録は無効' in skipped.stderr
    print('PASS: review 1/3/4: host/direct migration parity, repeated atomic replacements, backups, missing uploader')

    # 2: container fallback imports all editable directories before default seeding.
    app, legacy, defaults = (base / name for name in ('app', 'legacy', 'ama-defaults'))
    app.mkdir()
    entry = app / 'entrypoint.sh'; entry.write_text('#!/bin/sh\nexec "$@"\n'); entry.chmod(0o755)
    for name in ('avs', 'bat', 'config', 'drcs', 'JL', 'logo', 'profile'):
        (legacy / name).mkdir(parents=True)
        (legacy / name / 'asset').write_text('user ' + name)
        (defaults / name).mkdir(parents=True)
        (defaults / name / 'asset').write_text('default')
    env = dict(os.environ, STACK_SCRIPTS=str(ROOT / 'scripts'), AMATSUKAZE_APP_ROOT=str(app),
               AMATSUKAZE_DEFAULTS=str(defaults), AMATSUKAZE_LEGACY=str(legacy))
    run('sh', str(ROOT / 'docker/amatsukaze/entrypoint.sh'), 'true', env=env)
    assert (app / 'logo/asset').read_text() == 'user logo'
    (app / 'logo/asset').write_text('edited config')
    run('sh', str(ROOT / 'docker/amatsukaze/entrypoint.sh'), 'true', env=env)
    assert (app / 'logo/asset').read_text() == 'edited config'
    assert (legacy / 'logo/asset').read_text() == 'user logo'
    # Execute the actual make recipe with all external commands stubbed.
    repo = base / 'update'; shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))
    (repo / '.env').write_text('COMPOSE_FILE=compose.edcb.yaml:compose.amatsukaze.yaml\nMARIADB_PASSWORD=test\nBONCAS_B25_HOST=relay\nBONCAS_B25_PORT=6900\n')
    (repo / 'data/edcb').mkdir(parents=True)
    (repo / 'data/edcb/Common.ini').write_text('update user')
    (repo / 'data/amatsukaze/logo').mkdir(parents=True)
    (repo / 'data/amatsukaze/logo/user').write_text('user logo')
    binaries = base / 'bin'; binaries.mkdir()
    for name in ('git', 'docker'):
        stub = binaries / name; stub.write_text('#!/bin/sh\nexit 0\n'); stub.chmod(0o755)
    run('make', 'update', cwd=repo, env=dict(os.environ, PATH=str(binaries) + ':' + os.environ['PATH']))
    assert (repo / 'config/edcb/Common.ini').read_text() == 'update user'
    assert (repo / 'config/amatsukaze/logo/user').read_text() == 'user logo'
    print('PASS: review 2: make update migration and Amatsukaze startup fallback/nonoverwrite')

    # 5: restore retains local env and generates local mounts, saving archived mounts separately.
    archive_dir = base / 'archive'; (archive_dir / 'db').mkdir(parents=True)
    (archive_dir / 'db/epgstation.sql').write_text('-- dump')
    (archive_dir / '.env').write_text('RECORDED_DIR=/archived\n')
    (archive_dir / 'compose.storage.yaml').write_text('{"services":{"wrong":{}}}')
    archive = base / 'restore.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for item in archive_dir.iterdir():
            tar.add(item, arcname=item.name)
    local = dict(COMPOSE_FILE='compose.yaml:compose.edcb.yaml:compose.storage.yaml', RECORDED_DIR='/local',
                 RECORDED_DIRS_JSON='["/local", "/extra"]')
    (repo / '.env').write_text(''.join(k + '=' + v + '\n' for k, v in local.items()))
    run('bash', str(repo / 'scripts/restore.sh'), str(archive), env=dict(os.environ, YES='1', DOCKER_BIN=str(binaries / 'docker')))
    volumes = json.loads((repo / 'compose.storage.yaml').read_text())['services']
    assert volumes['edcb']['volumes'][0]['source'] == '/extra'
    assert 'wrong' not in volumes and (repo / 'compose.storage.yaml.from-archive').exists()
    assert (repo / '.env').read_text().startswith('COMPOSE_FILE=compose.yaml:compose.edcb.yaml:compose.storage.yaml')
    print('PASS: review 5: restore regenerates mounts from retained env')

    # 6: both primary overrides and line-based input retain additional storage.
    for override, reply in ((True, ''), (False, str(base / 'changed') + '\n')):
        primary, extra = base / 'primary', base / 'extra'
        primary.mkdir(exist_ok=True); extra.mkdir(exist_ok=True)
        (base / 'changed').mkdir(exist_ok=True)
        (repo / '.env').write_text('RECORDED_DIR=' + str(primary) + '\nRECORDED_DIRS_JSON=' + json.dumps([str(primary), str(extra)]) + '\n')
        script = '''source "$ROOT/scripts/setup-ui.sh"
get(){ sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; }
ask(){ if [[ $OVERRIDE == 1 ]]; then REPLY=$2; else read -r REPLY; fi; }
confirm(){ return 0; }
fail(){ exit 1; }
YES=1; NONINTERACTIVE=1; AUTO_INSTALL=0
select_storage
printf 'RESULT=%s\\n' "$storage_json"
'''
        values = dict(os.environ, ROOT=str(repo), ENV_FILE=str(repo / '.env'), OVERRIDE='1' if override else '0')
        values.pop('RECORDED_DIRS_JSON', None); values.pop('RECORDED_DIR', None)
        if override:
            values['RECORDED_DIR'] = str(base / 'changed')
        output = run('bash', '-c', script, env=values, input=reply).stdout
        selection = json.loads(output.split('RESULT=')[1])
        assert selection == [str(base / 'changed'), str(extra)], selection
    for service in ('edcb', 'epgstation', 'konomitv'):
        path = repo / 'config' / service / 'test.conf'; path.parent.mkdir(exist_ok=True)
        path.write_text('/recorded2/edcb')
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        warn_removed(repo, dict(RECORDED_DIR='a', RECORDED_DIRS_JSON='["a", "b"]'), dict(RECORDED_DIR='a'))
    assert all(service in log.getvalue() for service in ('edcb', 'epgstation', 'konomitv'))
    print('PASS: review 6: primary overrides/input retain extra disks; removed-path reference warnings')

    # 7: sysfs interfaces represent composite CCID readers and unrelated devices.
    sysfs = base / 'sysfs'; sysfs.mkdir()
    def usb(name, kind, number):
        device = sysfs / name; interface = device / (name + ':1.0'); interface.mkdir(parents=True)
        (device / 'busnum').write_text('1'); (device / 'devnum').write_text(str(number))
        (interface / 'bInterfaceClass').write_text(kind)
        (sysfs / (name + ':1.0')).symlink_to(interface)
    usb('1-1', '0b', 2)
    before = relay.readers(sysfs)
    usb('1-2', 'ff', 3)
    assert before == relay.readers(sysfs) == ['001/002']
    (sysfs / '1-2/devnum').write_text('4')
    assert before == relay.readers(sysfs)
    (sysfs / '1-1/devnum').write_text('5')
    assert relay.readers(sysfs) == ['001/005']
    shutil.rmtree(sysfs / '1-1')
    assert relay.readers(sysfs) == []
    # Missing USB nodes must not prevent either supervised service from starting.
    for name in ('pcscd', 'boncasrelay'):
        stub = binaries / name
        stub.write_text('#!/bin/sh\necho "' + name + '" >> "$START_LOG"\nsleep 1\n'); stub.chmod(0o755)
    stub = binaries / 'python3'
    stub.write_text('#!/bin/sh\nexit 0\n'); stub.chmod(0o755)
    logpath = base / 'started'
    sock = socket.socket(socket.AF_UNIX)
    socket_path = base / 'pcsc.sock'; sock.bind(str(socket_path))
    # The production bootstrap installs into /opt; isolate both paths on macOS.
    runtime_dir = base / 'relay-runtime'
    runtime_dir.mkdir()
    entrypoint = base / 'relay-entrypoint.sh'
    entrypoint.write_text((ROOT / 'docker/boncasrelay/entrypoint.sh').read_text()
                          .replace('/usr/local/libexec/boncasrelay/boncasrelay', str(binaries / 'boncasrelay'))
                          .replace('/opt/boncasrelay/boncasrelay', str(runtime_dir / 'boncasrelay')))
    process = subprocess.run(['bash', str(entrypoint)], env=dict(os.environ,
               PATH=str(binaries) + ':' + os.environ['PATH'], USB_DEV_ROOT=str(base / 'no-usb'),
               PCSC_SOCKET=str(socket_path), START_LOG=str(logpath)), capture_output=True, text=True, timeout=10)
    sock.close()
    assert '/dev/bus/usb がありません' in process.stderr
    assert 'boncasrelay' in logpath.read_text()
    (binaries / 'python3').unlink()
    print('PASS: review 7: CCID add/remove/reenumeration, unrelated USB unchanged, absent USB service startup')

    # 8: dynamic ACL follows connected subnet; no route or default route grants access.
    routes = [{'dst': '10.55.0.0/16', 'scope': 'link', 'dev': 'eth0'},
              {'dst': '192.168.80.0/24', 'scope': 'link', 'dev': 'eth1'}, {'dst': 'default', 'dev': 'eth0'}]
    acl = relay.render_acl('[General]\nAllow=@compose-subnets@\n', routes)
    assert 'Allow=10.55.0.0/16\nAllow=192.168.80.0/24' in acl
    assert relay.render_acl('Allow=172.30.69.0/24\n', routes).startswith('Allow=10.55')
    assert relay.render_acl('Allow=10.1.0.1/32\n', routes) == 'Allow=10.1.0.1/32\n'
    try:
        relay.render_acl('Allow=@compose-subnets@', [])
        raise AssertionError('missing routes must fail closed')
    except ValueError:
        pass
    assert 'ipam:' not in (ROOT / 'compose.boncasrelay.yaml').read_text()
    print('PASS: review 8: connected-subnet runtime ACL, repeated Allow syntax, custom ACL preservation, no default IPAM')

    # 9/10: shared templates match host output; per-disk runtimes remain read-only during recordings.
    fresh = base / 'fresh'
    settings = dict(RECORDED_DIR='a', RECORDED_DIRS_JSON='["a", "b", "c"]', EDCB_TUNER_COUNT='4')
    env = dict(os.environ, **settings, EDCB_ROOT=str(fresh / 'data'), EDCB_CONFIG_DIR=str(fresh / 'config'),
               EDCB_LIB=str(fresh / 'lib'), EDCB_DEFAULTS=str(fresh / 'defaults'), EDCB_RECORDED=str(fresh / 'recorded'))
    run('python3', str(ROOT / 'docker/edcb/configure.py'), env=env)
    for template in (ROOT / 'templates/edcb').glob('*.example'):
        expected = render.render('edcb', template.read_text(), settings).replace('/var/local/edcb', str(fresh / 'data'))
        assert (fresh / 'config' / template.name.removesuffix('.example')).read_text() == expected
    # Match the image's /opt layout, which differs from the repository layout.
    image = base / 'image/opt'
    shutil.copytree(ROOT / 'scripts', image / 'scripts')
    shutil.copytree(ROOT / 'templates/edcb', image / 'templates/edcb')
    shutil.copytree(ROOT / 'docker/edcb', image / 'edcb-stack')
    run('python3', str(image / 'edcb-stack/configure.py'),
        env=dict(env, EDCB_STACK_ROOT=str(image), EDCB_CONFIG_DIR=str(fresh / 'image-config')))
    assert (fresh / 'image-config/Common.ini').read_bytes() == (fresh / 'config/Common.ini').read_bytes()
    assert targets(settings) == ['/recorded', '/recorded2', '/recorded3']
    runtime = base / 'runtime'; runtime.mkdir()
    (runtime / 'edcb_to_epgstation_ts').write_bytes(b'executable')
    (runtime / 'config.yml').write_text('epgstationUpload:\n  parentDirectoryName: edcb\n')
    uploader = module('upload_runtime', ROOT / 'docker/edcb/upload_runtime.py')
    uploader.prepare(runtime, [p + '/edcb' for p in targets(settings)])
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in runtime.rglob('*') if p.is_file()}
    for _ in range(2):
        assert post.runtime_for_recording(runtime, '/recorded2/edcb/番組.ts') == runtime / 'recorded2'
        assert post.runtime_for_recording(runtime, '/recorded/edcb/番組.ts') == runtime
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}
    dockerfile = (ROOT / 'docker/edcb/Dockerfile').read_text()
    assert 'FROM uploader-${EDCB_EPGSTATION_ENABLED} AS uploader' in dockerfile
    disabled = dockerfile.split(' AS uploader-0\n')[1].split('\nFROM ')[0]
    assert '/out' in disabled and 'uploader-1' not in disabled
    (runtime / 'config.yml').write_text('epgstationUpload:\n  parentDirectoryName: custom\n')
    uploader.prepare(runtime, ['/recorded/edcb', '/recorded2/edcb'])
    assert post.runtime_for_recording(runtime, '/recorded2/edcb/番組.ts') == runtime
    assert 'EDCB_RECORDING_PATHS=' not in (ROOT / '.env.example').read_text()
    assert 'put EDCB_RECORDING_PATHS' not in (ROOT / 'setup.sh').read_text()
    print('PASS: review 9/10: shared template parity, derived storage paths, startup uploader runtimes, recording performs no writes, optional Rust stage graph')
