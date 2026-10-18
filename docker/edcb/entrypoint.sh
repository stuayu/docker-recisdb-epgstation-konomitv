#!/bin/sh
set -eu
stack=${EDCB_STACK:-/opt/edcb-stack}
root=${EDCB_ROOT:-/var/local/edcb}
case ${RUN_UID:-1000}:${RUN_GID:-1000} in *[!0-9:]*|:*|*:) echo 'RUN_UID/RUN_GID must be numeric' >&2; exit 2;; esac
[ "${RUN_UID:-1000}" -gt 0 ] && [ "${RUN_GID:-1000}" -gt 0 ] || exit 2
python3 "$stack/configure.py"
if [ "${1:-}" = edcb-chset ]; then
    python3 "$stack/chset.py" --refresh
else
    python3 "$stack/chset.py" || echo '[edcb] ChSet 未取得。スキャン後 make edcb-chset を実行してください。' >&2
fi
if [ "$(id -u)" = 0 ]; then
    chown -R "${RUN_UID:-1000}:${RUN_GID:-1000}" "$root" "${EDCB_CONFIG_DIR:-$root}"
    # Only this stack's new recording subdirectory, never existing recordings.
    chown "${RUN_UID:-1000}:${RUN_GID:-1000}" "${EDCB_RECORDED:-/recorded/edcb}"
fi
# chset.py replaces files atomically in config/; expose newly created files too.
python3 "$stack/configure.py"
[ "${1:-}" != edcb-chset ] || exit 0
cd "$root"
if [ "$(id -u)" = 0 ]; then exec gosu "${RUN_UID:-1000}:${RUN_GID:-1000}" "$@"; fi
exec "$@"
