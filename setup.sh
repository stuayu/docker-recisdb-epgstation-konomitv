#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"
NONINTERACTIVE=0 YES=0 RECONFIGURE=0 NO_BUILD=0 NO_START=0 INSTALL_DOCKER=0
DEV_DIR=${DEV_DIR:-/dev}
ENV_FILE=${ENV_FILE:-$ROOT/.env}
COMPOSE_TUNERS=${TUNERS_COMPOSE_FILE:-$ROOT/compose.tuners.yaml}
OS_OVERRIDE=${SETUP_OS:-}
STEP=0

usage() {
  cat <<'EOF'
使い方: ./setup.sh [オプション]
  --yes              既定値で非対話セットアップ
  --no-build         Docker イメージをビルドしない
  --no-start         コンテナを起動しない
  --reconfigure      質問と設定だけやり直す (ビルド・起動しない)
  --install-docker   Docker 公式インストールスクリプトを確認後に実行
  --help             このヘルプ

非対話環境変数: BONCAS_HOST, BONCAS_PORT, BONCAS_4K_SAME,
RECORDED_DIR, GPU (none|intel|nvidia), DB (sqlite|mariadb),
RECISDB_WEB_PORT, EPGSTATION_PORT, KONOMITV_PORT, HTTPS (yes|no),
RECISDB_HTTPS_PORT, EPGSTATION_HTTPS_PORT, KONOMITV_SOURCE,
AMATSUKAZE (yes|no), AMATSUKAZE_WEBUI_PORT, RUN_UID, RUN_GID
EOF
}
while (($#)); do
  case $1 in
    --yes) YES=1;; --no-build) NO_BUILD=1;; --no-start) NO_START=1;;
    --reconfigure) RECONFIGURE=1; NO_BUILD=1; NO_START=1;;
    --install-docker) INSTALL_DOCKER=1;; --help|-h) usage; exit 0;;
    *) printf '不明なオプション: %s\n' "$1" >&2; usage >&2; exit 2;;
  esac
  shift
done
[[ -t 0 ]] || NONINTERACTIVE=1
if [[ -t 1 ]]; then GREEN=$'\033[32m'; RED=$'\033[31m'; RESET=$'\033[0m'; else GREEN=''; RED=''; RESET=''; fi
ok(){ printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
fail(){ printf '%sエラー:%s %s\n対処: %s\n' "$RED" "$RESET" "$1" "$2" >&2; exit 1; }
step(){ STEP=$((STEP+1)); printf '\n[%d/11] %s\n' "$STEP" "$*"; }
ask(){ local prompt=$1 default=$2 value; if ((YES || NONINTERACTIVE)); then printf -v REPLY '%s' "$default"; else read -r -p "$prompt [$default]: " value; REPLY=${value:-$default}; fi; }
get(){ local key=$1 default=$2 value; value=$(sed -n "s/^${key}=//p" "$ENV_FILE" 2>/dev/null | tail -n1 || true); printf '%s' "${value:-$default}"; }
SETTINGS_FILE=$(mktemp)
trap 'rm -f "$SETTINGS_FILE"' EXIT
put(){ printf '%s=%s\n' "$1" "$2" >> "$SETTINGS_FILE"; }
case ${OS_OVERRIDE:-$(uname -s)} in Linux) ;; *) fail 'Linux 専用です (Docker Compose のデバイス設定を使います)。' '対応 Linux ホストで実行してください。テスト時は SETUP_OS=Linux を指定できます。';; esac
(( EUID != 0 )) || fail 'root では実行できません。' '通常ユーザーで実行してください。sudo は必要な作業だけ個別に使います。'

