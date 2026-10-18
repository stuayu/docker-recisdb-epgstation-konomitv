.PHONY: setup status update test config tuners build up down logs edcb-chset

setup:
	./setup.sh

status:
	docker compose ps
	@host=$$(hostname -I 2>/dev/null | awk '{print $$1}'); [ -n "$$host" ] || host=localhost; \
	. ./.env; printf 'recisdb-proxy HTTP: http://%s:%s/\nEPGStation HTTP: http://%s:%s/\nKonomiTV HTTPS: https://%s:%s/\n' "$$host" "$$RECISDB_WEB_PORT" "$$host" "$$EPGSTATION_PORT" "$$(printf '%s' "$$host" | tr '.' '-')" "$$KONOMITV_PORT"; \
	case ":$$COMPOSE_FILE:" in *:compose.https.yaml:*) printf 'recisdb-proxy HTTPS: https://%s:%s/\nEPGStation HTTPS: https://%s:%s/\n' "$$(printf '%s' "$$host" | tr '.' '-')" "$$RECISDB_HTTPS_PORT" "$$(printf '%s' "$$host" | tr '.' '-')" "$$EPGSTATION_HTTPS_PORT";; esac; \
	case ":$$COMPOSE_FILE:" in *:compose.edcb.yaml:*) printf 'EDCB WebUI: http://%s:%s/EMWUI/\n' "$$host" "$${EDCB_WEB_PORT:-5510}";; esac; \
	case ":$$COMPOSE_FILE:" in *:compose.edcb.https.yaml:*) printf 'EDCB HTTPS: https://%s:%s/EMWUI/\n' "$$(printf '%s' "$$host" | tr '.' '-')" "$${EDCB_HTTPS_PORT:-8553}";; esac; \
	case ":$$COMPOSE_FILE:" in *:compose.amatsukaze.yaml:*) printf 'Amatsukaze WebUI: http://%s:%s/\n' "$$host" "$${AMATSUKAZE_WEBUI_PORT:-32769}";; esac

update:
	@source=$$(sed -n 's/^KONOMITV_SOURCE=//p' .env | tail -n1); \
	[ -n "$$source" ] || source=../KonomiTV; \
	git -C "$$source" pull --ff-only
	docker compose pull mariadb
	docker compose build
	docker compose up -d

test:
	bash tests/setup_test.sh
	python3 tests/edcb_test.py

config:
	./setup.sh --reconfigure

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

edcb-chset:
	./scripts/edcb-chset.sh
