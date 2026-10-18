#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# EpgTimerSrv loads ChSet at startup. Never replace it under a running recorder.
docker compose stop edcb
trap 'docker compose up -d --no-deps edcb' EXIT
trap 'exit 1' HUP INT TERM
docker compose run --rm --no-deps edcb edcb-chset
