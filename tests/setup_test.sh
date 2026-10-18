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
printf 'EPGSTATION_REF=master\nCUSTOM_KEEP=preserved\n' >> "$TMP/repo/.env"
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
  'compose ps --status running --services') printf 'recisdb-proxy\nepgstation\nkonomitv\namatsukaze\nedcb\nboncasrelay\n';;
  'compose logs --no-color recisdb-proxy') echo 'Web API auth token: test-token';;
esac
EOF
cat > "$TMP/bin/getent" <<'EOF'
#!/usr/bin/env bash
[[ $1 == group && $2 == video ]] && echo 'video:x:44:'
EOF
cat > "$TMP/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$SYSTEMCTL_CALLS"
if [[ $1 == is-active && $2 == --quiet ]]; then
  case $3 in
    pcscd.service) [[ ${PCSC_SERVICE_ACTIVE:-0} == 1 ]];;
    pcscd.socket) [[ ${PCSC_SOCKET_ACTIVE:-0} == 1 ]];;
    *) exit 1;;
  esac
fi
EOF
cat > "$TMP/bin/sudo" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$SUDO_CALLS"
if [[ $1 == -n && $2 == true ]]; then [[ ${SUDO_NONINTERACTIVE_OK:-1} == 1 ]]; exit; fi
exit 0
EOF
cat > "$TMP/bin/id" <<'EOF'
#!/usr/bin/env bash
case $1 in -u) echo "${TEST_UID:-1000}";; -g) echo "${TEST_GID:-1000}";; esac
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
export AMATSUKAZE=no EDCB=no
export PATH="$TMP/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" HOME="$TMP/home" DOCKER_BIN="$TMP/bin/docker" DOCKER_CALLS="$TMP/docker.calls" CURL_CALLS="$TMP/curl.calls" SYSTEMCTL_CALLS="$TMP/systemctl.calls" SUDO_CALLS="$TMP/sudo.calls" DEV_DIR="$TMP/dev" TUNERS_COMPOSE_FILE="$TMP/repo/compose.tuners.yaml" ENV_FILE="$TMP/repo/.env" SETUP_OS=Linux
python3 -u -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); s.listen(); print(s.getsockname()[1],flush=True); exec("while True:\n c,_=s.accept(); c.close()")' > "$TMP/server-port" &
SERVER_PID=$!
disown "$SERVER_PID" 2>/dev/null || true
for _ in {1..50}; do [[ -s $TMP/server-port ]] && break; sleep 0.1; done
SERVER_PORT=$(cat "$TMP/server-port")
[[ $SERVER_PORT =~ ^[0-9]+$ ]] || fail 'temporary relay server did not start'

run_setup(){ (cd "$TMP/repo" && BONCAS_HOST=127.0.0.1 BONCAS_PORT="$SERVER_PORT" BONCAS_4K_SAME=yes RECORDED_DIR="${RECORDED_DIR:-$TMP/recorded}" GPU="${1:-none}" KONOMITV_SOURCE="$TMP/repo/konomitv" SETUP_OS=Linux ./setup.sh --yes --no-build --no-start); }

# A first-time socket activation is described accurately; no interactive sudo attempt.
if PCSC_SOCKET_ACTIVE=1 SUDO_NONINTERACTIVE_OK=0 BONCAS_MODE=local run_setup none >"$TMP/pcscd-socket" 2>&1; then
  fail 'socket-only pcscd with unavailable noninteractive sudo should stop'
fi
grep -q 'pcscd.socket が有効です。リーダー接続時にホスト pcscd が起動' "$TMP/pcscd-socket" || fail 'socket-only pcscd explanation'
grep -q 'sudo systemctl disable --now pcscd.service pcscd.socket' "$TMP/pcscd-socket" || fail 'sudo command shown'
grep -q '上のコマンドを実行してから ./setup.sh を再実行してください' "$TMP/pcscd-socket" || fail 'noninteractive sudo recovery guidance'
if grep -q 'systemctl disable --now' "$SUDO_CALLS"; then fail 'pcscd sudo action must not be attempted'; fi

