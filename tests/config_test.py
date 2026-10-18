"""Config provisioning contract: first-run generation, migration, regeneration with backup, backup and restore."""
import os
from pathlib import Path
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


with tempfile.TemporaryDirectory() as temp:
    base = Path(temp)

    # 1. First run creates all three files with embedded values; the template is copied for KonomiTV.
    repo = make_repo(base / 'one')
    env = write_env(base / 'one/.env')
    render(repo, env, ['first-run'])
    toml = (repo / 'config/recisdb-proxy/recisdb-proxy.toml').read_text(encoding='utf-8')
    check('boncaslink_server = "192.168.1.10:6900"' in toml, 'B25 relay embedded')
    check('[mmttlv]' not in toml, '4K table removed when no 4K relay')
    check((repo / 'config/konomitv/config.yaml').read_bytes() == (repo / 'templates/konomitv/config.yaml.example').read_bytes(),
          'KonomiTV copied from template')
    epg = ruby_yaml(repo / 'config/epgstation/config.yml')
    check(epg['mysql']['password'] == 'a:b #c"d\\e $value', 'DB password quoted safely')
    check(not any(p.get('id') == 'amatsukaze' for p in epg['encode']), 'Amatsukaze preset absent when disabled')
    check('amatsukaze' not in epg, 'Amatsukaze section absent when disabled')
    check('${' not in (repo / 'config/epgstation/config.yml').read_text(encoding='utf-8'), 'no unresolved placeholders')
    check(oct((repo / 'config/epgstation/config.yml').stat().st_mode & 0o777) == '0o600', 'EPGStation config is 0600')
    check(oct((repo / 'config/recisdb-proxy/recisdb-proxy.toml').stat().st_mode & 0o777) == '0o644', 'recisdb config is 0644')

    # 2. A second run never overwrites user edits.
    (repo / 'config/recisdb-proxy/recisdb-proxy.toml').write_text('user = "kept"\n', encoding='utf-8')
    out = render(repo, env, ['first-run']).stdout
    check((repo / 'config/recisdb-proxy/recisdb-proxy.toml').read_text(encoding='utf-8') == 'user = "kept"\n',
          'user recisdb edit preserved')
    check('既存の設定を維持' in out, 'keep message printed')

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
        check(not any(n.startswith('data/recorded') for n in names), 'recorded files excluded')
        check(not any(n.startswith('data/mariadb') for n in names), 'raw MariaDB directory excluded')
        check(b'CREATE TABLE t' in tar.extractfile('db/epgstation.sql').read(), 'dump content archived')

    repo7 = make_repo(base / 'seven')
    subprocess.run([str(repo7 / 'scripts/restore.sh'), str(archives[0])], env=dict(stub_env, YES='1'),
                   check=True, capture_output=True, text=True, cwd=repo7)
    check((repo7 / 'config/epgstation/config.yml').is_file(), 'config restored')
    check((repo7 / 'data/recisdb/recisdb-proxy.db').read_text(encoding='utf-8') == 'db', 'data restored')
    check(restored_sql.read_text(encoding='utf-8') == '-- dump\nCREATE TABLE t (id int);\n', 'dump imported')
    check(not (repo7 / 'data/recorded/program.ts').exists(), 'recorded files not restored from archive')

print('PASS: config first-run generation, migration, regen backup/diff/inode, unsafe values, backup excludes recorded files, restore imports dump')
