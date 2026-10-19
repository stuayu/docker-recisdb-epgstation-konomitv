#!/bin/sh
# Official Node.js 24 binaries; SHA256 from nodejs.org/dist/v24.22.0/SHASUMS256.txt.
set -eu
version=24.22.0
case "$(dpkg --print-architecture)" in
  amd64) arch=x64; sha=cc2f601cee82d9a5a233302fe307abc600727035fd7d2c3a3571755989e95008 ;;
  arm64) arch=arm64; sha=fef00bb4d36e1c50104a9775a10359beee98f162b4104dd12472c75065c6a143 ;;
  *) echo 'Unsupported Node.js architecture' >&2; exit 1 ;;
esac
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl xz-utils libatomic1 libstdc++6
curl -fsSL --retry 3 "https://nodejs.org/dist/v${version}/node-v${version}-linux-${arch}.tar.xz" -o /tmp/node.tar.xz
printf '%s  %s\n' "$sha" /tmp/node.tar.xz | sha256sum -c -
tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1
rm /tmp/node.tar.xz
node --version
npm --version
rm -rf /var/lib/apt/lists/*