# Missing .env means there is no prior storage choice to warn about; a real later change does warn.
mv "$ENV_FILE" "$ENV_FILE.saved"
mkdir -p "$TMP/recorded-first" "$TMP/recorded-second"
BONCAS_MODE=remote RECORDED_DIR="$TMP/recorded-first" run_setup none >"$TMP/storage-first"
if grep -q '録画先の削除・対応変更' "$TMP/storage-first"; then fail 'initial storage setup emitted removal warning'; fi
BONCAS_MODE=remote RECORDED_DIR="$TMP/recorded-second" run_setup none >"$TMP/storage-change"
grep -q '録画先の削除・対応変更' "$TMP/storage-change" || fail 'storage change warning missing'
mv "$ENV_FILE.saved" "$ENV_FILE"
HTTPS=yes run_setup none >"$TMP/out"
grep -q '^COMPOSE_FILE=compose.yaml:compose.tuners.yaml:compose.https.yaml$' "$ENV_FILE" || fail 'default HTTPS COMPOSE_FILE'
[[ -f $TMP/repo/config/recisdb-proxy/recisdb-proxy.toml && -f $TMP/repo/config/epgstation/config.yml && -f $TMP/repo/config/konomitv/config.yaml ]] || fail 'first run creates host config files'
grep -q 'boncaslink_server = "127.0.0.1:'"$SERVER_PORT"'"' "$TMP/repo/config/recisdb-proxy/recisdb-proxy.toml" || fail 'relay address embedded in recisdb config'
printf 'user_edit = true\n' >> "$TMP/repo/config/recisdb-proxy/recisdb-proxy.toml"
grep -q "^BONCAS_B25_PORT=$SERVER_PORT$" "$ENV_FILE" || fail 'relay port changed by WebUI port loop'
grep -q "^BONCAS_4K_PORT=$SERVER_PORT$" "$ENV_FILE" || fail '4K relay port changed'
grep -q '^CUSTOM_KEEP=preserved$' "$ENV_FILE" || fail 'unrelated env key not preserved'
grep -q "$TMP/dev/px4video0:/dev/px4video0" "$TUNERS_COMPOSE_FILE" || { cat "$TUNERS_COMPOSE_FILE" >&2; fail 'tuner device generated'; }
backup_found=0; for backup in "$ENV_FILE".bak.*; do [[ -f $backup ]] && backup_found=1; done
((backup_found)) || fail 'backup not created'

HTTPS=no run_setup none >"$TMP/out"
grep -q '^user_edit = true$' "$TMP/repo/config/recisdb-proxy/recisdb-proxy.toml" || fail 'setup overwrote user config'
HTTPS=no run_setup none >"$TMP/out"
grep -q '^COMPOSE_FILE=compose.yaml:compose.tuners.yaml$' "$ENV_FILE" || fail 'HTTPS disabled COMPOSE_FILE'
grep -q '^RECISDB_HTTPS_PORT=40443$' "$ENV_FILE" || fail 'HTTPS port setting preserved when disabled'
HTTPS=yes run_setup none >"$TMP/out"
grep -q ':compose.https.yaml$' "$ENV_FILE" || fail 'HTTPS re-enable COMPOSE_FILE'

mkdir -p "$TMP/dev/dri"; touch "$TMP/dev/dri/renderD128"; run_setup intel >"$TMP/out"
grep -q '^COMPOSE_FILE=compose.yaml:compose.tuners.yaml:compose.intel.yaml:compose.https.yaml$' "$ENV_FILE" || fail 'Intel COMPOSE_FILE'
rm "$TMP/dev/dri/renderD128"; if run_setup intel >"$TMP/intel-missing" 2>&1; then fail 'Intel GPU without render node should stop by default'; fi
grep -q 'renderD\* がありません' "$TMP/intel-missing" || fail 'Intel render node guidance'
rmdir "$TMP/dev/dri"
if NVIDIA_OK=1 NVIDIA_TOOLKIT_OK=0 run_setup nvidia >"$TMP/nvidia-missing" 2>&1; then fail 'NVIDIA runtime missing should stop by default'; fi
grep -q 'NVIDIA Container Toolkit' "$TMP/nvidia-missing" || fail 'NVIDIA toolkit guidance'
NVIDIA_OK=1 NVIDIA_TOOLKIT_OK=1 run_setup nvidia >"$TMP/out"
grep -q ':compose.nvidia.yaml:compose.https.yaml$' "$ENV_FILE" || fail 'NVIDIA COMPOSE_FILE'
NVIDIA_OK=0 run_setup none >"$TMP/out"
grep -q '^docker compose build$' "$DOCKER_CALLS" && fail 'no-build should skip build'
password=$(sed -n 's/^MARIADB_PASSWORD=//p' "$ENV_FILE")
root_password=$(sed -n 's/^MARIADB_ROOT_PASSWORD=//p' "$ENV_FILE")
run_setup none >"$TMP/out"
grep -q "^MARIADB_PASSWORD=$password$" "$ENV_FILE" || fail 'DB password not preserved'
grep -q "^MARIADB_ROOT_PASSWORD=$root_password$" "$ENV_FILE" || fail 'root password not preserved'
[[ $password =~ ^[a-f0-9]{48}$ && $root_password =~ ^[a-f0-9]{48}$ ]] || fail 'DB password generation'
if grep '^COMPOSE_FILE=' "$ENV_FILE" | grep -q mariadb; then fail 'obsolete DB override'; fi
if grep -q '^COMPOSE_PROFILES=mariadb$' "$ENV_FILE"; then fail 'obsolete DB profile'; fi

