#!/usr/bin/env python3
"""Detect GPUs, encode inside each image, and preserve manually edited settings."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys

from generated_config import replace_generated

VENDORS = {'0x8086': 'intel', '0x1002': 'amd', '0x10de': 'nvidia'}
# Dedicated NVIDIA first, then AMD, then Intel. GPU=... always overrides this.
PRIORITY = ('nvidia', 'amd', 'intel')
FFMPEG = {'epgstation': 'ffmpeg', 'recisdb-proxy': '/opt/recisdb-proxy/thirdparty/ffmpeg/ffmpeg',
          'konomitv': '/code/server/thirdparty/FFmpeg/ffmpeg.elf'}
RIGAYA = {'intel': 'QSVEncC', 'amd': 'VCEEncC', 'nvidia': 'NVEncC'}


VENDOR_NAMES = {'intel': r'\bIntel\b', 'amd': r'\b(?:AMD|ATI)\b', 'nvidia': r'\bNVIDIA\b'}


def _pci_vendor(line):
    """Return the vendor of one lspci -nn line, preferring the PCI vendor ID."""
    lowered = line.lower()
    for code, name in VENDORS.items():
        if f'[{code[2:]}:' in lowered:
            return name
    for name, pattern in VENDOR_NAMES.items():
        if re.search(pattern, line):
            return name
    return None


def detect(sys_drm=Path('/sys/class/drm'), pci=None):
    found = set()
    for path in sys_drm.glob('*/device/vendor'):
        try:
            vendor = VENDORS.get(path.read_text().strip().lower())
            if vendor:
                found.add(vendor)
        except OSError:
            pass
    # lspci is only a fallback for hosts where sysfs exposes no GPU at all.
    if not found:
        if pci is None:
            try:
                pci = subprocess.run(['lspci', '-nn'], capture_output=True, text=True,
                                     timeout=10, check=False).stdout
            except (OSError, subprocess.TimeoutExpired):
                pci = ''
        # Restrict fallback to display devices; NVIDIA audio/USB functions are not GPUs.
        for line in pci.splitlines():
            if not re.search(r'VGA compatible|3D controller|Display controller', line, re.I):
                continue
            vendor = _pci_vendor(line)
            if vendor:
                found.add(vendor)
    return next((name for name in PRIORITY if name in found), 'none')


def render_nodes(sys_drm=Path('/sys/class/drm')):
    """Return render node paths paired with their DRM vendor."""
    nodes = []
    for device in sorted(sys_drm.glob('renderD*/device/vendor')):
        try:
            vendor = VENDORS.get(device.read_text().strip().lower())
            if vendor:
                nodes.append((vendor, f"/dev/dri/{device.parents[1].name}"))
        except OSError:
            pass
    return nodes


def selected_render_node(gpu, sys_drm=Path('/sys/class/drm')):
    nodes = render_nodes(sys_drm)
    if gpu == 'none':
        return None
    vendor = gpu if gpu in ('intel', 'amd', 'nvidia') else next(
        (name for name in PRIORITY if any(item[0] == name for item in nodes)), 'none')
    return next((node for name, node in nodes if name == vendor), None)


def ffmpeg_args(backend, codec, node=None, size='1280x720'):
    args = ['-hide_banner', '-loglevel', 'error', '-nostdin']
    if backend == 'vaapi':
        if not node:
            raise ValueError('VA-API probe requires a render node matching the selected GPU vendor')
        args += ['-vaapi_device', node]
    # QSV uses the same implicit system-memory upload as EPGStation's presets.
    # Do not pass -init_hw_device only in the probe: that could mask runtime failure.
    args += ['-f', 'lavfi', '-i', f'testsrc2=size={size}:rate=30', '-t', '1', '-an', '-vf',
             'format=nv12,hwupload' if backend == 'vaapi' else 'format=nv12' if backend == 'qsv' else 'format=yuv420p',
             '-c:v', ('libx264' if codec == 'h264' else 'libx265') if backend == 'software' else f'{codec}_{backend}']
    if backend == 'software':
        args += ['-preset', 'veryfast', '-threads', '2']
    elif backend == 'qsv':
        args += ['-preset', 'veryfast']
    args += ['-b:v', '2000k', '-f', 'null', '-']
    return args


class Probe:
    def __init__(self, root, env, docker_bin):
        self.root, self.env, self.docker = root, env, docker_bin
        self.logs = []

    def run(self, service, command):
        args = [self.docker, 'compose', 'run', '--rm', '--no-deps', '-T']
        if service == 'amatsukaze' or (service == 'epgstation' and 'compose.amatsukaze.yaml' in self.env.get('COMPOSE_FILE', '').split(':')):
            args += ['--user', f"{self.env.get('RUN_UID', '1000')}:{self.env.get('RUN_GID', '1000')}"]
        args += ['--entrypoint', '/bin/sh', service, '-ec', command]
        try:
            result = subprocess.run(args, cwd=self.root, env={**os.environ, **self.env},
                                    capture_output=True, text=True, timeout=90, check=False)
            success = result.returncode == 0
            output = (result.stdout + result.stderr)[-8000:]
        except (OSError, subprocess.TimeoutExpired) as error:
            success, output = False, str(error)
        self.logs.append({'service': service, 'command': command, 'success': success, 'output': output})
        return success

    def configured_encode(self, service, binary, backend, codec, render_node=None):
        """Exercise the actual file/preview preset after the basic encode probe."""
        fixture = shlex.join([binary, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                              '-i', 'testsrc2=size=1280x720:rate=30', '-f', 'lavfi', '-i',
                              'sine=frequency=1000:sample_rate=48000', '-t', '1',
                              '-c:v', 'mpeg2video', '-c:a', 'aac', '-f', 'mpegts'])
        prefix = ('d=$(mktemp -d); trap \'rm -rf "$d"\' EXIT; ' + fixture + ' "$d/input.ts"; ')
        if service == 'epgstation':
            preset = codec
            command = (prefix + 'script=/app/config/enc.js; '
                       'cp "$script" "$d/enc.js"; FFMPEG=' + shlex.quote(binary) + ' FFPROBE=ffprobe' +
                       ' HWENCODER_H264=' + shlex.quote({'qsv': 'h264_qsv', 'amf': 'h264_amf', 'nvenc': 'h264_nvenc', 'software': 'libx264'}.get(backend, '')) +
                       ' HWENCODER_HEVC=' + shlex.quote({'qsv': 'hevc_qsv', 'amf': 'hevc_amf', 'nvenc': 'hevc_nvenc', 'software': 'libx265'}.get(backend, '')) +
                       ' INPUT="$d/input.ts" OUTPUT="$d/output.mp4" VIDEORESOLUTION=720 '
                       'AUDIOCOMPONENTTYPE=1 node "$d/enc.js" ' + preset +
                       ' 720; test -s "$d/output.mp4"')
            return self.run(service, command)
        if service == 'recisdb-proxy' and codec == 'h264':
            preview = module('preview_profiles_probe', 'preview-profiles.py')
            commands = []
            for four_k in (False, True):
                args = preview.ffmpeg_args(preview.BACKENDS[backend], four_k, render_node)
                commands.append(shlex.quote(binary) + ' ' + args + ' < "$d/input.ts" > /dev/null')
            return self.run(service, prefix + '; '.join(commands))
        return True

    def ffmpeg(self, service, gpu, executable=None, render_node=None):
        binary = executable or FFMPEG[service]
        # EPGStation presets may still assume renderD128 at runtime.
        candidates = {'intel': ['qsv'] if service == 'epgstation' else ['qsv', 'vaapi'],
                      'amd': ['amf'] if service == 'epgstation' else ['amf', 'vaapi'],
                      'nvidia': ['nvenc'], 'none': []}[gpu] + ['software']
        for backend in candidates:
            if backend == 'vaapi' and render_node is None:
                continue
            if not self.run(service, shlex.join([binary, *ffmpeg_args(backend, 'h264', render_node or '/dev/null')])):
                continue
            if not self.configured_encode(service, binary, backend, 'h264', render_node or '/dev/null'):
                continue
            hevc = (self.run(service, shlex.join([binary, *ffmpeg_args(backend, 'hevc', render_node or '/dev/null')]))
                    and self.configured_encode(service, binary, backend, 'hevc', render_node or '/dev/null'))
            return {'backend': backend, 'h264': True, 'hevc': hevc, 'binary': binary}
        return {'backend': None, 'h264': False, 'hevc': False, 'binary': binary}

    def rigaya(self, service, gpu):
        binary = RIGAYA.get(gpu)
        if binary:
            if service == 'konomitv':
                binary = f'/code/server/thirdparty/{binary}/{binary}.elf'
            else:
                binary = binary.lower()
            for codec in ('h264', 'hevc'):
                # Generate 30 raw 720p frames without requiring a second FFmpeg.
                # The temporary output lives only in this disposable container.
                command = ('d=$(mktemp -d); trap \'rm -rf "$d"\' EXIT; '
                           'dd if=/dev/zero bs=1382400 count=30 2>/dev/null | ' +
                           shlex.join([binary, '--raw', '--input-res', '1280x720', '--fps', '30',
                                       '--codec', codec, '--vbr', '2000', '-i', '-']) +
                           f' -o "$d/probe.{codec}"; test -s "$d/probe.{codec}"')
                success = self.run(service, command)
                if codec == 'h264':
                    if not success:
                        break
                    result = {'backend': gpu, 'encoder': RIGAYA[gpu], 'h264': True, 'hevc': False}
                else:
                    result['hevc'] = success
                    return result
        if service == 'konomitv':
            result = self.ffmpeg(service, 'none')
            result['encoder'] = 'FFmpeg' if result['h264'] else None
            return result
        # Amatsukaze uses x264 rather than FFmpeg for software encoding.
        command = ('d=$(mktemp -d); trap \'rm -rf "$d"\' EXIT; '
                   'dd if=/dev/zero bs=1382400 count=30 2>/dev/null | '
                   'x264 --input-res 1280x720 --fps 30 --preset veryfast -o "$d/probe.h264" -; test -s "$d/probe.h264"')
        success = self.run(service, command)
        return {'backend': 'software' if success else None, 'encoder': 'x264' if success else None,
                'h264': success, 'hevc': False}


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def epg_preset(text, result, cores):
    backend = result['backend']
    # At most two hardware jobs; software leaves roughly half the CPU for receiving/UI.
    jobs = min(2, max(1, cores // 2)) if backend != 'software' else max(1, min(4, cores // 2))
    for key in ('encodeProcessNum', 'concurrentEncodeNum'):
        text = re.sub(rf'^{key}:.*$', f'{key}: {jobs}', text, flags=re.M)
    # EPGStation detects the runtime encoder and enc.js reads HWENCODER_*.
    hardware_encoder = {'qsv': 'qsv', 'amf': 'vce', 'nvenc': 'nvenc'}.get(backend, 'auto')
    if re.search(r'^hardwareEncoder\s*:', text, re.M):
        text = re.sub(r'^hardwareEncoder\s*:.*$', f'hardwareEncoder: {hardware_encoder}', text, flags=re.M)
    else:
        text += f'\nhardwareEncoder: {hardware_encoder}\n'
    # HEVC file encoding is offered only after its independent probe succeeds.
    if result['hevc']:
        hevc = (f'    - id: hevc-720p\n      name: HEVC\n'
                "      cmd: '%NODE% %ROOT%/config/enc.js hevc 720'\n"
                '      suffix: .mp4\n      rate: 14.0\n')
        if not re.search(r'^\s*- id: hevc-720p\s*$', text, re.M):
            encode_match = re.search(r'^encode:\s*$', text, re.M)
            if not encode_match:
                return text
            index = encode_match.end() + (1 if text[encode_match.end():].startswith('\n') else 0)
            text = text[:index] + hevc + text[index:]
    return text


def apply_files(root, env, results, cores):
    render = module('render_gpu_config', 'render-config.py')
    changed = []
    baseline_env = {key: value for key, value in env.items() if not key.startswith('GPU_')}
    for service in ('epgstation', 'konomitv', 'amatsukaze'):
        result = results.get(service, {})
        if not result.get('h264'):
            if result:
                result['configuration'] = 'probe-failed-preserved'
            continue
        spec = render.SERVICES[service]
        template = (root / spec['template']).read_text()
        baseline = render.render(service, template, baseline_env)
        if service == 'epgstation':
            new = epg_preset(baseline, result, cores)
        elif service == 'konomitv':
            new = re.sub(r"^(    encoder:).*", lambda m: m[1] + ' ' + json.dumps(result['encoder']), baseline, flags=re.M)
        else:
            encoder = {'intel': 'QSVEnc', 'amd': 'VCEEnc', 'nvidia': 'NVEnc', 'software': 'x264'}[result['backend']]
            new = baseline.replace('<EncoderType>x264</EncoderType>', f'<EncoderType>{encoder}</EncoderType>')
        path = root / spec['output']
        if replace_generated(root, path, new, baseline):
            changed.append(service)
        result['configuration'] = 'applied' if path.is_file() and path.read_text() == new else 'manual-preserved'
    return changed


def summarize(saved):
    print(f"GPU エンコード判定 ({saved['gpu']}):")
    for service, result in saved.get('services', {}).items():
        print(f"  {service}: {result.get('encoder') or result['backend'] or '失敗・設定維持'}; "
              f"H.264={result['h264']} HEVC={result['hevc']}; 設定={result.get('configuration', 'profiles参照')}")
        if service == 'recisdb-proxy' and isinstance(result.get('profiles'), dict):
            preview = module('preview_profiles_notice', 'preview-profiles.py')
            preview.print_activation_notice(result['profiles'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('detect', 'render-node', 'probe', 'summary'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--env', type=Path)
    parser.add_argument('--docker-bin', default=os.environ.get('DOCKER_BIN', 'docker'))
    parser.add_argument('--gpu', choices=('none', 'intel', 'amd', 'nvidia'), default='none')
    parser.add_argument('--sys-drm', type=Path, default=Path(os.environ.get('SYS_DRM_DIR', '/sys/class/drm')))
    parser.add_argument('--preview-only', action='store_true')
    args = parser.parse_args()
    if args.command == 'detect':
        print(detect(args.sys_drm))
        return
    if args.command == 'render-node':
        print(selected_render_node(args.gpu, args.sys_drm) or '')
        return
    root = args.root.resolve()
    if args.command == 'summary':
        try:
            saved = json.loads((root / 'config/gpu-probe.json').read_text())
            summarize(saved)
        except (OSError, ValueError):
            print('GPU 未プローブ: 通常セットアップまたは --reconfigure で実エンコード判定してください。')
        return
    render = module('render_gpu_config', 'render-config.py')
    env_file = args.env or root / '.env'
    env = render.read_env(env_file)
    if not env.get('COMPOSE_FILE'):
        parser.error('COMPOSE_FILE is required in the environment file')
    probe = Probe(root, env, args.docker_bin)
    render_node = selected_render_node(args.gpu, args.sys_drm)
    if render_node and render_node != '/dev/dri/renderD128':
        print(f'警告: 選択した GPU の render node は {render_node} です。EPGStation upstream の一部設定は renderD128 固定です。')
    results = {}
    if not args.preview_only:
        results['epgstation'] = probe.ffmpeg('epgstation', args.gpu, render_node=render_node)
        results['konomitv'] = probe.rigaya('konomitv', args.gpu)
        if render.amatsukaze_enabled(env):
            results['amatsukaze'] = probe.rigaya('amatsukaze', args.gpu)
    preview = module('preview_profiles_gpu', 'preview-profiles.py')
    try:
        config = preview.read_preview_config(root, env, args.docker_bin)
        binary = config.get('command_path', '')
        if binary and 'ffmpeg' in Path(binary).name.lower():
            results['recisdb-proxy'] = probe.ffmpeg('recisdb-proxy', args.gpu, binary, render_node)
            if results['recisdb-proxy']['h264']:
                report = preview.apply_profiles(root, env, args.docker_bin, results['recisdb-proxy']['backend'],
                                                render_node=render_node or '/dev/null', command_path=binary)
                results['recisdb-proxy']['profiles'] = report
                print('プレビュープロファイル: ' + json.dumps(report, ensure_ascii=False))
        else:
            print('recisdb-proxy: FFmpeg 自動セットアップ後に再判定します。')
    except (preview.ProfileError, sqlite3.Error, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'recisdb-proxy: プレビュー設定を維持 ({error})')
        result = results.setdefault('recisdb-proxy', {'backend': None, 'h264': False, 'hevc': False})
        result['configuration'] = 'preview-preserved'
        result['error'] = str(error)
    results.setdefault('recisdb-proxy', {'backend': None, 'h264': False, 'hevc': False,
                                        'configuration': 'preview-unavailable'})
    changed = apply_files(root, env, results, os.cpu_count() or 1)
    state = root / 'config/gpu-probe.json'
    saved = {}
    if state.is_file() and args.preview_only:
        try:
            old = json.loads(state.read_text())
            if old.get('gpu') == args.gpu:
                saved = old
        except (ValueError, OSError):
            pass
    previous = saved.get('services', {})
    previous.update(results)
    logs_path = root / 'config/gpu-probe-log.json'
    logs = []
    if saved and logs_path.is_file():
        try:
            logs = json.loads(logs_path.read_text())
            if not isinstance(logs, list):
                logs = []
        except (ValueError, OSError):
            pass
    logs_path.write_text(json.dumps(logs + probe.logs, ensure_ascii=False, indent=2) + '\n')
    logs_path.chmod(0o600)
    saved = {'gpu': args.gpu, 'probed_at': datetime.now(timezone.utc).isoformat(), 'services': previous}
    state.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + '\n')
    state.chmod(0o600)
    summarize(saved)
    if changed:
        print('反映に必要な起動/再起動: docker compose up -d --force-recreate ' + ' '.join(changed))


if __name__ == '__main__':
    main()
