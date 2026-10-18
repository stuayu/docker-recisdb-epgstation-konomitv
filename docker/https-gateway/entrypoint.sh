#!/bin/sh
set -eu

AKEBI_ROUTES=${AKEBI_ROUTES:-}
AKEBI_KEYLESS_SERVER_URL=${AKEBI_KEYLESS_SERVER_URL:-https://akebi.konomi.tv/}
AKEBI_BIN=${AKEBI_BIN:-/usr/local/bin/akebi-https-server}
AKEBI_LISTEN_HOST=${AKEBI_LISTEN_HOST:-0.0.0.0}

if [ -z "$AKEBI_ROUTES" ]; then
    echo '[https-gateway] AKEBI_ROUTES is empty' >&2
    exit 2
fi

children=''
markers=''
stopping=0
state_dir=${TMPDIR:-/tmp}/akebi-gateway-$$
umask 077
mkdir "$state_dir" || { echo '[https-gateway] cannot create state directory' >&2; exit 1; }

stop_children() {
    stopping=1
    # Signal the Akebi processes themselves; the route subshells only wait on them.
    for pidfile in "$state_dir"/*.pid; do
        [ -f "$pidfile" ] && kill -TERM "$(cat "$pidfile")" 2>/dev/null || true
    done
    for pid in $children; do kill -TERM "$pid" 2>/dev/null || true; done
    for pid in $children; do wait "$pid" 2>/dev/null || true; done
    rm -rf "$state_dir"
}
trap 'stop_children; exit 0' INT TERM HUP

start_route() {
    route=$1
    case $route in
        *=*) port=${route%%=*}; target=${route#*=} ;;
        *) echo "[https-gateway] invalid route '$route': expected PORT=URL" >&2; exit 2 ;;
    esac
    case $port in ''|*[!0-9]*) echo "[https-gateway] invalid port in route '$route'" >&2; exit 2;; esac
    if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
        echo "[https-gateway] port out of range in route '$route'" >&2
        exit 2
    fi
    case $target in http://*|https://*) ;; *) echo "[https-gateway] invalid target in route '$route': expected http(s) URL" >&2; exit 2;; esac
    case $target in http://*/|https://*/) ;; *) echo "[https-gateway] target must end with '/': '$target'" >&2; exit 2;; esac

    marker=$state_dir/$port.done
    markers="$markers $marker"
    (
        set +e
        # sh has no pipefail: record Akebi's own exit status, not sed's.
        {
            "$AKEBI_BIN" --listen-address "$AKEBI_LISTEN_HOST:$port" \
                --proxy-pass-url "$target" --keyless-server-url "$AKEBI_KEYLESS_SERVER_URL" 2>&1 &
            printf '%s\n' "$!" > "$state_dir/$port.pid"
            wait "$!"
            printf '%s\n' "$?" > "$marker"
        } | sed -u "s/^/[akebi:$port] /"
    ) &
    children="$children $!"
    echo "[https-gateway] started port=$port target=$target pid=$!"
}

old_ifs=$IFS
IFS=' 	
'
set -f
for route in $AKEBI_ROUTES; do
    case $route in
        *=*) port=${route%%=*}; target=${route#*=} ;;
        *) echo "[https-gateway] invalid route '$route': expected PORT=URL" >&2; exit 2 ;;
    esac
    case $port in ''|*[!0-9]*) echo "[https-gateway] invalid port in route '$route'" >&2; exit 2;; esac
    if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then echo "[https-gateway] port out of range in route '$route'" >&2; exit 2; fi
    case $target in http://*|https://*) ;; *) echo "[https-gateway] invalid target in route '$route': expected http(s) URL" >&2; exit 2;; esac
    case $target in http://*/|https://*/) ;; *) echo "[https-gateway] target must end with '/': '$target'" >&2; exit 2;; esac
done
for route in $AKEBI_ROUTES; do start_route "$route"; done
IFS=$old_ifs
set +f

while [ "$stopping" -eq 0 ]; do
    for marker in $markers; do
        if [ -f "$marker" ]; then
            status=$(cat "$marker")
            echo "[https-gateway] Akebi process exited (status=$status); stopping all routes" >&2
            stop_children
            exit 1
        fi
    done
    sleep 1
done
