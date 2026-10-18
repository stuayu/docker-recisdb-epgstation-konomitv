"""Install dashboard assets and maintain EDCB's additional MIME mappings."""
from pathlib import Path
import shutil
import sys

MIME_TYPES = {'.woff2': 'font/woff2', '.woff': 'font/woff'}


def update_mime(path):
    text = path.read_text(encoding='utf-8-sig') if path.exists() else ''
    lines = [line for line in text.splitlines() if line.split('\t', 1)[0] not in MIME_TYPES]
    lines.extend(f'{extension}\t{mime}' for extension, mime in MIME_TYPES.items())
    updated = '\n'.join(lines) + '\n'
    if updated != text:
        path.write_text(updated, encoding='utf-8')


def wrap_html(html):
    equals = '='
    while f']{equals}]' in html:
        equals += '='
    # Lua ignores the first newline after a long-string opener; preserve HTML bytes.
    body = f'[{equals}[\n{html}]{equals}]'
    template = Path(__file__).with_name('dashboard-index.lua').read_text(encoding='utf-8')
    return template.replace('__DASHBOARD_BODY__', body)


def install(dist, root):
    public = root / 'HttpPublic'
    # Keep the standard top at the root so its relative subdirectory links still work.
    shutil.copy2(public / 'index.html', public / 'server.html')
    legacy = public / 'legacy/index.html'
    text = legacy.read_text(encoding='utf-8')
    marker = '  <ul>'
    if marker not in text:
        raise ValueError('EDCB legacy menu changed: cannot insert standard-top link')
    legacy.write_text(text.replace(marker, marker + '\n    <li><a href="../server.html">HTTPサーバー標準トップ</a></li>', 1), encoding='utf-8')
    shutil.copytree(dist / 'dash-assets', public / 'dash-assets', dirs_exist_ok=True)
    (public / 'index.html').write_text(wrap_html((dist / 'index.html').read_text(encoding='utf-8')), encoding='utf-8')
    update_mime(root / 'ContentTypeText.txt')


if __name__ == '__main__':
    install(*map(Path, sys.argv[1:]))
