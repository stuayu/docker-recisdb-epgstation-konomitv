#!/bin/sh
set -eu
# Settings are created on the host by setup.sh (config/recisdb-proxy/recisdb-proxy.toml) and bind-mounted here.
# The file is never regenerated at container start, so user edits survive restarts.
config=/data/recisdb-proxy.toml
if [ ! -f "$config" ]; then
  echo "[recisdb-proxy] $config がありません。setup.sh を実行してください (または make regen-config SERVICE=recisdb-proxy)。" >&2
  exit 1
fi
cd /data
exec recisdb-proxy --config "$config" --database /data/recisdb-proxy.db --log-dir /data/logs
