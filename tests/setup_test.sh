#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
SERVER_PID=''
trap '[[ -z $SERVER_PID ]] || kill "$SERVER_PID" 2>/dev/null || true; rm -rf "$TMP"' EXIT
fail(){ echo "FAIL: $*" >&2; exit 1; }
assert(){ "$@" || fail "$*"; }
mkdir -p "$TMP/repo" "$TMP/bin" "$TMP/dev" "$TMP/recorded" "$TMP/konomitv" "$TMP/home"
cp -R "$ROOT/." "$TMP/repo/"
mkdir -p "$TMP/repo/konomitv"
touch "$TMP/dev/px4video0"
cp "$ROOT/.env.example" "$TMP/repo/.env"
printf 'CUSTOM_KEEP=preserved\n' >> "$TMP/repo/.env"
cat > "$TMP/repo/konomitv/Dockerfile" <<'EOF'
FROM scratch
EOF
cat > "$TMP/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$DOCKER_CALLS"
case "$*" in
  'compose version'|'info'|'compose config') exit 0;;
  'info --format {{json .Runtimes}}') [[ ${NVIDIA_TOOLKIT_OK:-0} == 1 ]] && echo '{"nvidia":{}}';;
  'compose ps --format json') echo '[]';;
  'compose ps --status running --services') printf 'recisdb-proxy\nepgstation\nkonomitv\n';;
  'compose logs --no-color recisdb-proxy') echo 'Web API auth token: test-token';;
esac
EOF
cat > "$TMP/bin/getent" <<'EOF'
#!/usr/bin/env bash
[[ $1 == group && $2 == video ]] && echo 'video:x:44:'
EOF
cat > "$TMP/bin/id" <<'EOF'
#!/usr/bin/env bash
[[ $1 == -u ]] && echo 1000
EOF
cat > "$TMP/bin/nvidia-smi" <<'EOF'
#!/usr/bin/env bash
[[ ${NVIDIA_OK:-0} == 1 ]]
EOF
cat > "$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$CURL_CALLS"
exit 0
EOF
cat > "$TMP/bin/nvidia-ctk" <<'EOF'
#!/usr/bin/env bash
[[ ${NVIDIA_TOOLKIT_OK:-0} == 1 ]]
EOF
cat > "$TMP/bin/hostname" <<'EOF'
#!/usr/bin/env bash
[[ $1 == -I ]] && echo '192.168.1.30'
EOF
cat > "$TMP/bin/ip" <<'EOF'
#!/usr/bin/env bash
if [[ $1 == -4 && $2 == route ]]; then echo '1.1.1.1 via 192.168.1.1 dev eno1 src 192.168.1.30'; exit 0; fi
if [[ $1 == -brief ]]; then echo 'eno1 UP 192.168.1.30/24'; exit 0; fi
exit 1
EOF
chmod +x "$TMP/bin/"*
export PATH="$TMP/bin:/opt/homebrew/bin:/usr/bin:/bin" HOME="$TMP/home" DOCKER_BIN="$TMP/bin/docker" DOCKER_CALLS="$TMP/docker.calls" CURL_CALLS="$TMP/curl.calls" DEV_DIR="$TMP/dev" TUNERS_COMPOSE_FILE="$TMP/repo/compose.tuners.yaml" ENV_FILE="$TMP/repo/.env" SETUP_OS=Linux
python3 -u -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); s.listen(); print(s.getsockname()[1],flush=True); exec("while True:\n c,_=s.accept(); c.close()")' > "$TMP/server-port" &
SERVER_PID=$!
disown "$SERVER_PID" 2>/dev/null || true
for _ in {1..50}; do [[ -s $TMP/server-port ]] && break; sleep 0.1; done
SERVER_PORT=$(cat "$TMP/server-port")
[[ $SERVER_PORT =~ ^[0-9]+$ ]] || fail 'temporary relay server did not start'

run_setup(){ (cd "$TMP/repo" && BONCAS_HOST=127.0.0.1 BONCAS_PORT="$SERVER_PORT" BONCAS_4K_SAME=yes RECORDED_DIR="$TMP/recorded" GPU="${1:-none}" DB="${2:-sqlite}" KONOMITV_SOURCE="$TMP/repo/konomitv" SETUP_OS=Linux ./setup.sh --yes --no-build --no-start); }
run_setup none >"$TMP/out"
grep -q '^COMPOSE_FILE=compose.yaml:compose.tuners.yaml$' "$ENV_FILE" || fail 'default COMPOSE_FILE'
grep -q '^CUSTOM_KEEP=preserved$' "$ENV_FILE" || fail 'unrelated env key not preserved'
grep -q "$TMP/dev/px4video0:/dev/px4video0" "$TUNERS_COMPOSE_FILE" || { cat "$TUNERS_COMPOSE_FILE" >&2; fail 'tuner device generated'; }
backup_found=0; for backup in "$ENV_FILE".bak.*; do [[ -f $backup ]] && backup_found=1; done
((backup_found)) || fail 'backup not created'

