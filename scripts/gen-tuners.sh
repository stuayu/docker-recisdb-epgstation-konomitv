#!/bin/sh
set -eu

script_dir=$(CDPATH='' cd "$(dirname "$0")/.." && pwd)
dev_dir=${DEV_DIR:-/dev}
output=${TUNERS_COMPOSE_FILE:-"$script_dir/compose.tuners.yaml"}
tmp_file=${output}.tmp
count=0

trap 'rm -f "$tmp_file"' EXIT HUP INT TERM
mkdir -p "$(dirname "$output")"
{
  printf 'services:\n  recisdb-proxy:\n    devices:\n'

  add_device() {
    source_path=$1
    target_path=${source_path#"$dev_dir"}
    target_path=/dev$target_path
    printf '      - "%s:%s"\n' "$source_path" "$target_path"
    count=$((count + 1))
  }

  for name_pattern in px4video\* pt3video\* pxmlt5video\* isdb2056video\*; do
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
  printf 'services:\n  recisdb-proxy:\n    devices: []\n' > "$tmp_file"
fi

mv "$tmp_file" "$output"
trap - EXIT HUP INT TERM
printf 'Wrote %s (%s device nodes)\n' "$output" "$count"
