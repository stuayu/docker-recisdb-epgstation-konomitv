#!/usr/bin/env bash
# Archive config/ and data/ (MariaDB as a SQL dump, recorded files excluded) into a dated tar.gz.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
DOCKER_BIN=${DOCKER_BIN:-docker}
ENV_FILE=${ENV_FILE:-$ROOT/.env}
BACKUP_DIR=${BACKUP_DIR:-$ROOT/backup}
fail(){ printf 'エラー: %s\n対処: %s\n' "$1" "$2" >&2; exit 1; }

[[ -f $ENV_FILE ]] || fail '.env がありません。' 'setup.sh を先に実行してください。'
recorded=$(sed -n 's/^RECORDED_DIR=//p' "$ENV_FILE" | tail -n1)
recorded=${recorded:-./data/recorded}
recorded=${recorded#./}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/db"
# The quoted command runs inside the container, where MARIADB_ROOT_PASSWORD is set.
# shellcheck disable=SC2016
"$DOCKER_BIN" compose exec -T mariadb sh -c 'mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --single-transaction --databases epgstation' > "$work/db/epgstation.sql" \
  || fail 'MariaDB のダンプに失敗しました。' 'docker compose up -d mariadb で起動してから再実行してください。'
[[ -s $work/db/epgstation.sql ]] || fail 'MariaDB のダンプが空です。' 'docker compose ps で mariadb が起動しているか確認してください。'

mkdir -p "$BACKUP_DIR"
archive="$BACKUP_DIR/konomi-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
excludes=(--exclude='data/mariadb' --exclude='data/mariadb/*')
# Every selected storage beneath the repository is excluded, including paths with spaces.
storage_exclusions=$(python3 - "$ROOT" "$ENV_FILE" <<'PYSTORAGE'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from storage import directories
from importlib.util import module_from_spec, spec_from_file_location
root = Path(sys.argv[1]).resolve()
spec = spec_from_file_location('render', root / 'scripts/render-config.py')
render = module_from_spec(spec); spec.loader.exec_module(render)
for directory in directories(render.read_env(Path(sys.argv[2]))):
    path = (root / directory).resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        continue
    if relative == Path('.'):
        raise SystemExit('リポジトリ全体を録画先に指定できません。')
    print(relative)
PYSTORAGE
) || fail '録画先の除外リストを作成できません。' '.env の録画先を確認してください。'
while IFS= read -r storage; do
  [[ -n $storage ]] || continue
  excludes+=(--exclude="$storage" --exclude="$storage/*")
done <<< "$storage_exclusions"
# .env holds the database passwords that the config and the dump depend on.
# Include generated storage mounts so restore can recreate additional bindings.
optional=(); [[ ! -f compose.storage.yaml ]] || optional+=(compose.storage.yaml)
tar -czf "$archive" "${excludes[@]}" -C "$ROOT" .env config data "${optional[@]}" -C "$work" db
printf '%s\n' "バックアップを作成しました: $archive"
printf '%s\n' '含めたもの: .env, config/, data/ (MariaDB は db/epgstation.sql のダンプ)'
printf '%s\n' "含めないもの: 録画ファイル ($recorded)、data/mariadb の生ファイル"
