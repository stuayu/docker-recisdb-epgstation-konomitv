#!/usr/bin/env bash
# shellcheck disable=SC2034
# Sourced environment inventory and optional installation; no sudo during detection.
installed(){ command -v "$1" >/dev/null 2>&1; }
offer_install(){
  local component=$1
  if ! debian_host; then message "自動導入は Debian / Ubuntu 専用です。docs/ADVANCED.md の「不足ソフトの判定と導入の根拠」を参照してください。"; return 1; fi
  # Show the actual versioned recipe, including repository writes and service restart.
  printf '\n導入手順 (%s):\n' "$component"
  cat "$ROOT/scripts/install-host.sh"
  [[ -z $TUI ]] || ui --textbox "$ROOT/scripts/install-host.sh" 22 76
  confirm_sudo bash "$ROOT/scripts/install-host.sh" "$component"
}
card_reader_detected(){
  # USB CCID interface class is decimal 11 (0x0b). Avoid guessing vendor IDs.
  if installed lsusb; then
    local usb
    usb=$(lsusb -v 2>/dev/null || true)
    grep -Eq 'bInterfaceClass[[:space:]]+11([[:space:]]|$)|Chip/SmartCard' <<<"$usb" && return 0
  fi
  if installed pcsc_scan && installed timeout; then
    local scan
    scan=$(timeout 3 pcsc_scan -r 2>/dev/null || true)
    [[ $scan =~ [0-9]+:[[:space:]] ]] && return 0
  fi
  return 1
}
tuner_nodes_exist(){
  local node
  for node in "$DEV_DIR"/px4video* "$DEV_DIR"/pt3video* "$DEV_DIR"/pxmlt*video* "$DEV_DIR"/pxm1urvideo* "$DEV_DIR"/pxs1urvideo* "$DEV_DIR"/isdb2056video* "$DEV_DIR"/isdbt2071video* "$DEV_DIR"/dvb/adapter*/frontend*; do
    [[ ! -e $node || -d $node ]] || return 0
  done
  return 1
}
known_tuner_usb(){
  # px4_drv driver/px4_usb.h and px4_usb.c USB table (VID 0511).
  installed lsusb && lsusb | grep -Eiq '0511:(083f|084a|023f|024a|073f|074a|084e|024e|0252|0253|004b|084b|0254|924e|0854|0855|0052)'
}
host_inventory(){
  local report='' text
  if installed docker && docker compose version >/dev/null 2>&1; then text='Docker / Compose: 導入済み ✓'; else text='Docker / Compose: 未導入'; fi
  report+="$text"$'\n'
  if tuner_nodes_exist; then text='チューナー: デバイス検出 ✓'; else text='チューナー: 未検出'; fi
  report+="$text"$'\n'
  if installed modinfo && modinfo px4_drv >/dev/null 2>&1; then text='px4_drv: 導入済み ✓'; else text='px4_drv: 未検出'; fi
  report+="$text"$'\n'
  text=$(lspci 2>/dev/null | grep -Ei 'VGA|3D|Display' || true)
  report+="GPU: ${text:-未検出}"$'\n'
  if card_reader_detected; then CARD_DETECTED=1; text='カードリーダー: 検出 ✓'; else CARD_DETECTED=0; text='カードリーダー: 未検出 (手動で同梱を選択可能)'; fi
  report+="$text"$'\n'
  text=$(ufw status 2>/dev/null || true)
  if [[ $text != *'Status: active'* ]] && grep -Eq '^[[:space:]]*ENABLED=yes' "${UFW_CONFIG_FILE:-/etc/ufw/ufw.conf}" 2>/dev/null; then
    text='Status: active (ufw.conf の ENABLED=yes。実行時状態は管理者が確認)'
  fi
  report+="ファイアウォール: ${text:-状態不明 (権限が必要な場合は管理者が確認)}"
  message "$report"
  if [[ $text == *'Status: active'* ]]; then message 'UFW 有効。Docker 公開ポートは UFW を迂回します。docs/ADVANCED.md の「録画ホストのファイアウォール」にある DOCKER-USER / ルーター ACL を確認してください。同梱 BonCasRelay の 6900 はホスト非公開、6980 はループバック限定です。'; fi
}