step 'OS・必要コマンド・容量を確認'
command -v git >/dev/null || fail 'git がありません。' 'Ubuntu/Debian: sudo apt update && sudo apt install -y git'
docker_cmd=${DOCKER_BIN:-$(command -v docker || true)}
if [[ -z $docker_cmd ]] && ((INSTALL_DOCKER)); then
  printf 'これから get.docker.com を取得・実行し、Docker Engine をインストールします。\n'
  if ((YES)); then fail '--install-docker と --yes の併用では確認を省略できません。' '対話端末で --install-docker を実行してください。'; fi
  read -r -p '公式インストールスクリプトの実行を承認しますか? [y/N] ' answer
  [[ $answer == y || $answer == Y ]] || fail 'Docker の導入を中止しました。' 'Docker 公式手順を使って導入し、再実行してください.'
  command -v curl >/dev/null || fail 'curl がありません。' 'sudo apt install -y curl を実行してください。'
  curl -fsSL https://get.docker.com -o /tmp/docker-install.sh || fail '公式インストールスクリプトを取得できません。' 'ネットワークを確認し Docker 公式手順を参照してください。'
  sudo sh /tmp/docker-install.sh || fail 'Docker インストールに失敗しました。' 'Docker 公式手順のエラーを確認してください。'
  docker_cmd=$(command -v docker || true)
fi
[[ -n $docker_cmd ]] || fail 'Docker Engine がありません。' 'https://docs.docker.com/engine/install/ を参照。Ubuntu は README の導入例を実行してください。'
"$docker_cmd" compose version >/dev/null 2>&1 || fail 'Docker Compose v2 がありません。' 'Docker Engine の Compose plugin を導入してください: https://docs.docker.com/compose/install/linux/'
if ! "$docker_cmd" info >/dev/null 2>&1; then
  if command -v getent >/dev/null && getent group docker >/dev/null; then
    # shellcheck disable=SC2016
    fail '現在のユーザーが Docker を利用できません。' 'sudo usermod -aG docker "$USER" を実行し、ログアウト・再ログインしてください。'
  fi
  fail 'Docker daemon に接続できません。' 'Docker Engine を起動し、ユーザーを docker グループへ追加してください。'
fi
free_kb=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
printf 'ビルド用の空き容量: %.1f GiB (数 GB 以上を推奨)\n' "$(awk -v k="$free_kb" 'BEGIN{print k/1048576}')"
ok 'Linux、git、Docker Compose v2 を確認'

step 'チューナーデバイスを確認'
device_count=0
for p in "$DEV_DIR"/px4video* "$DEV_DIR"/pt3video* "$DEV_DIR"/pxmlt5video* "$DEV_DIR"/isdb2056video*; do [[ -e $p && ! -d $p ]] && device_count=$((device_count+1)); done
for adapter_dir in "$DEV_DIR"/dvb/adapter[0-9]*; do
  [[ -d $adapter_dir ]] || continue
  for p in "$adapter_dir"/frontend[0-9]* "$adapter_dir"/demux[0-9]* "$adapter_dir"/dvr[0-9]*; do [[ -e $p && ! -d $p ]] && device_count=$((device_count+1)); done
done
if ((device_count==0)); then
  if command -v lsmod >/dev/null 2>&1 && lsmod | grep -q '^px4_drv'; then
    printf 'px4_drv はロード済みですがデバイスノードがありません。USB 接続、ファームウェア、対応機種を確認してください。\n'
  elif command -v modinfo >/dev/null 2>&1 && modinfo px4_drv >/dev/null 2>&1; then
    printf 'px4_drv は導入済みですがロードされていません。sudo modprobe px4_drv を実行して再確認してください。\n'
  else
    printf 'チューナーと px4_drv を検出できません。px4_drv の導入手順: https://github.com/tsukumijima/px4_drv#インストール-linux\n'
  fi
  printf 'recisdb-proxy の対応デバイス確認: https://github.com/stuayu/recisdb-proxy-rs#linux-へのインストール-コピペで完了\n'
  ask 'チューナーなしで続けますか (後から make tuners で追加できます)' 'はい'
  [[ $REPLY == はい || $REPLY == y || $REPLY == yes ]] || exit 1