(cd "$TMP/repo" && BONCAS_HOST=127.0.0.1 BONCAS_PORT=1 BONCAS_4K_SAME=yes RECORDED_DIR="$TMP/recorded" GPU=none KONOMITV_SOURCE="$TMP/repo/konomitv" SETUP_OS=Linux ./setup.sh --yes --no-build --no-start) >"$TMP/failed" 2>&1 || true
grep -q 'BonCasRelay に接続できません' "$TMP/failed" || fail 'unreachable relay explanation'
if (cd "$TMP/repo" && SETUP_OS=Darwin ./setup.sh --help >/dev/null); then :; fi
if (cd "$TMP/repo" && SETUP_OS=Darwin ./setup.sh --yes --no-build --no-start) >"$TMP/darwin" 2>&1; then fail 'Darwin should stop'; fi
grep -q 'Linux 専用' "$TMP/darwin" || fail 'Darwin explanation'

export DEV_DIR="$TMP/empty-dev"; mkdir -p "$DEV_DIR"
export DOCKER_CALLS="$TMP/docker2.calls"
if (cd "$TMP/repo" && BONCAS_HOST=127.0.0.1 BONCAS_PORT=6900 BONCAS_4K_SAME=yes RECORDED_DIR="$TMP/recorded" GPU=none KONOMITV_SOURCE="$TMP/repo/konomitv" SETUP_OS=Linux ./setup.sh --yes) >"$TMP/full"; then :; else cat "$TMP/full" >&2; fail 'full stub setup'; fi
grep -q '^compose build$' "$DOCKER_CALLS" || fail 'build args'
grep -q '^compose up -d$' "$DOCKER_CALLS" || fail 'up args'
grep -q '^compose config$' "$DOCKER_CALLS" || fail 'config args'
grep -q 'test-token' "$TMP/full" || fail 'dashboard token'
grep -Eq -- '--resolve 192-168-1-30\.local\.konomi\.tv:7000:127\.0\.0\.1 .*https://192-168-1-30\.local\.konomi\.tv:7000/' "$CURL_CALLS" || fail 'KonomiTV HTTPS probe URL'
grep -Eq -- '--resolve 192-168-1-30\.local\.konomi\.tv:40443:127\.0\.0\.1 .*https://192-168-1-30\.local\.konomi\.tv:40443/' "$CURL_CALLS" || fail 'recisdb HTTPS probe URL'
grep -Eq -- '--resolve 192-168-1-30\.local\.konomi\.tv:8443:127\.0\.0\.1 .*https://192-168-1-30\.local\.konomi\.tv:8443/' "$CURL_CALLS" || fail 'EPGStation HTTPS probe URL'
grep -q 'KonomiTV HTTPS: https://192-168-1-30.local.konomi.tv:7000/' "$TMP/full" || fail 'KonomiTV HTTPS URL output'
grep -q 'px4_drv を検出できません' "$TMP/full" || fail 'missing px4_drv guidance'

