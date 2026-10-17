.PHONY: config tuners build up down logs

config:
	cp -n .env.example .env || true
	mkdir -p data/recisdb data/epgstation data/epgstation-logs data/epgstation-thumbnail data/epgstation-drop data/konomitv data/konomitv-logs data/recorded data/mariadb

tuners:
	./scripts/gen-tuners.sh

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100