else ok "$device_count 個のデバイスノードを検出"; fi

step 'BonCasRelay 接続先を設定'
oldhost=$(get BONCAS_B25_HOST 192.168.1.10); oldport=$(get BONCAS_B25_PORT 6900)
ask 'BonCasRelay ホスト名または IP' "${BONCAS_HOST:-$oldhost}"; host=$REPLY
ask 'BonCasRelay ポート' "${BONCAS_PORT:-$oldport}"; port=$REPLY
if [[ ! $port =~ ^[0-9]+$ ]] || ((port<=0 || port>=65536)); then fail 'ポート番号が不正です。' '1〜65535 の数字を指定してください。'; fi
if command -v python3 >/dev/null && ! python3 - "$host" "$port" <<'PY'
import socket,sys
try:
 s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=3); s.close()
except OSError: sys.exit(1)
PY
then
  echo 'BonCasRelay に接続できません。Relay 未起動、--allow に録画ホスト IP がない、ファイアウォールが原因候補です。カードホスト側の PC/SC・BonCasRelay の起動と許可設定も README の「ホスト機側の準備」で確認してください。'
  ip -brief -4 address 2>/dev/null || hostname -I 2>/dev/null || true
  ask '接続できないまま続けますか' 'はい'; [[ $REPLY == はい || $REPLY == y || $REPLY == yes ]] || fail '接続確認で中止しました。' 'BonCasRelay と LAN 設定を確認してください。'
fi
same_default=はい; [[ $(get BONCAS_4K_HOST "$host") == "$host" ]] || same_default=いいえ
ask '4K (ACAS) も同じ Relay を使いますか' "${BONCAS_4K_SAME:-$same_default}"; same=$REPLY
fourk=$host; fourkport=$port
if [[ $same != はい && $same != y && $same != yes ]]; then ask '4K BonCasRelay ホスト' "$(get BONCAS_4K_HOST "$host")"; fourk=$REPLY; ask '4K BonCasRelay ポート' "$(get BONCAS_4K_PORT 6900)"; fourkport=$REPLY; fi

step '録画先を設定'
ask '録画保存ディレクトリ' "${RECORDED_DIR:-$(get RECORDED_DIR ./data/recorded)}"; recorded=$REPLY
mkdir -p "$recorded" || fail "録画先を作成できません: $recorded" '書き込み権限とパスを確認してください。'
[[ -w $recorded ]] || fail "録画先へ書き込めません: $recorded" '所有者・グループ・権限を確認してください。'

step 'GPU・DB・ポートを設定'
gpu_default=none; [[ -d $DEV_DIR/dri ]] && gpu_default=intel; command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1 && gpu_default=nvidia
existing_compose=$(get COMPOSE_FILE compose.yaml:compose.tuners.yaml)
https_default=no; [[ $existing_compose == *compose.https.yaml* ]] && https_default=yes
[[ $existing_compose == *compose.intel.yaml* ]] && gpu_default=intel
[[ $existing_compose == *compose.nvidia.yaml* ]] && gpu_default=nvidia
ask 'GPU (none / intel = Intel/AMD /dev/dri / nvidia)' "${GPU:-$gpu_default}"; gpu=$REPLY
[[ $gpu == none || $gpu == intel || $gpu == nvidia ]] || fail 'GPU の選択が不正です。' 'none、intel、nvidia のいずれかを選択してください。'
if [[ $gpu == intel ]]; then
  render_node=''; for p in "$DEV_DIR"/dri/renderD*; do [[ -e $p ]] && render_node=$p && break; done
  if [[ -z $render_node ]]; then
    printf 'GPU を選びましたが %s/dri/renderD* がありません。GPU ドライバーと render グループを確認してください。\n' "$DEV_DIR"
    ask 'デバイスなしで続けますか' 'いいえ'
    [[ $REPLY == はい || $REPLY == y || $REPLY == yes ]] || fail 'Intel/AMD GPU デバイスを確認できません。' 'GPU を導入するか、GPU=none で再実行してください。'
  else
    render_gid=$(getent group render 2>/dev/null | awk -F: '{print $3}' || true)
    [[ -z $render_gid ]] || printf 'render グループ GID: %s (%s)\n' "$render_gid" "$render_node"
  fi
