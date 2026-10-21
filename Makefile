.PHONY: help dev up down build logs ps backup restore verify test lint

help: ## показать команды
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

dev: ## поднять стек (пустая БД + есть бэкап = автовосстановление)
	./backend/scripts/dev.sh

up: ## поднять стек
	docker compose up -d

down: ## остановить стек
	docker compose down

build: ## пересобрать и поднять стек
	docker compose up -d --build

logs: ## логи всех сервисов
	docker compose logs -f

ps: ## статус сервисов
	docker compose ps

backup: ## бэкап БД+файлов -> ./backups/<stamp>/
	./backend/scripts/backup.sh

restore: ## восстановить из бэкапа: make restore SRC=backups/<stamp>
	@test -n "$(SRC)" || (echo "usage: make restore SRC=backups/<stamp>" && exit 1)
	./backend/scripts/restore.sh $(SRC)

verify: ## живая проверка стека без квоты LLM
	set -a; . ./.env; set +a; ./backend/scripts/verify.sh

test: ## backend + frontend тесты
	cd backend && uv run pytest -q -p no:warnings tests/ --ignore=tests/test_frozen_snapshot.py --ignore=tests/test_golden_positions.py --ignore=tests/test_observability.py --ignore=tests/test_storage.py --ignore=tests/test_audit_models.py
	pnpm --dir frontend run test:unit

lint: ## все проверки качества
	cd backend && uv run ruff check .
	pnpm --dir frontend run fmt:check
	pnpm --dir frontend run lint
	pnpm --dir frontend run typecheck
	PYTHON=$(PWD)/backend/.venv/bin/python pnpm --dir frontend run api:check
