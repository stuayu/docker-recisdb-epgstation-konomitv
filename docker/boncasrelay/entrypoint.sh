#!/bin/bash
set -Eeuo pipefail
usb_snapshot(){ find /dev/bus/usb -mindepth 2 -maxdepth 2 -printf '%p:%i\n' | sort; }
initial_usb=$(usb_snapshot)
pcscd --foreground &
pcsc_pid=$!
for _ in {1..50}; do
  [[ ! -S /run/pcscd/pcscd.comm ]] || break
  kill -0 "$pcsc_pid" 2>/dev/null || { wait "$pcsc_pid"; exit 1; }
  sleep 0.1
done
boncasrelay --config /config/boncasrelay.ini &
relay_pid=$!
# Host udev multicast is not guaranteed in a container network namespace.
# Restart the pair after a node change so pcscd scans the current USB tree.
(
  while sleep 2; do
    if [[ $(usb_snapshot) != "$initial_usb" ]]; then
      echo '[boncasrelay] USB device tree changed; restarting for reader discovery' >&2
      exit 1
    fi
  done
) &
watch_pid=$!
# shellcheck disable=SC2329
cleanup(){ kill "$pcsc_pid" "$relay_pid" "$watch_pid" 2>/dev/null || true; wait "$pcsc_pid" "$relay_pid" "$watch_pid" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 0' TERM INT
# Both processes must remain alive. tini forwards shutdown; reap both children.
wait -n "$pcsc_pid" "$relay_pid" "$watch_pid"
exit 1
