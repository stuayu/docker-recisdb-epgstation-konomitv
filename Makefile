.PHONY: setup status update test config tuners tuners-prune scan build up down logs edcb-chset regen-config backup restore storage

storage:
	./setup.sh --storage-only

setup:
	./setup.sh

status:
	docker compose ps
	python3 scripts/status.py

update:
	@source=$$(sed -n 's/^KONOMITV_SOURCE=//p' .env | tail -n1); \
	[ -n "$$source" ] || source=../KonomiTV; \
	git -C "$$source" pull --ff-only
	python3 scripts/render-config.py --root . --env .env first-run
	docker compose pull mariadb
	docker compose build
	docker compose up -d

test:
	bash tests/setup_test.sh
	python3 tests/edcb_test.py
	python3 tests/config_test.py
	python3 tests/review_test.py
	python3 tests/tuner_setup_test.py
	python3 tests/dashboard_test.py

config:
	./setup.sh --reconfigure

tuners:
	python3 scripts/tuner-setup.py register

tuners-prune:
	python3 scripts/tuner-setup.py prune $(if $(filter 1 yes true,$(YES)),--yes,)

scan:
	python3 scripts/tuner-setup.py scan

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

edcb-chset:
	./scripts/edcb-chset.sh

# 設定ファイルを再生成する。現在のファイルは config/<サービス>/backup/ に退避し、差分を表示してから置き換える。
regen-config:
	@test -n "$(SERVICE)" || { echo 'SERVICE=recisdb-proxy | epgstation | konomitv | edcb | amatsukaze | boncasrelay | edcb-to-epgstation を指定してください (例: make regen-config SERVICE=epgstation)' >&2; exit 2; }
	@if [ "$(SERVICE)" = amatsukaze ]; then python3 scripts/regen-amatsukaze.py; else python3 scripts/render-config.py --root . --env .env regen --service "$(SERVICE)"; fi

# config/ と data/ (録画ファイルと MariaDB の生ファイルを除く) を日時付き tar.gz にまとめる。
backup:
	./scripts/backup.sh

# make restore FILE=backup/konomi-backup-YYYYmmdd-HHMMSS.tar.gz
restore:
	@test -n "$(FILE)" || { echo 'FILE=バックアップファイルを指定してください' >&2; exit 2; }
	./scripts/restore.sh "$(FILE)"
