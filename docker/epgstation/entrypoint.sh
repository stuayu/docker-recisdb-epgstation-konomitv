#!/bin/sh
set -eu
envsubst '${MARIADB_PASSWORD}' < /config-template/config.yml > /app/config/config.yml
mkdir -p /app/data/tmp /app/logs/Operator /app/logs/Service /app/logs/EPGUpdater

for name in operatorLogConfig serviceLogConfig epgUpdaterLogConfig; do
  if [ ! -f "/app/config/${name}.yml" ]; then
    cp "/app/config/${name}.sample.yml" "/app/config/${name}.yml"
  fi
done

exec npm start
