#!/bin/sh
set -eu
if [ -z "${BONCAS_B25_HOST:-}" ]; then
  echo "BONCAS_B25_HOST is required" >&2
  exit 1
fi

envsubst '${BONCAS_B25_HOST} ${BONCAS_B25_PORT} ${BONCAS_4K_HOST} ${BONCAS_4K_PORT}' \
  < /config/recisdb-proxy.toml.example > /data/recisdb-proxy.toml.tmp
if [ -n "${BONCAS_4K_HOST:-}" ]; then
  mv /data/recisdb-proxy.toml.tmp /data/recisdb-proxy.toml
else
  sed '/^\[mmttlv\]$/,/^\[/ { /^\[mmttlv\]$/d; /^boncaslink_server[[:space:]]*=/d; }' \
    /data/recisdb-proxy.toml.tmp > /data/recisdb-proxy.toml
  rm /data/recisdb-proxy.toml.tmp
fi
cd /data
exec recisdb-proxy --config /data/recisdb-proxy.toml --database /data/recisdb-proxy.db --log-dir /data/logs