# Exercise opt-in selection without launching a real Docker daemon.
export DEV_DIR="$TMP/dev"
AMATSUKAZE=yes run_setup none >"$TMP/amatsukaze.out"
grep -q ':compose.amatsukaze.yaml$' "$ENV_FILE" || fail 'Amatsukaze enabled COMPOSE_FILE'
grep -q '^AMATSUKAZE_WEBUI_PORT=32769$' "$ENV_FILE" || fail 'Amatsukaze WebUI port'
grep -q '^RUN_UID=1000$' "$ENV_FILE" || fail 'shared UID'
grep -q '^RUN_GID=1000$' "$ENV_FILE" || fail 'shared GID'
grep -q '^EPGSTATION_REF=main$' "$ENV_FILE" || fail 'obsolete master migration'
if grep -q '^EPGSTATION_REF=master$' "$ENV_FILE"; then fail 'duplicate obsolete master remains'; fi
mkdir -p "$TMP/dev/dri"; touch "$TMP/dev/dri/renderD128"
AMATSUKAZE=yes run_setup intel >"$TMP/out"
grep -q ':compose.amatsukaze.yaml:compose.amatsukaze.intel.yaml$' "$ENV_FILE" || fail 'conditional Amatsukaze Intel override'
rm "$TMP/dev/dri/renderD128"; rmdir "$TMP/dev/dri"
AMATSUKAZE=yes NVIDIA_OK=1 NVIDIA_TOOLKIT_OK=1 run_setup nvidia >"$TMP/out"
grep -q ':compose.amatsukaze.yaml:compose.amatsukaze.nvidia.yaml$' "$ENV_FILE" || fail 'conditional Amatsukaze NVIDIA override'
AMATSUKAZE=no run_setup none >"$TMP/out"
if grep '^COMPOSE_FILE=' "$ENV_FILE" | grep -q amatsukaze; then fail 'disabled Amatsukaze override remains'; fi

# A copied example still defaults to enabled and uses the invoking user's IDs.
awk '!/^SETUP_AMATSUKAZE=/' "$ENV_FILE" > "$ENV_FILE.next"; mv "$ENV_FILE.next" "$ENV_FILE"
(unset AMATSUKAZE; TEST_UID=2345 TEST_GID=3456 run_setup none >"$TMP/default-amatsukaze.out")
grep -q ':compose.amatsukaze.yaml$' "$ENV_FILE" || fail 'first-run Amatsukaze defaults yes'
grep -q '^RUN_UID=2345$' "$ENV_FILE" || fail 'first-run UID follows caller'
grep -q '^RUN_GID=3456$' "$ENV_FILE" || fail 'first-run GID follows caller'
AMATSUKAZE=no run_setup none >"$TMP/out"
(unset AMATSUKAZE; run_setup none >"$TMP/out")
if grep '^COMPOSE_FILE=' "$ENV_FILE" | grep -q amatsukaze; then fail 'explicit no not preserved'; fi

# Reconfigure removes the legacy DB override/profile without rotating credentials.
printf 'COMPOSE_FILE=compose.yaml:compose.mariadb.yaml\nCOMPOSE_PROFILES=mariadb,custom\nSETUP_DB=sqlite\n' >> "$ENV_FILE"
HTTPS=yes run_setup none >"$TMP/out"
grep -q '^COMPOSE_PROFILES=custom$' "$ENV_FILE" || fail 'custom profile not preserved'
if grep -q '^SETUP_DB=' "$ENV_FILE"; then fail 'obsolete DB selector'; fi
grep -q "^MARIADB_PASSWORD=$password$" "$ENV_FILE" || fail 'legacy migration rotated password'