fi
if [[ $gpu == nvidia ]]; then
  nvidia_runtime=0
  if command -v nvidia-ctk >/dev/null 2>&1 && "$docker_cmd" info --format '{{json .Runtimes}}' 2>/dev/null | grep -q 'nvidia'; then nvidia_runtime=1; fi
  if (( ! nvidia_runtime )); then
    printf 'NVIDIA Container Toolkit または Docker NVIDIA runtime がありません。\n導入手順: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html\n確認: sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker\n'
    ask 'GPU 設定未完了のまま続けますか' 'いいえ'
    [[ $REPLY == はい || $REPLY == y || $REPLY == yes ]] || fail 'NVIDIA runtime を確認できません。' 'Toolkit を導入・設定後に再実行してください。'
  fi
fi
db_default=$(get SETUP_DB sqlite)
[[ $existing_compose == *compose.mariadb.yaml* || $(get COMPOSE_PROFILES '') == *mariadb* ]] && db_default=mariadb
ask 'EPGStation DB (sqlite / mariadb)' "${DB:-$db_default}"; db=$REPLY
[[ $db == sqlite || $db == mariadb ]] || fail 'DB の選択が不正です。' 'sqlite または mariadb を指定してください。'
ask 'recisdb-proxy Web ポート' "${RECISDB_WEB_PORT:-$(get RECISDB_WEB_PORT 40080)}"; p1=$REPLY
ask 'EPGStation ポート' "${EPGSTATION_PORT:-$(get EPGSTATION_PORT 8888)}"; p2=$REPLY
ask 'KonomiTV ポート' "${KONOMITV_PORT:-$(get KONOMITV_PORT 7000)}"; p3=$REPLY
ask 'HTTPS 経路を有効にしますか' "${HTTPS:-$https_default}"; https=$REPLY
[[ $https == yes || $https == はい || $https == y || $https == no || $https == いいえ || $https == n ]] || fail 'HTTPS の選択が不正です。' 'yes または no を指定してください。'
https_enabled=0; [[ $https == yes || $https == はい || $https == y ]] && https_enabled=1
p4=$(ask 'recisdb-proxy HTTPS ポート' "${RECISDB_HTTPS_PORT:-$(get RECISDB_HTTPS_PORT 40443)}"; printf '%s' "$REPLY")
p5=$(ask 'EPGStation HTTPS ポート' "${EPGSTATION_HTTPS_PORT:-$(get EPGSTATION_HTTPS_PORT 8443)}"; printf '%s' "$REPLY")
amatsukaze_default=$(get SETUP_AMATSUKAZE yes)
[[ $existing_compose != *compose.amatsukaze.yaml* ]] || amatsukaze_default=yes
ask 'Amatsukaze を使いますか (既定: はい)' "${AMATSUKAZE:-$amatsukaze_default}"; amatsukaze=$REPLY
case $amatsukaze in yes|はい|y) amatsukaze_enabled=1;; no|いいえ|n) amatsukaze_enabled=0;; *) fail 'Amatsukaze の選択が不正です。' 'yes または no を指定してください。';; esac
if ((amatsukaze_enabled)); then put SETUP_AMATSUKAZE yes; else put SETUP_AMATSUKAZE no; fi
amatsukaze_port=${AMATSUKAZE_WEBUI_PORT:-$(get AMATSUKAZE_WEBUI_PORT 32769)}
if ((amatsukaze_enabled)); then
  ask 'Amatsukaze WebUI ポート' "$amatsukaze_port"; amatsukaze_port=$REPLY
  uid_default=$(id -u); gid_default=$(id -g)
  if [[ $(get SETUP_AMATSUKAZE '') == yes || $existing_compose == *compose.amatsukaze.yaml* ]]; then
    uid_default=$(get RUN_UID "$uid_default"); gid_default=$(get RUN_GID "$gid_default")
  fi
  ask '録画・エンコードを実行する UID' "${RUN_UID:-$uid_default}"; run_uid=$REPLY
  ask '録画・エンコードを実行する GID' "${RUN_GID:-$gid_default}"; run_gid=$REPLY
  [[ $run_uid =~ ^[0-9]+$ && $run_gid =~ ^[0-9]+$ ]] || fail 'UID/GID が不正です。' 'id -u / id -g で確認した数値を指定してください。'
  ((run_uid > 0 && run_gid > 0)) || fail 'UID/GID は 0 以外を指定してください。' '録画先に書ける一般ユーザーの ID を指定してください。'
  put RUN_UID "$run_uid"; put RUN_GID "$run_gid"
  printf '録画先 %s の所有者・権限を UID=%s GID=%s に合わせてください。既存録画の所有権は自動変更しません。\n' "$recorded" "$run_uid" "$run_gid"
