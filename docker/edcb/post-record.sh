#!/bin/sh
# EDCB Unix always passes direct environment macros with ISO8601 dates.
set -eu
exec python3 /opt/edcb-stack/post-record.py "$@"
