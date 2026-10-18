#!/usr/bin/env bash
# Restore an archive made by scripts/backup.sh. Confirms before overwriting config/ and data/.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
DOCKER_BIN=${DOCKER_BIN:-docker}
fail(){ printf 'エラー: %s\n対処: %s\n' "$1" "$2" >&2; exit 1; }

archive=${1:-}
[[ -n $archive && -f $archive ]] || fail 'バックアップファイルを指定してください。' 'make restore FILE=backup/konomi-backup-YYYYmmdd-HHMMSS.tar.gz'
if [[ ${YES:-0} != 1 ]]; then
  [[ -t 0 ]] || fail '対話できないため中止しました。' '確認後に YES=1 を付けて再実行してください。'
  read -r -p "config/ と data/ を $archive の内容で上書きします。続けますか [y/N] " answer
  [[ $answer == y || $answer == Y ]] || { echo '中止しました。'; exit 1; }
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
tar -xzf "$archive" -C "$work"
[[ -f $work/db/epgstation.sql ]] || fail 'アーカイブに db/epgstation.sql がありません。' '対応する backup.sh で作成したファイルか確認してください。'

"$DOCKER_BIN" compose stop >/dev/null 2>&1 || true
[[ -d $work/config ]] && { mkdir -p config; cp -a "$work/config/." config/; }
[[ -d $work/data ]] && { mkdir -p data; cp -a "$work/data/." data/; }
if [[ -f $work/.env ]]; then
  if [[ -f .env ]]; then
    printf '既存の .env は変更していません。アーカイブの .env は %s に保存しました。\n' "$ROOT/.env.from-archive"
    cp "$work/.env" "$ROOT/.env.from-archive"
    printf '必要なら .env の DB パスワードを確認してください。\n'
  else
    cp -p "$work/.env" .env
  fi
fi

"$DOCKER_BIN" compose up -d mariadb
for _ in $(seq 1 60); do
  # shellcheck disable=SC2016 # expands inside the container
  if "$DOCKER_BIN" compose exec -T mariadb sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "SELECT 1"' >/dev/null 2>&1; then break; fi
  sleep 2
done
# shellcheck disable=SC2016 # expands inside the container
"$DOCKER_BIN" compose exec -T mariadb sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD"' < "$work/db/epgstation.sql" \
  || fail 'MariaDB への復元に失敗しました。' 'docker compose logs mariadb を確認してください。'
"$DOCKER_BIN" compose up -d
echo 'リストアが完了しました。'