fi
put AMATSUKAZE_WEBUI_PORT "$amatsukaze_port"

relay_port=$port
for port in "$p1" "$p2" "$p3" "$p4" "$p5" "$amatsukaze_port"; do
  if [[ ! $port =~ ^[0-9]+$ ]] || ((port<=0 || port>=65536)); then fail 'ポート番号が不正です。' '1〜65535 の数字を指定してください。'; fi
done
compose=compose.yaml:compose.tuners.yaml; [[ $gpu == intel ]] && compose+=:compose.intel.yaml; [[ $gpu == nvidia ]] && compose+=:compose.nvidia.yaml; [[ $db == mariadb ]] && compose+=:compose.mariadb.yaml; ((https_enabled)) && compose+=:compose.https.yaml
if ((amatsukaze_enabled)); then
  compose+=:compose.amatsukaze.yaml
  [[ $gpu == intel ]] && compose+=:compose.amatsukaze.intel.yaml
  [[ $gpu == nvidia ]] && compose+=:compose.amatsukaze.nvidia.yaml
fi
# Correct the obsolete fork branch while preserving custom refs.
if [[ $(get EPGSTATION_REF main) == master ]]; then put EPGSTATION_REF main; echo 'EPGSTATION_REF=master を main に更新します。'; fi
put COMPOSE_FILE "$compose"; put BONCAS_B25_HOST "$host"; put BONCAS_B25_PORT "$relay_port"; put BONCAS_4K_HOST "$fourk"; put BONCAS_4K_PORT "$fourkport"
put RECORDED_DIR "$recorded"; put RECISDB_WEB_PORT "$p1"; put EPGSTATION_PORT "$p2"; put KONOMITV_PORT "$p3"
put RECISDB_HTTPS_PORT "$p4"; put EPGSTATION_HTTPS_PORT "$p5"; put AKEBI_KEYLESS_SERVER_URL "${AKEBI_KEYLESS_SERVER_URL:-$(get AKEBI_KEYLESS_SERVER_URL https://akebi.konomi.tv/)}"
if [[ $db == mariadb ]]; then put COMPOSE_PROFILES mariadb; else put COMPOSE_PROFILES ''; fi
video_gid=''
if [[ $gpu == intel ]]; then video_gid=$(getent group render 2>/dev/null | awk -F: '{print $3}' || true); fi
[[ -n $video_gid ]] || video_gid=$(getent group video 2>/dev/null | awk -F: '{print $3}' || true)
if [[ -z $video_gid && $gpu == intel && -n ${render_node:-} ]]; then video_gid=$(stat -c '%g' "$render_node" 2>/dev/null || true); fi
put VIDEO_GID "${video_gid:-44}"
put SETUP_DB "$db"
if [[ $db == mariadb ]]; then
  mariadb_password=$(get MARIADB_PASSWORD ''); root_password=$(get MARIADB_ROOT_PASSWORD '')
  [[ -n $mariadb_password && $mariadb_password != change-me ]] || mariadb_password=$(openssl rand -hex 24)
  [[ -n $root_password && $root_password != change-me-too ]] || root_password=$(openssl rand -hex 24)
  put MARIADB_PASSWORD "$mariadb_password"; put MARIADB_ROOT_PASSWORD "$root_password"