# EDCB combinations, default yes and saved opt-out; no real containers.
EDCB=yes HTTPS=yes run_setup none >"$TMP/edcb.out"
grep -q ':compose.edcb.yaml:compose.edcb.https.yaml$' "$ENV_FILE" || fail 'EDCB HTTPS overrides'
grep -q '^EDCB_WEB_PORT=5510$' "$ENV_FILE" || fail 'EDCB HTTP port'
EDCB=yes HTTPS=no AMATSUKAZE=yes run_setup none >"$TMP/edcb.out"
grep -q ':compose.amatsukaze.yaml:compose.edcb.yaml$' "$ENV_FILE" || fail 'EDCB without HTTPS'
EDCB=no HTTPS=yes run_setup none >"$TMP/out"
(unset EDCB; run_setup none >"$TMP/out")
if grep '^COMPOSE_FILE=' "$ENV_FILE" | grep -q edcb; then fail 'EDCB opt-out not preserved'; fi
awk '!/^SETUP_EDCB=/' "$ENV_FILE" > "$ENV_FILE.next"; mv "$ENV_FILE.next" "$ENV_FILE"
(unset EDCB; run_setup none >"$TMP/out")
grep -q ':compose.edcb.yaml:compose.edcb.https.yaml$' "$ENV_FILE" || fail 'EDCB default yes'
EDCB=yes EDCB_WEB_PORT=5520 EDCB_HTTPS_PORT=8554 run_setup none >"$TMP/out"
grep -q '^EDCB_WEB_PORT=5520$' "$ENV_FILE" || fail 'custom EDCB port'
if EDCB=yes EDCB_TUNER_COUNT=0 run_setup none >"$TMP/out" 2>&1; then fail 'invalid EDCB count'; fi
EDCB=no run_setup none >"$TMP/out"

(cd "$TMP/repo" && EDCB=yes HTTPS=yes EDCB_WEB_PORT=5510 EDCB_HTTPS_PORT=8553 BONCAS_HOST=127.0.0.1 BONCAS_PORT="$SERVER_PORT" BONCAS_4K_SAME=yes RECORDED_DIR="$TMP/recorded" GPU=none KONOMITV_SOURCE="$TMP/repo/konomitv" ./setup.sh --yes --no-build) >"$TMP/edcb-full"
grep -q 'http://127.0.0.1:5510/' "$CURL_CALLS" || fail 'EDCB HTTP probe'
grep -q 'https://192-168-1-30.local.konomi.tv:8553/' "$CURL_CALLS" || fail 'EDCB HTTPS probe'
grep -q 'EDCB WebUI: http://192.168.1.30:5510/E3/' "$TMP/edcb-full" || fail 'EDCB WebUI URL'

# EPGStation uses the host-created config as is: the entrypoint never regenerates it.
app="$TMP/epg-app"; mkdir -p "$app/config"
for name in operatorLogConfig serviceLogConfig epgUpdaterLogConfig; do touch "$app/config/$name.sample.yml"; done
printf 'user: edited\n' > "$app/config/config.yml"
EPGSTATION_APP_ROOT="$app" AMATSUKAZE_ENABLED=0 sh "$ROOT/docker/epgstation/entrypoint.sh" true >/dev/null
grep -qx 'user: edited' "$app/config/config.yml" || fail 'EPGStation entrypoint rewrote user config'
[[ -f $app/config/operatorLogConfig.yml ]] || fail 'EPGStation sample log config not seeded'
rm -f "$app/config/config.yml"
if EPGSTATION_APP_ROOT="$app" sh "$ROOT/docker/epgstation/entrypoint.sh" true >"$TMP/epg-missing" 2>&1; then fail 'missing EPGStation config should stop'; fi
grep -q 'setup.sh' "$TMP/epg-missing" || fail 'missing EPGStation config guidance'
printf 'user: edited\n' > "$app/config/config.yml"

# Root bootstrap delegates to the selected numeric identity and only repairs application state.
cat > "$TMP/bin/chown" <<'EOFCHOWN'
#!/bin/sh
printf '%s\n' "$*" >> "$IDENTITY_CALLS"
EOFCHOWN
cat > "$TMP/bin/gosu" <<'EOFGOSU'
#!/bin/sh
printf 'gosu %s\n' "$*" >> "$IDENTITY_CALLS"
shift
exec "$@"
EOFGOSU
chmod +x "$TMP/bin/chown" "$TMP/bin/gosu"
IDENTITY_CALLS="$TMP/identity.calls" TEST_UID=0 EPGSTATION_APP_ROOT="$app" AMATSUKAZE_ENABLED=1 RUN_UID=1234 RUN_GID=2345 sh "$ROOT/docker/epgstation/entrypoint.sh" true
grep -q 'gosu 1234:2345 true' "$TMP/identity.calls" || fail 'EPGStation identity drop'
if grep -q /recorded "$TMP/identity.calls"; then fail 'recording ownership must not change'; fi
if grep -v '^gosu' "$TMP/identity.calls" | grep -q 'config/config.yml'; then fail 'host config.yml ownership must not change'; fi

