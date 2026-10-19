#!/bin/sh
# Build Rust code against noble's libc/OpenSSL rather than copying Debian binaries.
set -eu
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl build-essential
curl --proto '=https' --tlsv1.2 -fsSL --retry 3 https://sh.rustup.rs -o /tmp/rustup-init.sh
sh /tmp/rustup-init.sh -y --profile minimal --default-toolchain 1.99.1
rm /tmp/rustup-init.sh
rm -rf /var/lib/apt/lists/*