fi

step '環境設定・ディレクトリ・チューナー Compose を生成'
if [[ ! -f $ENV_FILE ]]; then cp .env.example "$ENV_FILE"; fi
if [[ -s $SETTINGS_FILE ]]; then
  if [[ -f $ENV_FILE ]]; then stamp=$(date +%Y%m%d%H%M%S%N); cp -p "$ENV_FILE" "$ENV_FILE.bak.$stamp"; fi
  tmp=$(mktemp); cp "$ENV_FILE" "$tmp"
  while IFS='=' read -r key value; do if grep -q "^${key}=" "$tmp"; then awk -v key="$key" -v value="$value" 'BEGIN{FS=OFS="="} $1==key {$0=key OFS value} {print}' "$tmp" > "$tmp.next"; mv "$tmp.next" "$tmp"; else printf '%s=%s\n' "$key" "$value" >> "$tmp"; fi; done < "$SETTINGS_FILE"
  mv "$tmp" "$ENV_FILE"
fi
mkdir -p data/recisdb data/epgstation data/epgstation-logs data/epgstation-thumbnail data/epgstation-drop data/konomitv data/konomitv-logs data/mariadb
if ((amatsukaze_enabled)); then
  for dir in avs bat config data drcs JL logo profile input output; do mkdir -p "data/amatsukaze/$dir"; done
