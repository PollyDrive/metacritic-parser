.PHONY: up down logs build migrate test lint tach fix shell db-shell install lock backup restore-check

up:
	podman compose up -d

down:
	podman compose down

logs:
	podman compose logs -f app

# podman compose build не работает с приватными registry — собираем напрямую
build:
	podman build -t metacritic-game-tracker-app:latest .

migrate:
	poetry run alembic upgrade head

test:
	poetry run pytest tests/ -q

lint:
	poetry run ruff check .
	poetry run tach check

tach:
	poetry run tach check

fix:
	poetry run ruff check . --fix

shell:
	podman compose exec app python

db-shell:
	podman compose exec db psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-metacritic_game_tracker_db}

backup:            ## Дамп БД + состояние, с проверкой
	@bash scripts/backup.sh

restore-check:     ## Проверить, что последний дамп реально восстанавливается
	@LATEST=$$(ls -t backups/db_*.dump | head -1); \
	 podman exec -i $${DB_CONTAINER:-metacritic-game-tracker_db_1} psql -U $${POSTGRES_USER:-postgres} -c \
	   'DROP DATABASE IF EXISTS restore_test; CREATE DATABASE restore_test;'; \
	 podman exec -i $${DB_CONTAINER:-metacritic-game-tracker_db_1} pg_restore -U $${POSTGRES_USER:-postgres} \
	   -d restore_test < $$LATEST && echo "ВОССТАНОВЛЕНИЕ РАБОТАЕТ: $$LATEST"; \
	 podman exec -i $${DB_CONTAINER:-metacritic-game-tracker_db_1} psql -U $${POSTGRES_USER:-postgres} -c \
	   'DROP DATABASE restore_test;'

# Зафиксировать текущие версии зависимостей
lock:
	poetry lock

install:
	poetry install