mkdir -p "$TMP/dev/dri"; touch "$TMP/dev/dri/renderD128"; run_setup intel >"$TMP/out"
grep -q '^COMPOSE_FILE=compose.yaml:compose.tuners.yaml:compose.intel.yaml$' "$ENV_FILE" || fail 'Intel COMPOSE_FILE'
rm "$TMP/dev/dri/renderD128"; if run_setup intel >"$TMP/intel-missing" 2>&1; then fail 'Intel GPU without render node should stop by default'; fi
grep -q 'renderD\* がありません' "$TMP/intel-missing" || fail 'Intel render node guidance'
rmdir "$TMP/dev/dri"
if NVIDIA_OK=1 NVIDIA_TOOLKIT_OK=0 run_setup nvidia >"$TMP/nvidia-missing" 2>&1; then fail 'NVIDIA runtime missing should stop by default'; fi
grep -q 'NVIDIA Container Toolkit' "$TMP/nvidia-missing" || fail 'NVIDIA toolkit guidance'
NVIDIA_OK=1 NVIDIA_TOOLKIT_OK=1 run_setup nvidia >"$TMP/out"
grep -q ':compose.nvidia.yaml$' "$ENV_FILE" || fail 'NVIDIA COMPOSE_FILE'
NVIDIA_OK=0 run_setup none >"$TMP/out"
grep -q '^docker compose build$' "$DOCKER_CALLS" && fail 'no-build should skip build'
run_setup none mariadb >"$TMP/out"
grep -q ':compose.mariadb.yaml$' "$ENV_FILE" || fail 'MariaDB COMPOSE_FILE'
grep -q '^COMPOSE_PROFILES=mariadb$' "$ENV_FILE" || fail 'MariaDB profile not enabled'
if grep -q '^MARIADB_PASSWORD=change-me$' "$ENV_FILE" || grep -q '^MARIADB_ROOT_PASSWORD=change-me-too$' "$ENV_FILE"; then fail 'MariaDB password was not generated'; fi

(cd "$TMP/repo" && BONCAS_HOST=127.0.0.1 BONCAS_PORT=1 BONCAS_4K_SAME=yes RECORDED_DIR="$TMP/recorded" GPU=none DB=sqlite KONOMITV_SOURCE="$TMP/repo/konomitv" SETUP_OS=Linux ./setup.sh --yes --no-build --no-start) >"$TMP/failed" 2>&1 || true
grep -q 'BonCasRelay に接続できません' "$TMP/failed" || fail 'unreachable relay explanation'
if (cd "$TMP/repo" && SETUP_OS=Darwin ./setup.sh --help >/dev/null); then :; fi
if (cd "$TMP/repo" && SETUP_OS=Darwin ./setup.sh --yes --no-build --no-start) >"$TMP/darwin" 2>&1; then fail 'Darwin should stop'; fi
grep -q 'Linux 専用' "$TMP/darwin" || fail 'Darwin explanation'

export DEV_DIR="$TMP/empty-dev"; mkdir -p "$DEV_DIR"
export DOCKER_CALLS="$TMP/docker2.calls"
if (cd "$TMP/repo" && BONCAS_HOST=127.0.0.1 BONCAS_PORT=6900 BONCAS_4K_SAME=yes RECORDED_DIR="$TMP/recorded" GPU=none DB=sqlite KONOMITV_SOURCE="$TMP/repo/konomitv" SETUP_OS=Linux ./setup.sh --yes) >"$TMP/full"; then :; else cat "$TMP/full" >&2; fail 'full stub setup'; fi
grep -q '^compose build$' "$DOCKER_CALLS" || fail 'build args'
grep -q '^compose up -d$' "$DOCKER_CALLS" || fail 'up args'
grep -q '^compose config$' "$DOCKER_CALLS" || fail 'config args'
grep -q 'test-token' "$TMP/full" || fail 'dashboard token'
grep -Eq -- '--resolve 192-168-1-30\.local\.konomi\.tv:7000:127\.0\.0\.1 .*https://192-168-1-30\.local\.konomi\.tv:7000/' "$CURL_CALLS" || fail 'KonomiTV HTTPS probe URL'
grep -q 'KonomiTV: https://192-168-1-30.local.konomi.tv:7000/' "$TMP/full" || fail 'KonomiTV HTTPS URL output'
grep -q 'px4_drv を検出できません' "$TMP/full" || fail 'missing px4_drv guidance'
echo 'PASS: --yes generation, backup, GPU compose selection, relay failure, OS guard, build/up stubs'