fi
DEV_DIR="$DEV_DIR" TUNERS_COMPOSE_FILE="$COMPOSE_TUNERS" ./scripts/gen-tuners.sh >/dev/null || fail 'チューナー Compose を生成できません。' 'scripts/gen-tuners.sh の権限と出力先を確認してください。'
source_path=$(get KONOMITV_SOURCE ../KonomiTV); source_path=${KONOMITV_SOURCE:-$source_path}; [[ $source_path = /* ]] || source_path="$ROOT/$source_path"
if [[ ! -f $source_path/Dockerfile ]]; then
  ask "KonomiTV ソースがありません。$source_path に clone しますか" 'はい'
  [[ $REPLY == はい || $REPLY == y || $REPLY == yes ]] || fail 'KonomiTV ソースが必要です。' 'KONOMITV_SOURCE に Dockerfile を含むフォークのパスを指定してください。'
  git clone https://github.com/stuayu/KonomiTV.git "$source_path" || fail 'KonomiTV の clone に失敗しました。' 'ネットワークと保存先の権限を確認してください。'
fi
ok '.env とデータ領域を準備'

if ((amatsukaze_enabled)); then
  printf 'Amatsukaze WebUI: http://<録画ホストIP>:%s/\nEPGStation のエンコード設定に Amatsukaze を自動追加します。初回起動で EPGStation プロファイルを作成します。\nWebUI で局別ロゴを登録し、サービス設定の CM 解析無効を解除してから録画のエンコードを選択してください。\n' "$amatsukaze_port"
fi
if ((RECONFIGURE)); then echo '設定を更新しました。反映には make build && make up を実行してください。'; exit 0; fi
if ((NO_BUILD)); then echo 'ビルドを省略しました。'; else
  step 'Compose 設定を検証'
  "$docker_cmd" compose config >/dev/null || fail 'docker compose config が失敗しました。' '.env、Compose ファイル、KonomiTV_SOURCE を確認してください。'
  step 'Docker イメージをビルド (数分以上かかる場合があります)'
  "$docker_cmd" compose build || fail 'Docker イメージのビルドに失敗しました。' 'ログの最初のエラー、空き容量、ネットワークを確認してください。'
fi
if ((NO_START)); then echo '起動を省略しました。docker compose up -d で起動できます。'; exit 0; fi
step 'コンテナを起動'
"$docker_cmd" compose up -d || fail 'コンテナ起動に失敗しました。' 'docker compose logs と docker compose ps で原因を確認してください。'
step 'サービスの起動を待機'
ipaddr=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}' || true)
[[ -n $ipaddr ]] || ipaddr=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
[[ -n $ipaddr ]] || ipaddr=localhost
deadline=$((SECONDS+180)); services_ready=0; http_ready=0
konomi_host=${ipaddr//./-}.local.konomi.tv
while ((SECONDS<deadline)); do
  running_services=$("$docker_cmd" compose ps --status running --services 2>/dev/null || true)
  if grep -qx recisdb-proxy <<<"$running_services" && grep -qx epgstation <<<"$running_services" && grep -qx konomitv <<<"$running_services" && { (( ! amatsukaze_enabled )) || grep -qx amatsukaze <<<"$running_services"; }; then
    services_ready=1
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS --max-time 3 "http://127.0.0.1:$p1/mirakurun/api/status" >/dev/null 2>&1 && curl -fsS --max-time 3 "http://127.0.0.1:$p2/" >/dev/null 2>&1 && curl --resolve "$konomi_host:$p3:127.0.0.1" -fsS --max-time 3 "https://$konomi_host:$p3/" >/dev/null 2>&1; then
        if { (( ! amatsukaze_enabled )) || curl -fsS --max-time 3 "http://127.0.0.1:$amatsukaze_port/" >/dev/null 2>&1; } && { (( ! https_enabled )) || { curl --resolve "$konomi_host:$p4:127.0.0.1" -fsS --max-time 3 "https://$konomi_host:$p4/" >/dev/null 2>&1 && curl --resolve "$konomi_host:$p5:127.0.0.1" -fsS --max-time 3 "https://$konomi_host:$p5/" >/dev/null 2>&1; }; }; then http_ready=1; break; fi
      fi
    else printf 'curl がないため HTTP 応答確認を省略します。必要なら curl を導入して再確認してください。\n'; http_ready=1; break; fi
  fi
  sleep 3
done
if ((services_ready && http_ready)); then ok '選択したサービスの起動と HTTP 応答を確認'; else echo 'サービス起動または HTTP 応答がタイムアウトしました。docker compose ps / logs を確認してください。'; fi
step 'アクセス先と次の作業'
printf 'recisdb-proxy HTTP: http://%s:%s/\nEPGStation HTTP: http://%s:%s/\nKonomiTV HTTPS: https://%s:%s/\n' "$ipaddr" "$p1" "$ipaddr" "$p2" "$konomi_host" "$p3"
if ((amatsukaze_enabled)); then printf 'Amatsukaze WebUI: http://%s:%s/\n' "$ipaddr" "$amatsukaze_port"; fi
if ((https_enabled)); then printf 'recisdb-proxy HTTPS: https://%s:%s/\nEPGStation HTTPS: https://%s:%s/\n' "$konomi_host" "$p4" "$konomi_host" "$p5"; fi
printf 'BonCasRelay Web 設定: カードホスト上で http://127.0.0.1:6980/\n'
token=$("$docker_cmd" compose logs --no-color recisdb-proxy 2>/dev/null | sed -n 's/.*Web API auth token: *//p' | tail -n1 || true)
[[ -z $token ]] || printf '初回ダッシュボード token: %s\n' "$token"
printf '次にやること:\n1. recisdb-proxy の BonDriver 画面でチューナー登録・チャンネルスキャン。\n2. EPG 取得を待ち、EPGStation で番組表と予約を確認。\n3. KonomiTV で初期設定し、ライブ視聴を確認。\n'
