#!/bin/sh
set -eu
app_root=${EPGSTATION_APP_ROOT:-/app}
template=${EPGSTATION_CONFIG_TEMPLATE:-/config-template/config.yml}
AMATSUKAZE_ENCODE=''
AMATSUKAZE_CONFIG=''
if [ "${AMATSUKAZE_ENABLED:-0}" = 1 ]; then
  # YAML text, not a shell command.
  # shellcheck disable=SC2089
  AMATSUKAZE_ENCODE="    - id: amatsukaze
      name: Amatsukaze
      cmd: '%NODE% %ROOT%/dist/AmatsukazeEncodeTool.js EPGStation'
      suffix: .mp4
      rate: 12.0"
  AMATSUKAZE_CONFIG='amatsukaze:
    host: amatsukaze
    port: 32768
    addTaskPath: /opt/amatsukaze/AmatsukazeAddTask
    profile: EPGStation
    priority: 3
    noMove: true
    connectTimeoutMs: 60000
    taskTimeoutMs: 0
    pathMappings: []'
fi
# shellcheck disable=SC2090
export AMATSUKAZE_ENCODE AMATSUKAZE_CONFIG
mkdir -p "$app_root/config"
# Keep substitution restricted so EPGStation percent placeholders remain intact.
# shellcheck disable=SC2016
envsubst '${MARIADB_PASSWORD} ${AMATSUKAZE_ENCODE} ${AMATSUKAZE_CONFIG}' < "$template" > "$app_root/config/config.yml"
mkdir -p "$app_root/data/tmp" "$app_root/logs/Operator" "$app_root/logs/Service" "$app_root/logs/EPGUpdater"

for name in operatorLogConfig serviceLogConfig epgUpdaterLogConfig; do
  if [ ! -f "$app_root/config/${name}.yml" ]; then
    cp "$app_root/config/${name}.sample.yml" "$app_root/config/${name}.yml"
  fi
done

if [ "${AMATSUKAZE_ENABLED:-0}" = 1 ]; then
  case ${RUN_UID:-}:${RUN_GID:-} in *[!0-9:]*|:*|*:) echo 'RUN_UID and RUN_GID must be numeric' >&2; exit 2;; esac
  # Repair application state created by previous root runs; never chown /recorded.
  if [ "$(id -u)" = 0 ]; then
    chown -R "$RUN_UID:$RUN_GID" "$app_root/config" "$app_root/data" "$app_root/logs" "$app_root/thumbnail" "$app_root/drop"
    cd "$app_root"
    if [ "$#" -gt 0 ]; then exec gosu "$RUN_UID:$RUN_GID" "$@"; fi
    exec gosu "$RUN_UID:$RUN_GID" npm start
  fi
fi
cd "$app_root"
if [ "$#" -gt 0 ]; then exec "$@"; fi
exec npm start
