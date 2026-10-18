#!/bin/bash
set -Eeuo pipefail
runtime=${BONCAS_RUNTIME_SCRIPT:-/opt/boncasrelay/runtime.py}
usb_snapshot(){ python3 "$runtime" readers; }
monitor=1
if [[ ! -d ${USB_DEV_ROOT:-/dev/bus/usb} ]]; then
  echo '[boncasrelay] /dev/bus/usb がありません。USB 監視を無効化して起動します。' >&2
  monitor=0
fi
python3 "$runtime" acl /config/boncasrelay.ini /run/boncasrelay.ini
initial_usb=$(usb_snapshot)
pcscd --foreground &
pcsc_pid=$!
for _ in {1..50}; do
  [[ ! -S ${PCSC_SOCKET:-/run/pcscd/pcscd.comm} ]] || break
  kill -0 "$pcsc_pid" 2>/dev/null || { wait "$pcsc_pid"; exit 1; }
  sleep 0.1
done
boncasrelay --config /run/boncasrelay.ini &
relay_pid=$!
# Host udev multicast is not guaranteed in a container network namespace.
# Watch only CCID interfaces; unrelated USB changes must not interrupt decryption.
(
  while sleep 2; do
    if ((monitor)) && [[ $(usb_snapshot) != "$initial_usb" ]]; then
      echo '[boncasrelay] CCID reader set changed; restarting for reader discovery' >&2
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
while kill -0 "$pcsc_pid" 2>/dev/null && kill -0 "$relay_pid" 2>/dev/null && kill -0 "$watch_pid" 2>/dev/null; do
  sleep 0.2
done
exit 1
