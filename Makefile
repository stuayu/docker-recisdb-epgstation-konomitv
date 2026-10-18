.PHONY: setup status update test config tuners build up down logs

setup:
	./setup.sh

status:
	docker compose ps
	@host=$$(hostname -I 2>/dev/null | awk '{print $$1}'); [ -n "$$host" ] || host=localhost; \
	. ./.env; printf 'recisdb-proxy HTTP: http://%s:%s/\nEPGStation HTTP: http://%s:%s/\nKonomiTV HTTPS: https://%s:%s/\n' "$$host" "$$RECISDB_WEB_PORT" "$$host" "$$EPGSTATION_PORT" "$$(printf '%s' "$$host" | tr '.' '-')" "$$KONOMITV_PORT"; \
	case ":$$COMPOSE_FILE:" in *:compose.https.yaml:*) printf 'recisdb-proxy HTTPS: https://%s:%s/\nEPGStation HTTPS: https://%s:%s/\n' "$$(printf '%s' "$$host" | tr '.' '-')" "$$RECISDB_HTTPS_PORT" "$$(printf '%s' "$$host" | tr '.' '-')" "$$EPGSTATION_HTTPS_PORT";; esac

update:
	@source=$$(sed -n 's/^KONOMITV_SOURCE=//p' .env | tail -n1); \
	[ -n "$$source" ] || source=../KonomiTV; \
	git -C "$$source" pull --ff-only
	docker compose build
	docker compose up -d

test:
	bash tests/setup_test.sh

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
