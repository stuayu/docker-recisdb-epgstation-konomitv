#!/bin/sh
set -eu
app_root=${EPGSTATION_APP_ROOT:-/app}
# config.yml is created on the host by setup.sh (config/epgstation/config.yml) and bind-mounted.
# It is never regenerated at container start, so user edits survive restarts.
config="$app_root/config/config.yml"
if [ ! -f "$config" ]; then
  echo "[epgstation] $config がありません。setup.sh を実行するか make regen-config SERVICE=epgstation を実行してください。" >&2
  exit 1
fi
mkdir -p "$app_root/data/tmp" "$app_root/logs/Operator" "$app_root/logs/Service" "$app_root/logs/EPGUpdater"

for name in operatorLogConfig serviceLogConfig epgUpdaterLogConfig; do
  if [ ! -f "$app_root/config/${name}.yml" ]; then
    cp "$app_root/config/${name}.sample.yml" "$app_root/config/${name}.yml"
  fi
done

if [ "${AMATSUKAZE_ENABLED:-0}" = 1 ]; then
  case ${RUN_UID:-}:${RUN_GID:-} in *[!0-9:]*|:*|*:) echo 'RUN_UID and RUN_GID must be numeric' >&2; exit 2;; esac
  # Repair application state created by previous root runs; never chown /recorded or the host config.yml.
  if [ "$(id -u)" = 0 ]; then
    find "$app_root/config" -mindepth 1 -maxdepth 1 ! -name config.yml -exec chown -R "$RUN_UID:$RUN_GID" {} +
    chown -R "$RUN_UID:$RUN_GID" "$app_root/data" "$app_root/logs" "$app_root/thumbnail" "$app_root/drop"
    if ! gosu "$RUN_UID:$RUN_GID" test -r "$config"; then
      echo "[epgstation] $config を UID=$RUN_UID GID=$RUN_GID で読めません。ホストの所有者・権限を合わせてください (setup.sh の RUN_UID/RUN_GID と一致させます)。" >&2
      exit 1
    fi
    cd "$app_root"
    if [ "$#" -gt 0 ]; then exec gosu "$RUN_UID:$RUN_GID" "$@"; fi
    exec gosu "$RUN_UID:$RUN_GID" npm start
  fi
fi
cd "$app_root"
if [ "$#" -gt 0 ]; then exec "$@"; fi
exec npm start
