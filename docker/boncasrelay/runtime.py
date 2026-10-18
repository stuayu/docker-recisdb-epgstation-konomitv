"""Discover CCID devices and render a runtime ACL from connected IPv4 routes."""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def readers(sysfs):
    result = set()
    for interface in sysfs.glob('*/bInterfaceClass'):
        try:
            if int(interface.read_text().strip(), 16) != 0x0b:
                continue
            device = interface.parent.resolve().parent
            bus = int((device / 'busnum').read_text())
            number = int((device / 'devnum').read_text())
            result.add(f'{bus:03}/{number:03}')
        except (OSError, ValueError):
            continue
    return sorted(result)


def render_acl(text, routes):
    subnets = sorted({str(ipaddress.ip_network(route['dst'], strict=False))
                      for route in routes if route.get('scope') == 'link'
                      and route.get('dst') != 'default' and route.get('dev') != 'lo'})
    if not subnets:
        raise ValueError('Compose ネットワークの接続済みサブネットを取得できません')
    # Recognize the previous generated default too, preserving custom ACLs.
    return re.sub(r'^Allow=(?:@compose-subnets@|172\.30\.69\.0/24)\s*$',
                  '\n'.join('Allow=' + subnet for subnet in subnets), text, flags=re.M)


if __name__ == '__main__':
    if sys.argv[1] == 'readers':
        print('\n'.join(readers(Path(os.environ.get('USB_SYSFS', '/sys/bus/usb/devices')))))
    else:
        routes = json.loads(subprocess.check_output(['ip', '-j', '-4', 'route', 'show'], text=True))
        Path(sys.argv[3]).write_text(render_acl(Path(sys.argv[2]).read_text(), routes))
