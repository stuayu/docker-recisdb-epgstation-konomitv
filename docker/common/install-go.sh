#!/bin/sh
# Official Go archives; hashes from https://go.dev/dl/?mode=json&include=all.
set -eu
version=1.24.13
case "$(dpkg --print-architecture)" in
  amd64) sha=1fc94b57134d51669c72173ad5d49fd62afb0f1db9bf3f798fd98ee423f8d730 ;;
  arm64) sha=74d97be1cc3a474129590c67ebf748a96e72d9f3a2b6fef3ed3275de591d49b3 ;;
  *) echo 'Unsupported Go architecture' >&2; exit 1 ;;
esac
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git
curl -fsSL --retry 3 "https://go.dev/dl/go${version}.linux-$(dpkg --print-architecture).tar.gz" -o /tmp/go.tar.gz
printf '%s  %s\n' "$sha" /tmp/go.tar.gz | sha256sum -c -
tar -xzf /tmp/go.tar.gz -C /usr/local
rm /tmp/go.tar.gz
/usr/local/go/bin/go version
rm -rf /var/lib/apt/lists/*
