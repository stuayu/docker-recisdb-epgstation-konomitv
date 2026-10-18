"""Apply checked compatibility changes to the externally fetched BonDriver."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
p = root / 'src/BonDriver_LinuxMirakc.cpp'
s = p.read_text(encoding='utf-8-sig')
# The upstream has fixed-size URL buffers and assumes mirakc's object channel.
for old, new, count in [
    ('"/api/', '"/mirakurun/api/', 3),
    ('const int len = 14;', 'const int len = 256;', 1),
    ('channel_obj["channel"].get<picojson::object>()',
     'channel_obj["channel"].get<picojson::array>().front().get<picojson::object>()', 1),
]:
    if s.count(old) != count:
        raise SystemExit(f'BonDriver upstream changed: expected {count} occurrences of {old}')
    s = s.replace(old, new)
p.write_text(s)
p = root / 'src/BonDriver_LinuxMirakc.hpp'
s = p.read_text(encoding='utf-8-sig')
assert s.count('#define SPACE_NUM 8') == 1
p.write_text(s.replace('#define SPACE_NUM 8', '#define SPACE_NUM 64'))
p = root / 'src/http_proc.hpp'
s = p.read_text()
old = 's_addr.sin_addr.s_addr = inet_addr( host );'
assert s.count(old) == 1
s = s.replace(old, '''struct addrinfo hints = {}, *resolved = nullptr;
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, nullptr, &hints, &resolved) == 0) {
        s_addr.sin_addr = ((struct sockaddr_in *)resolved->ai_addr)->sin_addr;
        freeaddrinfo(resolved);
    } else {
        s_addr.sin_addr.s_addr = INADDR_NONE;
    }''')
assert s.count('::shutdown(s, SHUT_WR)') == 1
s = s.replace('::shutdown(s, SHUT_WR)', '::shutdown(s, SHUT_RDWR)')
p.write_text(s)
