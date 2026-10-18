#!/usr/bin/env bash
# shellcheck disable=SC2034
# Sourced by setup.sh. All privileged operations pass through confirm_sudo.
TUI='' ADVANCED_PORTS=1
truth(){ [[ $1 == yes || $1 == はい || $1 == y || $1 == Y ]]; }
ui(){ "$TUI" --title '録画・視聴セットアップ' "$@"; }
message(){ if [[ -n $TUI ]]; then ui --msgbox "$*" 22 76; else printf '%s\n' "$*"; fi; }
confirm(){
  local text=$1 default=${2:-no} answer
  if [[ -n $TUI ]]; then
    if truth "$default"; then ui --yesno "$text" 22 76; else ui --defaultno --yesno "$text" 22 76; fi
  elif ((YES || NONINTERACTIVE)); then truth "$default"
  else read -r -p "$text [y/N]: " answer; truth "$answer"; fi
}
confirm_sudo(){
  local rendered
  printf -v rendered '%q ' sudo "$@"
  printf '実行内容: %s\n' "$rendered"
  if (( ! AUTO_INSTALL )); then
    # --yes must never approve privileged work, including chown or service changes.
    (( ! YES && ! NONINTERACTIVE )) || return 1
    confirm "$rendered を実行しますか？" no || return 1
  fi
  sudo "$@"
}
debian_host(){
  # shellcheck disable=SC1090,SC1091
  source "${OS_RELEASE_FILE:-/etc/os-release}"
  [[ ${ID:-} == debian || ${ID:-} == ubuntu ]]
}
init_ui(){
  ((YES || NONINTERACTIVE)) && return 0
  [[ -t 1 ]] || return 0
  TUI=$(command -v whiptail || command -v dialog || true)
  if [[ -z $TUI ]] && debian_host; then
    if confirm_sudo apt-get install -y whiptail; then TUI=$(command -v whiptail || true); fi
  fi
  [[ -z $TUI ]] || message 'ようこそ。環境確認、ソフト選択、録画先、カードサーバー、GPU とポートを設定します。設定は約 5 分、初回ビルドは数十分かかる場合があります。キャンセルで中止します。'
}
ui_ask(){
  local prompt=$1 default=$2
  case $prompt in
    'HTTPS 経路を有効にしますか') REPLY=$HTTPS; return;;
    'Amatsukaze を使いますか (既定: はい)') REPLY=$AMATSUKAZE; return;;
    'EDCB を使いますか (既定: はい)') REPLY=$EDCB; return;;
    'GPU (none / intel = Intel/AMD /dev/dri / nvidia)')
      REPLY=$(ui --default-item "$default" --menu 'GPU を確認' 16 76 4 none 'ソフトウェア' intel 'Intel / AMD (/dev/dri)' nvidia 'NVIDIA' 3>&1 1>&2 2>&3) || exit 1
      return;;
  esac
  if [[ $prompt == *ポート* && $ADVANCED_PORTS == 0 ]]; then REPLY=$default; return; fi
  case $default in
    yes|no|はい|いいえ)
      if confirm "$prompt" "$default"; then REPLY=yes; else REPLY=no; fi;;
    *) REPLY=$(ui --inputbox "$prompt" 12 76 "$default" 3>&1 1>&2 2>&3) || exit 1;;
  esac
}
select_software(){
  [[ -n $TUI ]] || return 0
  local selected args=() key value
  for key in EDCB AMATSUKAZE HTTPS; do
    case $key in EDCB) value=${EDCB:-$(get SETUP_EDCB yes)};; AMATSUKAZE) value=${AMATSUKAZE:-$(get SETUP_AMATSUKAZE yes)};; HTTPS) value=${HTTPS:-yes}; [[ $(get COMPOSE_FILE compose.https.yaml) == *compose.https.yaml* ]] || value=no;; esac
    if truth "$value"; then value=ON; else value=OFF; fi
    args+=("$key" "$key" "$value")
  done
  selected=$(ui --checklist '使うソフト (Space で選択)' 18 76 6 "${args[@]}" 3>&1 1>&2 2>&3) || exit 1
  EDCB=no AMATSUKAZE=no HTTPS=no
  [[ $selected != *EDCB* ]] || EDCB=yes
  [[ $selected != *AMATSUKAZE* ]] || AMATSUKAZE=yes
  [[ $selected != *HTTPS* ]] || HTTPS=yes
}
select_storage(){
  local default=${RECORDED_DIR:-$(get RECORDED_DIR ./data/recorded)} selected path details tag value choice free owner
  local args=() paths=() candidates=() descriptions=() line
  if [[ -n ${RECORDED_DIRS_JSON:-} ]]; then
    while IFS= read -r path; do [[ -z $path ]] || paths+=("$path"); done < <(python3 -c 'import json,sys; print("\n".join(json.loads(sys.argv[1])))' "$RECORDED_DIRS_JSON")
    [[ ${#paths[@]} -gt 0 ]] || paths=("$default")
  elif [[ -z ${RECORDED_DIR:-} || -n $TUI ]]; then
    paths=("$default")
    while IFS= read -r path; do [[ -z $path || $path == "$default" ]] || paths+=("$path"); done < <(python3 -c 'import json,sys; print("\n".join(json.loads(sys.argv[1])))' "$(get RECORDED_DIRS_JSON '[]')")
  else paths=("$default"); fi
  if [[ -n $TUI ]]; then
    candidates=("${paths[@]}")
    while IFS=$'\t' read -r path details; do
      [[ -n $path ]] || continue
      value=0; for line in "${candidates[@]}"; do [[ $line != "$path" ]] || value=1; done
      if (( ! value )); then candidates+=("$path"); descriptions[${#candidates[@]}-1]=$details; fi
    done < <(python3 "$ROOT/scripts/storage.py" candidates)
    for ((tag=0; tag<${#candidates[@]}; tag++)); do
      path=${candidates[$tag]}; value=OFF
      for line in "${paths[@]}"; do [[ $line != "$path" ]] || value=ON; done
      details=${descriptions[$tag]:-}
      [[ -n $details ]] || details=$(df -Pk "$path" 2>/dev/null | awk 'NR==2 {printf "空き %.1f GB", $4*1024/1000000000}' || true)
      args+=("$tag" "$path $details" "$value")
    done
    selected=$(ui --checklist '録画先を複数選択。先頭が既定。その他のフォルダーは次の画面。' 22 78 12 "${args[@]}" other 'その他のフォルダーを選ぶ…' OFF 3>&1 1>&2 2>&3) || exit 1
    paths=()
    for ((tag=0; tag<${#candidates[@]}; tag++)); do
      [[ " $selected " == *"\"$tag\""* || " $selected " == *" $tag "* ]] && paths+=("${candidates[$tag]}")
    done
    if [[ $selected == *other* ]]; then
      while :; do
        if [[ ${TUI##*/} == dialog ]]; then path=$(ui --dselect "$default/" 20 76 3>&1 1>&2 2>&3) || exit 1
        else path=$(ui --inputbox '録画先フォルダー (絶対パスまたは ./ からの相対パス)' 12 76 "$default" 3>&1 1>&2 2>&3) || exit 1; fi
        paths+=("$path")
        confirm '別のフォルダーも追加しますか？' no || break
      done
    fi
    ((${#paths[@]})) || fail '録画先が選ばれていません。' '1 つ以上選んでください。'
    if ((${#paths[@]}>1)); then
      args=(); for ((tag=0; tag<${#paths[@]}; tag++)); do args+=("$tag" "${paths[$tag]}"); done
      choice=$(ui --menu '既定の録画先を選択' 20 76 10 "${args[@]}" 3>&1 1>&2 2>&3) || exit 1
      path=${paths[$choice]}; unset 'paths[choice]'; paths=("$path" "${paths[@]}")
    fi
  elif [[ -z ${RECORDED_DIRS_JSON:-} ]]; then
    ask '録画保存ディレクトリ' "$default"; if [[ $REPLY != "$default" ]]; then paths=("$REPLY"); fi
  fi
  for path in "${paths[@]}"; do
    [[ -n $path && $path != *'$'* && $path != *$'\n'* && $path != *$'\r'* ]] || fail '録画先の文字が不正です。' '改行と $ は使用できません。'
    if [[ ! -d $path ]]; then
      confirm "録画先を作成しますか？ $path" yes || exit 1
      mkdir -p -- "$path" || fail "録画先を作成できません: $path" '親ディレクトリの権限を確認してください。'
    fi
    owner=$(stat -c '%u:%g' "$path" 2>/dev/null || stat -f '%u:%g' "$path")
    printf '録画先: %s 所有者: %s 実行 UID:GID: %s:%s\n' "$path" "$owner" "$(id -u)" "$(id -g)"
    if [[ ! -w $path ]]; then
      confirm_sudo chown "${RUN_UID:-$(get RUN_UID "$(id -u)")}:${RUN_GID:-$(get RUN_GID "$(id -g)")}" "$path" || fail "録画先へ書き込めません: $path" '権限を確認してください。'
      [[ -w $path ]] || fail "録画先へ書き込めません: $path" 'UID/GID と ACL を確認してください。'
    fi
    free=$(df -Pk "$path" | awk 'NR==2 {print $4}')
    if [[ $free =~ ^[0-9]+$ ]] && ((free<97656250)); then
      message "$path の空き容量は 100 GB 未満です。"
      confirm 'この録画先で続けますか？' yes || exit 1
    fi
  done
  recorded=${paths[0]}
  storage_json=$(python3 -c 'import json,sys; print(json.dumps(list(dict.fromkeys(sys.argv[1:]))))' "${paths[@]}")
}
run_logged(){
  local status pid
  mkdir -p "$ROOT/data/setup-logs"
  LOG_FILE="$ROOT/data/setup-logs/$(date +%Y%m%d-%H%M%S)-$1.log"; shift
  if [[ -n $TUI ]]; then
    "$@" >"$LOG_FILE" 2>&1 & pid=$!
    { while kill -0 "$pid" 2>/dev/null; do printf 'XXX\n50\n処理中。ログ: %s\nXXX\n' "$LOG_FILE"; sleep 1; done; echo 100; } | ui --gauge '処理中' 10 76 0 || true
    if wait "$pid"; then status=0; else status=$?; fi
  else
    if "$@" 2>&1 | tee "$LOG_FILE"; then status=0; else status=$?; fi
  fi
  if ((status)); then message "失敗しました。ログ: $LOG_FILE"; return "$status"; fi
}
