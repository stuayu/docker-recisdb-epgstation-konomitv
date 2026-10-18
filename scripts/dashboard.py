"""Generate the disposable EDCB dashboard configuration from selected services."""
import json
import os
from pathlib import Path
import subprocess
import tempfile


def detect_host():
    """Use setup's route source, then hostname -I, then localhost fallback."""
    def output(command):
        try:
            return subprocess.run(command, capture_output=True, text=True, check=False).stdout.split()
        except FileNotFoundError:
            return []

    route = output(['ip', '-4', 'route', 'get', '1.1.1.1'])
    if 'src' in route and route.index('src') + 1 < len(route):
        return route[route.index('src') + 1]
    addresses = output(['hostname', '-I'])
    return addresses[0] if addresses else 'localhost'


def configuration(env, host):
    compose = env.get('COMPOSE_FILE', 'compose.yaml').split(':')
    https = 'compose.https.yaml' in compose

    def port(key, default):
        value = int(env.get(key) or default)
        if not 1 <= value <= 65535:
            raise ValueError(f'{key} must be 1..65535')
        return value

    services = []

    def add(id_, name, role, http=None, tls=None, path='/'):
        item = {'id': id_, 'name': name, 'role': role, 'path': path}
        if http:
            item['http'] = port(*http)
        if tls and https:
            item['https'] = port(*tls)
        services.append(item)

    if 'compose.yaml' in compose:
        add('epgstation', 'EPGStation', '録画予約・録画一覧・視聴',
            ('EPGSTATION_PORT', 8888), ('EPGSTATION_HTTPS_PORT', 8443))
        # KonomiTV has no published plain-HTTP endpoint. Do not invent one when
        # HTTPS links are disabled; its built-in Akebi still runs independently.
        if https:
            add('konomitv', 'KonomiTV', 'ライブ視聴・録画再生', tls=('KONOMITV_PORT', 7000))
    edcb = 'compose.edcb.yaml' in compose
    if edcb:
        add('edcb', 'EDCB', '番組表・録画予約 (EMWUI)', ('EDCB_WEB_PORT', 5510),
            ('EDCB_HTTPS_PORT', 8553) if 'compose.edcb.https.yaml' in compose else None, '/E3/')
    if 'compose.yaml' in compose:
        add('recisdb', 'recisdb-proxy', 'チューナー・チャンネル管理',
            ('RECISDB_WEB_PORT', 40080), ('RECISDB_HTTPS_PORT', 40443))
    if 'compose.amatsukaze.yaml' in compose:
        add('amatsukaze', 'Amatsukaze', 'CM カット・エンコード', ('AMATSUKAZE_WEBUI_PORT', 32769))
    if env.get('BONCAS_MODE') == 'local' and 'compose.boncasrelay.yaml' in compose:
        services.append({'id': 'boncasrelay', 'name': 'BonCasRelay', 'role': 'B-CAS カードリーダー中継',
                         'local': f'http://127.0.0.1:{port("BONCASRELAY_WEB_PORT", 6980)}/',
                         'note': 'カードを挿したマシン上でのみ開けます'})
    title = env.get('DASHBOARD_TITLE') or '録画サーバー'
    if not title.strip():
        raise ValueError('DASHBOARD_TITLE must not be blank')
    return {'title': title, 'host': host,
            'httpsHost': host.replace('.', '-') + '.local.konomi.tv' if https else None,
            'services': services, 'edcb': {'api': edcb}}


def generate(root, env):
    if 'compose.edcb.yaml' not in env.get('COMPOSE_FILE', '').split(':'):
        return
    path = Path(root) / 'data/edcb/dashboard.json'
    body = json.dumps(configuration(env, os.environ.get('DASHBOARD_HOST') or detect_host()),
                      ensure_ascii=False, indent=2) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    # The public symlink follows each atomic replacement, including while EDCB runs.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(body)
            file.flush()
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    print('再生成: data/edcb/dashboard.json (.env から生成する派生データ)')


if __name__ == '__main__':
    print(detect_host())