# First start seeds bind mounts, later starts preserve user-edited profiles and assets.
seed="$TMP/amatsukaze-defaults"; app="$TMP/amatsukaze-app"
for dir in avs bat config data drcs JL logo profile input output; do mkdir -p "$seed/$dir"; done
cp "$ROOT/docker/amatsukaze/EPGStation.profile" "$seed/profile/"
mkdir -p "$app"
printf '#!/bin/sh\nexec "$@"\n' > "$app/entrypoint.sh"; chmod +x "$app/entrypoint.sh"
STACK_SCRIPTS="$ROOT/scripts" AMATSUKAZE_APP_ROOT="$app" AMATSUKAZE_DEFAULTS="$seed" "$ROOT/docker/amatsukaze/entrypoint.sh" true
cmp "$seed/profile/EPGStation.profile" "$app/profile/EPGStation.profile" || fail 'first boot profile seed'
printf 'user profile\n' > "$app/profile/EPGStation.profile"
STACK_SCRIPTS="$ROOT/scripts" AMATSUKAZE_APP_ROOT="$app" AMATSUKAZE_DEFAULTS="$seed" "$ROOT/docker/amatsukaze/entrypoint.sh" true
grep -qx 'user profile' "$app/profile/EPGStation.profile" || fail 'profile overwritten'
python3 - "$ROOT/docker/amatsukaze/EPGStation.profile" <<'PYXML'
import sys, xml.etree.ElementTree as ET
p = ET.parse(sys.argv[1]).getroot()
ns = {'p': 'http://schemas.datacontract.org/2004/07/Amatsukaze.Server'}
for k, v in {'Name':'EPGStation', 'EncoderType':'x264', 'DisableChapter':'false', 'NoDelogo':'false', 'OutputMask':'2', 'OutputFormat':'MP4', 'EnableRename':'false', 'MoveEDCBFiles':'false'}.items():
    assert p.find('p:' + k, ns).text == v, k
PYXML
echo 'PASS: Amatsukaze opt-in, GPU overrides, master migration, EPGStation entrypoint keeps host config, profile seed/nonoverwrite'

cat > "$TMP/akebi-stub" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$AKEBI_ARGS"
exec sleep 30
EOF
chmod +x "$TMP/akebi-stub"
: > "$TMP/akebi.args"
AKEBI_ARGS="$TMP/akebi.args" AKEBI_BIN="$TMP/akebi-stub" AKEBI_ROUTES='40443=http://recisdb-proxy:40080/ 8443=http://epgstation:8888/' AKEBI_LISTEN_HOST=127.0.0.1 TMPDIR="$TMP" "$ROOT/docker/https-gateway/entrypoint.sh" >"$TMP/gateway.log" 2>&1 &
GATEWAY_PID=$!
for _ in {1..50}; do [[ $(wc -l < "$TMP/akebi.args" 2>/dev/null || echo 0) -ge 2 ]] && break; sleep 0.1; done
grep -q -- '--listen-address 127.0.0.1:40443 --proxy-pass-url http://recisdb-proxy:40080/ --keyless-server-url https://akebi.konomi.tv/' "$TMP/akebi.args" || fail 'recisdb Akebi args'
grep -q -- '--listen-address 127.0.0.1:8443 --proxy-pass-url http://epgstation:8888/ --keyless-server-url https://akebi.konomi.tv/' "$TMP/akebi.args" || fail 'EPGStation Akebi args'
kill -TERM "$GATEWAY_PID" 2>/dev/null || true
wait "$GATEWAY_PID" 2>/dev/null || true
if AKEBI_BIN="$TMP/akebi-stub" AKEBI_ROUTES='bad-route' "$ROOT/docker/https-gateway/entrypoint.sh" >"$TMP/bad-route" 2>&1; then fail 'invalid Akebi route should fail'; fi
grep -q 'expected PORT=URL' "$TMP/bad-route" || fail 'invalid route explanation'
echo 'PASS: --yes generation, backup, GPU compose selection, relay failure, OS guard, build/up stubs'

python3 "$ROOT/tests/setup_ui_test.py"
