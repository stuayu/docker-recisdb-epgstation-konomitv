"""Config provisioning contract: first-run generation, migration, regeneration with backup, backup and restore."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV_TEXT = """TZ=Asia/Tokyo
COMPOSE_FILE=compose.yaml:compose.tuners.yaml
BONCAS_B25_HOST=192.168.1.10
BONCAS_B25_PORT=6900
BONCAS_4K_HOST=
BONCAS_4K_PORT=6900
RECORDED_DIR=./data/recorded
MARIADB_PASSWORD=a:b #c"d\\e $value
MARIADB_ROOT_PASSWORD=root-test
"""
AMATSUKAZE_COMPOSE = 'compose.yaml:compose.tuners.yaml:compose.amatsukaze.yaml'


def fail(message):
    raise SystemExit(f'FAIL: {message}')


def check(condition, message):
    if not condition:
        fail(message)


def make_repo(base):
    repo = base / 'repo'
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns('.git', '__pycache__', 'backup'))
    return repo


def write_env(path, compose=None, extra=''):
    text = ENV_TEXT
    if compose is not None:
        text = text.replace('COMPOSE_FILE=compose.yaml:compose.tuners.yaml', f'COMPOSE_FILE={compose}')
    path.write_text(text + extra, encoding='utf-8')
    return path


def render(repo, env, command, *extra, check_status=True):
    result = subprocess.run(['python3', str(repo / 'scripts/render-config.py'), '--root', str(repo),
                             '--env', str(env), *command, *extra],
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if check_status:
        check(result.returncode == 0, f'render {command} failed: {result.stdout}{result.stderr}')
    return result


def ruby_yaml(path):
    result = subprocess.run(['ruby', '-ryaml', '-rjson', '-e', 'puts JSON.generate(YAML.load_file(ARGV[0]))', str(path)],
                            capture_output=True, text=True)
    check(result.returncode == 0, f'YAML invalid: {result.stderr}')
    import json
    return json.loads(result.stdout)


dockerfile = (ROOT / 'docker/recisdb-proxy/Dockerfile').read_text(encoding='utf-8')
check('FROM ubuntu:24.04 AS web-builder' in dockerfile and 'npm ci && npm run build' in dockerfile,
      'recisdb Dockerfile builds web UI with CI LTS Node and lockfile')
check('COPY --from=web-builder /src/recisdb-proxy/static/vue /src/recisdb-proxy/static/vue' in dockerfile
      and dockerfile.index('COPY --from=web-builder') < dockerfile.index('RUN cargo build'),
      'Vue output is copied to rust-embed folder before cargo build')
print('PASS: recisdb Dockerfile statically builds and embeds Vue dashboard')


with tempfile.TemporaryDirectory() as temp:
    base = Path(temp)

    # 1. First run creates all three files with embedded values; the template is copied for KonomiTV.
    repo = make_repo(base / 'one')
    env = write_env(base / 'one/.env')
    render(repo, env, ['first-run'])
    toml = (repo / 'config/recisdb-proxy/recisdb-proxy.toml').read_text(encoding='utf-8')
    check('boncaslink_server = "192.168.1.10:6900"' in toml, 'B25 relay embedded')
    check(re.search(r'(?m)^auth_enabled = false$', toml), 'Web auth disabled by default')
    check(not re.search(r'RUST_LOG', (repo / 'docker/recisdb-proxy/entrypoint.sh').read_text()),
          'recisdb entrypoint does not override RUST_LOG')
    check('[mmttlv]' not in toml, '4K table removed when no 4K relay')
    check((repo / 'config/konomitv/config.yaml').read_bytes() == (repo / 'templates/konomitv/config.yaml.example').read_bytes(),
          'KonomiTV copied from template')
    konomi_text = (repo / 'config/konomitv/config.yaml').read_text(encoding='utf-8')
    check("'/data/konomitv-capture'" in konomi_text and not re.search(r"[A-Za-z]:\\", konomi_text),
          'KonomiTV generated config uses Docker-mounted capture path and no Windows paths')
    epg = ruby_yaml(repo / 'config/epgstation/config.yml')
    check(epg['mysql']['password'] == 'a:b #c"d\\e $value', 'DB password quoted safely')
    check(not any(p.get('id') == 'amatsukaze' for p in epg['encode']), 'Amatsukaze preset absent when disabled')
    check('amatsukaze' not in epg, 'Amatsukaze section absent when disabled')
    check('${' not in (repo / 'config/epgstation/config.yml').read_text(encoding='utf-8'), 'no unresolved placeholders')
    check(oct((repo / 'config/epgstation/config.yml').stat().st_mode & 0o777) == '0o600', 'EPGStation config is 0600')
    check(oct((repo / 'config/recisdb-proxy/recisdb-proxy.toml').stat().st_mode & 0o777) == '0o600', 'recisdb config is 0600 (optional API token)')

    # 2. A second run never overwrites user edits.
    (repo / 'config/recisdb-proxy/recisdb-proxy.toml').write_text('user = "kept"\n', encoding='utf-8')
    out = render(repo, env, ['first-run']).stdout
    check((repo / 'config/recisdb-proxy/recisdb-proxy.toml').read_text(encoding='utf-8') == 'user = "kept"\n',
          'user recisdb edit preserved')
    check('既存の設定を維持' in out, 'keep message printed')

    # Existing auth is migrated with a backup, but an explicit token means opt-in.
    auth_repo = make_repo(base / 'auth-migration')
    auth_env = write_env(base / 'auth-migration/.env')
    auth_config = auth_repo / 'config/recisdb-proxy/recisdb-proxy.toml'
    auth_config.parent.mkdir(parents=True)
    auth_config.write_text('[web]\nauth_enabled = true\n', encoding='utf-8')
    out = render(auth_repo, auth_env, ['first-run']).stdout
    check('auth_enabled = false' in auth_config.read_text(encoding='utf-8'), 'existing Web auth disabled')
    backups = list((auth_config.parent / 'backup').glob('recisdb-proxy.toml.*'))
    check(len(backups) == 1 and 'auth_enabled = true' in backups[0].read_text(encoding='utf-8'),
          'existing auth config backed up before migration')
    check('認証を無効化' in out and '退避:' in out, 'auth migration reported')
    token_repo = make_repo(base / 'auth-token-preserved')
    token_env = write_env(base / 'auth-token-preserved/.env')
    token_config = token_repo / 'config/recisdb-proxy/recisdb-proxy.toml'
    token_config.parent.mkdir(parents=True)
    token_config.write_text('[web]\nauth_enabled = true\nauth_token = "custom-token"\n', encoding='utf-8')
    out = render(token_repo, token_env, ['first-run']).stdout
    check('auth_enabled = true' in token_config.read_text(encoding='utf-8'), 'explicit token preserves auth')
    check('auth_token' in out and not list((token_config.parent / 'backup').glob('*')),
          'explicit token preserve reported without backup')

    # 3. Amatsukaze on and 4K relay set: both sections are embedded at first run.
    repo2 = make_repo(base / 'two')
    env2 = write_env(base / 'two/.env', compose=AMATSUKAZE_COMPOSE)
    env2.write_text(env2.read_text(encoding='utf-8').replace('BONCAS_4K_HOST=\n', 'BONCAS_4K_HOST=192.168.1.11\n')
                    .replace('BONCAS_4K_PORT=6900', 'BONCAS_4K_PORT=6901'), encoding='utf-8')
    render(repo2, env2, ['first-run'])
    toml2 = (repo2 / 'config/recisdb-proxy/recisdb-proxy.toml').read_text(encoding='utf-8')
    check('[mmttlv]' in toml2 and 'boncaslink_server = "192.168.1.11:6901"' in toml2, '4K relay embedded')
    epg2 = ruby_yaml(repo2 / 'config/epgstation/config.yml')
    check(epg2['amatsukaze']['host'] == 'amatsukaze' and epg2['amatsukaze']['port'] == 32768, 'Amatsukaze section embedded')
    presets = [p for p in epg2['encode'] if p.get('id') == 'amatsukaze']
    check(len(presets) == 1 and presets[0]['suffix'] == '.mp4', 'Amatsukaze preset embedded')

    # 4. Migration: the old recisdb path is copied (not moved) into the new location.
    repo3 = make_repo(base / 'three')
    env3 = write_env(base / 'three/.env')
    legacy = repo3 / 'data/recisdb/recisdb-proxy.toml'
    legacy.parent.mkdir(parents=True)
    legacy.write_text('legacy = true\n', encoding='utf-8')
    out = render(repo3, env3, ['first-run']).stdout
    check((repo3 / 'config/recisdb-proxy/recisdb-proxy.toml').read_text(encoding='utf-8') == 'legacy = true\n', 'legacy copied')
    check(legacy.read_text(encoding='utf-8') == 'legacy = true\n', 'legacy file kept')
    check('旧設定を移行' in out, 'migration message printed')

    # KonomiTV migration replaces only Windows upload folders and backs up the edited file.
    repo_konomi = make_repo(base / 'konomi-migration')
    env_konomi = write_env(base / 'konomi-migration/.env')
    render(repo_konomi, env_konomi, ['first-run'])
    konomi = repo_konomi / 'config/konomitv/config.yaml'
    old_konomi = konomi.read_text(encoding='utf-8').replace(
        "'/data/konomitv-capture'", "'E:\\TV-Capture'") + '\n# user setting retained\n'
    old_konomi = old_konomi.replace("backend: 'Mirakurun'", "backend: 'EDCB'")
    konomi.write_text(old_konomi, encoding='utf-8')
    out = render(repo_konomi, env_konomi, ['first-run']).stdout
    migrated_konomi = konomi.read_text(encoding='utf-8')
    backups = list((repo_konomi / 'config/konomitv/backup').glob('config.yaml.*'))
    check("'/data/konomitv-capture'" in migrated_konomi and 'E:\\TV-Capture' not in migrated_konomi,
          'Windows KonomiTV upload folder migrated')
    check("backend: 'EDCB'" in migrated_konomi and '# user setting retained' in migrated_konomi,
          'KonomiTV migration preserves unrelated edits')
    check(len(backups) == 1 and backups[0].read_text(encoding='utf-8') == old_konomi,
          'KonomiTV migration keeps exact pre-migration backup')
    check('upload_folders' in out and '退避:' in out, 'KonomiTV migration reports replacement and backup')

    # 5. Amatsukaze enabled later: the existing file is not rewritten, the user is told to regenerate.
    repo4 = make_repo(base / 'four')
    render(repo4, write_env(base / 'four/.env'), ['first-run'])
    before = (repo4 / 'config/epgstation/config.yml').read_text(encoding='utf-8')
    out = render(repo4, write_env(base / 'four/.env2', compose=AMATSUKAZE_COMPOSE), ['first-run']).stdout
    check((repo4 / 'config/epgstation/config.yml').read_text(encoding='utf-8') == before, 'EPGStation file untouched')
    check('make regen-config SERVICE=epgstation' in out, 'regen guidance printed')

    # 6. Regeneration: backup first, show the diff, keep the inode for bind mounts.
    target = repo4 / 'config/epgstation/config.yml'
    inode = target.stat().st_ino
    env4 = write_env(base / 'four/.env3', compose=AMATSUKAZE_COMPOSE)
    refused = render(repo4, env4, ['regen', '--service', 'epgstation'], check_status=False)
    check(refused.returncode != 0, 'regen without a terminal and without --yes must refuse')
    check(target.read_text(encoding='utf-8') == before, 'refused regen leaves the file unchanged')
    check(not (repo4 / 'config/epgstation/backup').exists(), 'refused regen makes no backup')
    result = render(repo4, env4, ['regen', '--service', 'epgstation', '--yes'])
    check('+    - id: amatsukaze' in result.stdout, 'diff shown before replacing')
    backups = list((repo4 / 'config/epgstation/backup').glob('config.yml.*'))
    check(len(backups) == 1 and backups[0].read_text(encoding='utf-8') == before, 'backup holds the previous file')
    check('amatsukaze' in ruby_yaml(target), 'regenerated file contains Amatsukaze section')
    check(target.stat().st_ino == inode, 'file rewritten in place (inode kept)')
    no_change = render(repo4, env4, ['regen', '--service', 'epgstation', '--yes'])
    check('変更はありません' in no_change.stdout, 'unchanged regen reports no change')
    check(len(list((repo4 / 'config/epgstation/backup').glob('config.yml.*'))) == 1, 'no extra backup when unchanged')

    # 7. Unsafe values are refused instead of producing broken TOML.
    repo5 = make_repo(base / 'five')
    env5 = write_env(base / 'five/.env', extra='')
    env5.write_text(env5.read_text(encoding='utf-8').replace('BONCAS_B25_HOST=192.168.1.10', 'BONCAS_B25_HOST=bad"host'), encoding='utf-8')
    bad = render(repo5, env5, ['first-run'], check_status=False)
    check(bad.returncode != 0 and not (repo5 / 'config/recisdb-proxy/recisdb-proxy.toml').exists(), 'unsafe relay host refused')

    # 8. Backup and restore with a docker stub: recorded files and the raw MariaDB directory are excluded.
    repo6 = make_repo(base / 'six')
    env6 = write_env(repo6 / '.env')
    render(repo6, env6, ['first-run'])
    (repo6 / 'data/recisdb').mkdir(parents=True)
    (repo6 / 'data/recisdb/recisdb-proxy.db').write_text('db', encoding='utf-8')
    (repo6 / 'data/recorded').mkdir(parents=True)
    (repo6 / 'data/recorded/program.ts').write_text('video', encoding='utf-8')
    (repo6 / 'data/recorded2').mkdir()
    (repo6 / 'data/recorded2/extra.ts').write_text('extra video')
    with (repo6 / '.env').open('a') as file:
        file.write('RECORDED_DIRS_JSON=["./data/recorded", "./data/recorded2"]\n')
    (repo6 / 'data/mariadb').mkdir(parents=True)
    (repo6 / 'data/mariadb/ibdata1').write_text('raw', encoding='utf-8')
    stub = base / 'docker'
    stub.write_text(
        '#!/bin/sh\n'
        'echo "$*" >> "$DOCKER_CALLS"\n'
        'case "$*" in\n'
        '  *mariadb-dump*) printf -- "-- dump\\nCREATE TABLE t (id int);\\n";;\n'
        '  *"SELECT 1"*) ;;\n'
        '  *"mariadb -uroot -p"*) cat > "$RESTORE_SQL";;\n'
        'esac\n'
        'exit 0\n', encoding='utf-8')
    stub.chmod(0o755)
    calls = base / 'docker.calls'
    restored_sql = base / 'restored.sql'
    stub_env = dict(os.environ, DOCKER_BIN=str(stub), DOCKER_CALLS=str(calls), RESTORE_SQL=str(restored_sql))
    backup_dir = base / 'backups'
    subprocess.run([str(repo6 / 'scripts/backup.sh')], env=dict(stub_env, ENV_FILE=str(repo6 / '.env'), BACKUP_DIR=str(backup_dir)),
                   check=True, capture_output=True, text=True, cwd=repo6)
    archives = list(backup_dir.glob('konomi-backup-*.tar.gz'))
    check(len(archives) == 1, 'one backup archive created')
    with tarfile.open(archives[0]) as tar:
        names = tar.getnames()
        check('.env' in names and 'config/epgstation/config.yml' in names, 'config and .env archived')
        check('data/recisdb/recisdb-proxy.db' in names, 'service data archived')
        check('db/epgstation.sql' in names, 'MariaDB dump archived')
        check(not any(n.startswith('data/recorded') for n in names), 'all selected recorded folders excluded')
        check(not any(n.startswith('data/mariadb') for n in names), 'raw MariaDB directory excluded')
        check(b'CREATE TABLE t' in tar.extractfile('db/epgstation.sql').read(), 'dump content archived')

    repo7 = make_repo(base / 'seven')
    subprocess.run([str(repo7 / 'scripts/restore.sh'), str(archives[0])], env=dict(stub_env, YES='1'),
                   check=True, capture_output=True, text=True, cwd=repo7)
    check((repo7 / 'config/epgstation/config.yml').is_file(), 'config restored')
    check((repo7 / 'data/recisdb/recisdb-proxy.db').read_text(encoding='utf-8') == 'db', 'data restored')
    check(restored_sql.read_text(encoding='utf-8') == '-- dump\nCREATE TABLE t (id int);\n', 'dump imported')
    check(not (repo7 / 'data/recorded/program.ts').exists(), 'recorded files not restored from archive')

print('PASS: config first-run generation, KonomiTV Windows path migration/backup, regen backup/diff/inode, unsafe values, backup excludes recorded files, restore imports dump')

# EDCB access defaults migrate only when the old values are exact matches.
with tempfile.TemporaryDirectory() as temp:
    base = Path(temp)
    repo = make_repo(base / 'edcb-access')
    env = write_env(repo / '.env', compose='compose.yaml:compose.tuners.yaml:compose.edcb.yaml')
    config = repo / 'config/edcb'
    (config / 'Setting').mkdir(parents=True)
    old_acl = '+127.0.0.1,+10.0.0.0/8,+172.16.0.0/12,+192.168.0.0/16'
    timer = config / 'EpgTimerSrv.ini'
    timer.write_text('[SET]\nHttpAccessControlList=' + old_acl + '\nUser=kept\n')
    public = config / 'Setting/HttpPublic.ini'
    public.write_bytes('[SET]\nALLOW_SETTING_LIST=127.0.0.1,::1\n'.encode() + '名前=維持\n'.encode('shift_jis'))
    out = render(repo, env, ['first-run']).stdout
    assert '+100.64.0.0/10' in timer.read_text()
    assert 'ALLOW_SETTING_LIST=\n' in public.read_bytes().decode('shift_jis')
    assert '名前=維持' in public.read_bytes().decode('shift_jis')
    assert list(config.glob('EpgTimerSrv.ini.pre-config-migration'))
    assert list((config / 'Setting').glob('HttpPublic.ini.pre-config-migration'))
    assert 'HttpAccessControlList の既定値を移行' in out

    custom = make_repo(base / 'edcb-access-custom')
    custom_env = write_env(custom / '.env', compose='compose.yaml:compose.tuners.yaml:compose.edcb.yaml')
    custom_dir = custom / 'config/edcb'
    (custom_dir / 'Setting').mkdir(parents=True)
    custom_timer = custom_dir / 'EpgTimerSrv.ini'
    custom_timer.write_text('[SET]\nHttpAccessControlList=+127.0.0.1,+192.168.10.0/24\n')
    custom_public = custom_dir / 'Setting/HttpPublic.ini'
    custom_public.write_text('[SET]\nALLOW_SETTING_LIST=127.0.0.1,192.168.10.9\n')
    out = render(custom, custom_env, ['first-run']).stdout
    assert custom_timer.read_text().endswith('+192.168.10.0/24\n')
    assert custom_public.read_text().endswith('127.0.0.1,192.168.10.9\n')
    assert not list(custom_dir.glob('EpgTimerSrv.ini.pre-config-migration'))
    assert not list((custom_dir / 'Setting').glob('HttpPublic.ini.pre-config-migration'))
    assert 'Tailscale から使う場合' in out
print('PASS: EDCB Tailscale ACL and exact-default HttpPublic access migration')

# Optional configurations and migration preserve runtime databases and user settings.
with tempfile.TemporaryDirectory() as temp:
    base = Path(temp)
    repo = make_repo(base / 'optional')
    old = repo / 'data/edcb'
    (old / 'Setting').mkdir(parents=True)
    (old / 'Common.ini').write_text('[SET]\nUserSetting=kept\n')
    (old / 'Setting/HttpPublic.ini').write_text('[E3]\nuser=kept\n')
    (old / 'Setting/ChSet5.txt').write_text('channels\n')
    (old / 'Setting/Reserve.txt').write_text('reservation runtime\n')
    (repo / 'data/amatsukaze/config').mkdir(parents=True)
    (repo / 'data/amatsukaze/config/AmatsukazeServer.xml').write_text('<user/>')
    env = write_env(repo / '.env', compose=AMATSUKAZE_COMPOSE + ':compose.edcb.yaml:compose.boncasrelay.yaml',
                    extra='EDCB_EPGSTATION_ENABLED=1\nEDCB_EPGSTATION_ENCODE=1\nRECORDED_DIRS_JSON=["./data/recorded", "./data/recorded2"]\n')
    render(repo, env, ['first-run'])
    assert (repo / 'config/edcb/Common.ini').read_bytes() == (old / 'Common.ini').read_bytes()
    assert (old / 'Setting/Reserve.txt').read_text() == 'reservation runtime\n'
    assert not (repo / 'config/edcb/Setting/Reserve.txt').exists()
    assert (repo / 'config/edcb/Setting/HttpPublic.ini').read_text() == '[E3]\nuser=kept\n'
    assert (repo / 'config/edcb/Setting/ChSet5.txt').read_text() == 'channels\n'
    assert (repo / 'config/amatsukaze/config/AmatsukazeServer.xml').read_text() == '<user/>'
    assert (repo / 'data/amatsukaze/config/AmatsukazeServer.xml').read_text() == '<user/>'
    uploader = ruby_yaml(repo / 'config/edcb-to-epgstation/config.yml')
    assert uploader['epgstationUpload']['epgstationUrl'] == 'http://epgstation:8888/'
    assert uploader['epgstationUpload']['uploadMode'] == 'path'
    assert uploader['epgstationUpload']['deleteEDCBRecFile'] is False
    assert uploader['epgstationEncode']['runEncode'] is True
    assert uploader['epgstationEncode']['mode'] == 'Amatsukaze'
    # Disabled services do not generate settings or batch hooks.
    disabled = make_repo(base / 'disabled')
    render(disabled, write_env(disabled / '.env'), ['first-run'])
    assert not (disabled / 'config/boncasrelay').exists()
    assert not (disabled / 'config/edcb-to-epgstation').exists()
    assert not (disabled / 'config/edcb').exists()
    # Regen updates only requested settings with backups.
    render(repo, env, ['regen', '--service', 'edcb', '--yes'])
    assert 'RecFolderPath1=/recorded2/edcb' in (repo / 'config/edcb/Common.ini').read_text()
    assert list((repo / 'config/edcb/backup').glob('Common.ini.*'))
    epg = ruby_yaml(repo / 'config/epgstation/config.yml')
    assert {item['name']: item['path'] for item in epg['importDirs']} == {'edcb': '/recorded/edcb', 'edcb2': '/recorded2/edcb'}
    assert {item['name']: item['path'] for item in epg['recorded']} == {
        'recorded': '/recorded', 'recorded2': '/recorded2', 'edcb': '/recorded/edcb', 'edcb2': '/recorded2/edcb'}

print('PASS: optional Relay/uploader settings, encode opt-in, EDCB/Amatsukaze migration, runtime data retained, multiple storage configuration, EDCB regen backup')
