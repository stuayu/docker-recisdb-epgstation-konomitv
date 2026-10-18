"""Exercise the real TUI path via a pseudo terminal and scripted dialog answers."""
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def stub(folder, name, text):
    path = folder / name
    path.write_text('#!/bin/bash\n' + text + '\n')
    path.chmod(0o755)
    return path


def terminal(command, cwd, env, input_bytes=None):
    master, slave = pty.openpty()
    proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    if input_bytes is not None:
        os.write(master, input_bytes)
    os.set_blocking(master, False)
    chunks = []
    deadline = time.monotonic() + 60
    try:
        while proc.poll() is None or select.select([master], [], [], 0)[0]:
            if time.monotonic() > deadline:
                proc.kill()
                raise AssertionError('TUI setup timed out\n' + b''.join(chunks).decode(errors='replace'))
            if select.select([master], [], [], .1)[0]:
                try:
                    chunk = os.read(master, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                except BlockingIOError:
                    continue
                except OSError:
                    break
        status = proc.wait(timeout=5)
        output = b''.join(chunks).decode(errors='replace')
        assert status == 0, output
        return output
    finally:
        os.close(master)
        if proc.poll() is None:
            proc.kill()
            proc.wait()


with tempfile.TemporaryDirectory() as temp:
    base = Path(temp)
    repo = base / 'repo'
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns('.git', 'data', 'config', '__pycache__', 'backup'))
    bin_dir = base / 'bin'; bin_dir.mkdir()
    dev = base / 'dev'; dev.mkdir()
    storage = [base / 'disk one', base / 'disk-two']
    for path in storage:
        path.mkdir()
    source = repo / 'konomitv'; source.mkdir(); (source / 'Dockerfile').write_text('FROM scratch\n')
    calls = base / 'calls'
    answers = base / 'answers'
    answers.write_text(json.dumps({'storage': '"1" "2"'}))
    dialog = stub(bin_dir, 'whiptail', '''echo "ui $*" >> "$CALLS"
case "$*" in
  *--checklist*使うソフト*) echo '"EDCB" "AMATSUKAZE" "HTTPS"' >&2;;
  *--checklist*録画先*) python3 -c 'import json,os; print(json.load(open(os.environ["ANSWERS"]))["storage"])' >&2;;
  *--menu*既定の録画先*) echo 0 >&2;;
  *--menu*カードサーバー*) echo local >&2;;
  *--menu*GPU*) echo none >&2;;
  *--inputbox*)
    case "$*" in *GPU*) echo none >&2;; *) echo "${@: -1}" >&2;; esac;;
  *--yesno*) case "$*" in *詳細設定*|*エンコードしますか*) exit 1;; esac;;
esac
exit 0''')
    stub(bin_dir, 'docker', 'echo "docker $*" >> "$CALLS"; exit 0')
    stub(bin_dir, 'sudo', 'echo "sudo $*" >> "$CALLS"; exit 0')
    stub(bin_dir, 'apt-get', 'echo "apt-get $*" >> "$CALLS"; exit 0')
    stub(bin_dir, 'systemctl', 'exit 1')
    stub(bin_dir, 'id', 'case $1 in -u|-g) echo 1000;; -un) echo tester;; esac')
    stub(bin_dir, 'getent', 'exit 1')
    stub(bin_dir, 'modinfo', '[[ ${DRIVER_OK:-0} == 1 ]]')
    stub(bin_dir, 'lsmod', 'exit 0')
    stub(bin_dir, 'nvidia-smi', 'exit 1')
    stub(bin_dir, 'lspci', 'echo "VGA: NVIDIA test"')
    stub(bin_dir, 'lsusb', 'if [[ $1 == -v ]]; then echo "bInterfaceClass 11 Chip/SmartCard"; else echo "ID 0511:083f PLEX"; fi')
    stub(bin_dir, 'ufw', 'echo "Status: active"')
    mount_json = {'filesystems': [{'target': '/', 'fstype': 'ext4', 'avail': 999999999999},
                                 {'target': '/run', 'fstype': 'tmpfs', 'avail': 999999999999},
                                 {'target': str(storage[0]), 'fstype': 'ext4', 'avail': 200000000000},
                                 {'target': str(storage[1]), 'fstype': 'nfs', 'avail': 300000000000}]}
    mounts = base / 'mounts'; mounts.write_text(json.dumps(mount_json))
    stub(bin_dir, 'findmnt', 'cat "$MOUNT_FIXTURE"')
    # findmnt fallback fixtures also exercise lsblk and df discovery independently.
    env = dict(os.environ, PATH=str(bin_dir) + ':/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
               DOCKER_BIN=str(bin_dir / 'docker'), TUNERS_COMPOSE_FILE=str(repo / 'compose.tuners.yaml'),
               CALLS=str(calls), ANSWERS=str(answers), MOUNT_FIXTURE=str(mounts),
               SETUP_OS='Linux', ENV_FILE=str(repo / '.env'), DEV_DIR=str(dev),
               KONOMITV_SOURCE=str(source), OS_RELEASE_FILE=str(base / 'os-release'))
    for key in ('RECORDED_DIR', 'RECORDED_DIRS_JSON', 'AMATSUKAZE', 'EDCB', 'HTTPS', 'BONCAS_MODE', 'GPU'):
        env.pop(key, None)
    (base / 'os-release').write_text('ID=debian\nVERSION_CODENAME=bookworm\n')
    found = subprocess.check_output(['python3', str(repo / 'scripts/storage.py'), 'candidates'], env=env, text=True)
    assert 'ext4 / 200.0 GB' in found and 'nfs / 300.0 GB' in found
    assert '\n/\t' not in '\n' + found and '/run' not in found
    terminal(['./setup.sh', '--no-build', '--no-start'], repo, env)
    values = dict(line.split('=', 1) for line in (repo / '.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    assert json.loads(values['RECORDED_DIRS_JSON']) == [str(p) for p in storage]
    assert values['RECORDED_DIR'] == str(storage[0])
    assert 'compose.boncasrelay.yaml' in values['COMPOSE_FILE'] and 'compose.storage.yaml' in values['COMPOSE_FILE']
    assert values['BONCAS_B25_HOST'] == values['BONCAS_4K_HOST'] == 'boncasrelay'
    assert values['BONCAS_B25_PORT'] == values['BONCAS_4K_PORT'] == '6900'
    assert values['RUN_UID'] == values['RUN_GID'] == '1000'
    assert values['EDCB_EPGSTATION_ENABLED'] == '1' and values['EDCB_EPGSTATION_ENCODE'] == '0'
    assert 'boncasrelay:6900' in (repo / 'config/recisdb-proxy/recisdb-proxy.toml').read_text()
    epg = (repo / 'config/epgstation/config.yml').read_text()
    assert 'name: recorded2' in epg and 'name: edcb2' in epg
    assert '/recorded2' in (repo / 'config/konomitv/config.yaml').read_text()
    common = (repo / 'config/edcb/Common.ini').read_text()
    assert 'RecFolderNum=2' in common and 'RecFolderPath1=/recorded2/edcb' in common
    assert 'BatFilePath=/opt/edcb-stack/post-record.sh' in (repo / 'config/edcb/EpgTimerSrv.ini').read_text()
    upload = (repo / 'config/edcb-to-epgstation/config.yml').read_text()
    assert 'uploadMode: "path"' in upload and 'runEncode: false' in upload
    assert 'Allow=@compose-subnets@' in (repo / 'config/boncasrelay/boncasrelay.ini').read_text()
    assert 'c 189:* rw' in (repo / 'compose.boncasrelay.yaml').read_text()
    mounts_out = json.loads((repo / 'compose.storage.yaml').read_text())['services']
    assert mounts_out['konomitv']['volumes'][0]['target'] == '/host-rootfs/recorded2'
    assert all(v['volumes'][0]['source'] == str(storage[1].resolve()) for v in mounts_out.values())
    log = calls.read_text()
    assert 'sudo bash' in log and 'install-host.sh px4' in log and 'install-host.sh nvidia' in log, log
    assert 'UFW 有効' in log and '導入手順' not in log  # textbox shows the actual recipe.
    # Reconfiguration preserves settings and uses current values as defaults.
    config = repo / 'config/epgstation/config.yml'
    config.write_text(epg + '# user edit\n')
    stub(bin_dir, 'nvidia-ctk', 'exit 0')
    calls.write_text('')
    terminal(['./setup.sh', '--reconfigure'], repo, dict(env, DRIVER_OK='1'))
    assert 'install-host.sh px4' not in calls.read_text() and 'install-host.sh nvidia' not in calls.read_text()
    assert config.read_text() == epg + '# user edit\n'
    # Storage-only skips Docker, GPU and software configuration.
    calls.write_text('')
    terminal(['./setup.sh', '--storage-only'], repo, env)
    assert not any(line.startswith('docker ') for line in calls.read_text().splitlines())
    assert config.read_text() == epg + '# user edit\n'
    # A privileged install is never implicitly approved by --yes.
    calls.write_text('')
    script = f'''source {repo}/scripts/setup-ui.sh
YES=1; NONINTERACTIVE=1; AUTO_INSTALL=0
if confirm_sudo apt-get install -y whiptail; then exit 10; fi
AUTO_INSTALL=1
confirm_sudo apt-get install -y whiptail
'''
    subprocess.run(['bash', '-c', script], env=env, check=True, capture_output=True)
    assert calls.read_text().count('sudo apt-get install -y whiptail') == 1
    # Missing TUI dependency: show/install it only after approval; refusal falls back.
    dialog.rename(bin_dir / 'whiptail.hidden')
    calls.write_text('')
    init_script = f'''source {repo}/scripts/setup-ui.sh
YES=0; NONINTERACTIVE=0; AUTO_INSTALL=0
init_ui
'''
    output = terminal(['bash', '-c', init_script], repo, env, input_bytes=b'n\n')
    assert 'apt-get install -y whiptail' in output
    assert not calls.read_text() if calls.exists() else True
    # Progress logging retains a failing command's output and status.
    log_script = f'''set -o pipefail
source {repo}/scripts/setup-ui.sh
ROOT={repo}; TUI=''
if run_logged failure bash -c 'echo expected-build-failure; exit 7'; then exit 10; fi
[[ -f $LOG_FILE ]] && grep -q expected-build-failure "$LOG_FILE"
'''
    subprocess.run(['bash', '-c', log_script], env=env, check=True, capture_output=True)
    # No reader or supported tuner => no detection false positives.
    stub(bin_dir, 'lsusb', 'exit 0')
    subprocess.run(['bash', '-c', f'source {repo}/scripts/setup-host.sh; ! card_reader_detected && ! known_tuner_usb'], env=env, check=True)
    # lsblk and df fallback both retain network drives.
    stub(bin_dir, 'findmnt', 'exit 1')
    block = base / 'blocks'; block.write_text(json.dumps({'blockdevices': [{'mountpoints': [str(storage[0])], 'fstype': 'xfs', 'fsavail': 200000000000}]}))
    env['BLOCK_FIXTURE'] = str(block)
    stub(bin_dir, 'lsblk', 'cat "$BLOCK_FIXTURE"')
    found = subprocess.check_output(['python3', str(repo / 'scripts/storage.py'), 'candidates'], env=env, text=True)
    assert 'xfs / 200.0 GB' in found
    stub(bin_dir, 'lsblk', 'exit 1')
    stub(bin_dir, 'df', 'printf "Filesystem Type 1024-blocks Used Available Capacity Mounted on\\nserver:/tv nfs 500000000 100 200000000 1%% /mnt/network\\n"')
    found = subprocess.check_output(['python3', str(repo / 'scripts/storage.py'), 'candidates'], env=env, text=True)
    assert '/mnt/network\tnfs / 204.8 GB' in found

    # Regeneration uses image defaults, backs up runtime-generated XML, and
    # leaves independent user assets intact. Docker only streams a fixture tar.
    defaults = base / 'amatsukaze-defaults'
    (defaults / 'profile').mkdir(parents=True)
    (defaults / 'profile/EPGStation.profile').write_text('image profile')
    archive = base / 'defaults.tar'
    import tarfile
    with tarfile.open(archive, 'w') as tar:
        tar.add(defaults / 'profile', arcname='profile')
    settings = repo / 'config/amatsukaze'
    (settings / 'config').mkdir(exist_ok=True)
    (settings / 'logo').mkdir(exist_ok=True)
    (settings / 'config/AmatsukazeServer.xml').write_text('<edited/>')
    (settings / 'profile/EPGStation.profile').write_text('edited profile')
    (settings / 'logo/custom.lgd').write_bytes(b'custom logo')
    stub(bin_dir, 'docker', 'cat "$DEFAULT_ARCHIVE"')
    regen_env = dict(env, DEFAULT_ARCHIVE=str(archive))
    command = ['python3', str(repo / 'scripts/regen-amatsukaze.py')]
    rejected = subprocess.run(command, env=regen_env, cwd=repo, capture_output=True)
    assert rejected.returncode != 0
    assert (settings / 'config/AmatsukazeServer.xml').read_text() == '<edited/>'
    terminal(command, repo, regen_env, input_bytes=b'y\n')
    assert not (settings / 'config/AmatsukazeServer.xml').exists()
    assert (settings / 'profile/EPGStation.profile').read_text() == 'image profile'
    assert (settings / 'logo/custom.lgd').read_bytes() == b'custom logo'
    assert list((settings / 'backup').glob('*/config/AmatsukazeServer.xml'))

print('PASS: Amatsukaze regeneration diff/confirmation/backup, runtime XML reset, custom assets retained')
print('PASS: TUI selections, storage discovery/findmnt/lsblk/df, multiple mounts, local Relay, installer confirmation, storage-only, reconfigure preservation')
