#!/bin/sh
set -eu

script_dir=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
dev_dir=${DEV_DIR:-/dev}
output=${TUNERS_COMPOSE_FILE:-"$script_dir/compose.tuners.yaml"}
tmp_file=${output}.tmp
count=0
env_file=${ENV_FILE:-"$script_dir/.env"}
if [ "${TUNER_EXCLUDE+x}" != x ]; then
  TUNER_EXCLUDE=$(sed -n 's/^TUNER_EXCLUDE=//p' "$env_file" 2>/dev/null | tail -n1 || true)
fi
tuner_gids=''
render_gid=''

trap 'rm -f "$tmp_file"' EXIT HUP INT TERM
mkdir -p "$(dirname "$output")"
{
  printf 'services:\n  recisdb-proxy:\n    devices:\n'

  add_device() {
    source_path=$1
    excluded=0
    old_ifs=$IFS; IFS=,
    for excluded_pattern in $TUNER_EXCLUDE; do
      [ -n "$excluded_pattern" ] || continue
      # shellcheck disable=SC2254
      case $source_path in $excluded_pattern) excluded=1;; esac
      case $source_path in "$dev_dir"/dvb/adapter[0-9]*/*)
        adapter_path=${source_path%/*}
        # shellcheck disable=SC2254
        case $adapter_path in $excluded_pattern) excluded=1;; esac
      esac
    done
    IFS=$old_ifs
    [ "$excluded" -eq 0 ] || return 0
    target_path=${source_path#"$dev_dir"}
    target_path=/dev$target_path
    printf '      - "%s:%s"\n' "$source_path" "$target_path"
    gid=$(stat -c '%g' "$source_path" 2>/dev/null || true)
    case $gid in ''|*[!0-9]*) ;; *)
      case ,$tuner_gids, in *,$gid,*) ;; *) tuner_gids=${tuner_gids:+$tuner_gids,}$gid;; esac
    esac
    count=$((count + 1))
  }

  for name_pattern in px4video\* pt3video\* pxmlt\*video\* pxm1urvideo\* pxs1urvideo\* isdbt2071video\* isdb2056video\*; do
    for device_path in "$dev_dir"/$name_pattern; do
      [ -e "$device_path" ] || continue
      [ -d "$device_path" ] && continue
      add_device "$device_path"
    done
  done

  for adapter_dir in "$dev_dir"/dvb/adapter[0-9]*; do
    [ -d "$adapter_dir" ] || continue
    for node_path in "$adapter_dir"/frontend[0-9]* "$adapter_dir"/demux[0-9]* "$adapter_dir"/dvr[0-9]*; do
      [ -e "$node_path" ] || continue
      [ -d "$node_path" ] && continue
      add_device "$node_path"
    done
  done
} > "$tmp_file"

if [ "$count" -eq 0 ]; then
  tuner_gids=$(getent group video 2>/dev/null | awk -F: 'NR == 1 {print $3}' || true)
  case $tuner_gids in ''|*[!0-9]*) tuner_gids=44;; esac
  printf 'services:\n  recisdb-proxy:\n    devices: []\n' > "$tmp_file"
fi
if [ -z "$tuner_gids" ]; then
  tuner_gids=$(getent group video 2>/dev/null | awk -F: 'NR == 1 {print $3}' || true)
  case $tuner_gids in ''|*[!0-9]*) tuner_gids=44;; esac
fi
printf '    group_add:\n' >> "$tmp_file"
old_ifs=$IFS; IFS=,
for gid in $tuner_gids; do printf '      - "%s"\n' "$gid" >> "$tmp_file"; done
IFS=$old_ifs
for render_node in "$dev_dir"/dri/renderD*; do
  [ -e "$render_node" ] || continue
  render_gid=$(stat -c '%g' "$render_node" 2>/dev/null || true)
  case $render_gid in ''|*[!0-9]*) render_gid='';; esac
  [ -z "$render_gid" ] || break
done
if [ -z "$render_gid" ]; then
  render_gid=$(getent group render 2>/dev/null | awk -F: 'NR == 1 {print $3}' || true)
fi
case $render_gid in ''|*[!0-9]*) render_gid='';; esac

mv "$tmp_file" "$output"
trap - EXIT HUP INT TERM
if [ -f "$env_file" ]; then
  COMPOSE_FILE=${COMPOSE_FILE:-} python3 - "$env_file" "$tuner_gids" "$render_gid" <<'PYENV'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
gids = sys.argv[2]
render_gid = sys.argv[3]
lines = path.read_text().splitlines()
values = dict(line.split('=', 1) for line in lines if '=' in line and not line.lstrip().startswith('#'))
legacy_video = ('GPU' not in values and 'compose.intel.yaml' in values.get('COMPOSE_FILE', ''))
if not render_gid:
    if legacy_video:
        render_gid = values.get('VIDEO_GID', values.get('RENDER_GID', '110'))
    else:
        render_gid = values.get('RENDER_GID', '110')
updates = {'TUNER_GIDS': gids, 'RENDER_GID': render_gid}
# VIDEO_GID is a distinct AMD video/kfd group in current setups. Only retire
# the old Intel alias when this is still an unmigrated (GPU key absent) env.
lines = [line for line in lines if line.split('=', 1)[0] not in updates
         and not (legacy_video and line.startswith('VIDEO_GID='))]
lines.extend(key + '=' + value for key, value in updates.items())
path.write_text('\n'.join(lines) + '\n')
PYENV
  chmod 600 "$env_file"
fi
printf 'Wrote %s (%s device nodes)\n' "$output" "$count"
