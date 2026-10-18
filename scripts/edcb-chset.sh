#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# EpgTimerSrv loads ChSet at startup. Never replace it under a running recorder.
docker_cmd=${DOCKER_BIN:-docker}
"$docker_cmd" compose stop edcb
finish() {
  result=$?
  trap - EXIT
  "$docker_cmd" compose up -d --no-deps edcb || result=1
  exit "$result"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
if [ -n "${EDCB_TUNER_COUNT:-}" ]; then
  python3 scripts/tuner-setup.py edcb-count
fi
"$docker_cmd" compose run --rm --no-deps edcb edcb-chset
