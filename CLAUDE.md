# metacritic-game-tracker — правила работы с Claude

Спека: [specs/001-metacritic-game-tracker/spec.md](specs/001-metacritic-game-tracker/spec.md) (spec-kit).

## Стек

Python 3.11+ · FastAPI · SQLAlchemy async · PostgreSQL · Poetry · Podman
Тесты: `poetry run pytest`

## Архитектура — DDD

```
metacritic_game_tracker/
├── domain/          ← чистые модели + доменные правила (нет внешних зависимостей)
├── application/     ← use cases / оркестрация (нет HTTP/SQL напрямую)
├── infrastructure/  ← адаптеры: db/, scraper/ (Metacritic), llm/, youtube/, web/ (FastAPI routes)
└── shared/          ← cross-cutting: guardrail.py, sanitizer.py, llm_config.py
scripts/             ← тонкие точки входа: load_dotenv + asyncio.run(app.run())
```

**Правила слоёв (tach.toml принудительно):**
- `domain` и `shared` — нет внутренних зависимостей
- `infrastructure` импортирует только `domain` + `shared`
- `application` импортирует `domain` + `shared` + `infrastructure`
- Скрипты вызывают `application`, никогда не импортируют `infrastructure` напрямую

## Запуск — только через Podman

| Среда | Как |
|---|---|
| Разработка (тесты, lint) | `poetry run ...` на хосте, локальная БД |
| Production | `podman compose up -d` |
| Ручной прогон ингестии | `podman compose exec app python scripts/run_ingest.py` |

## TDD — обязательно для всех фич и багфиксов

Используй `/tdd` перед началом любой реализации.

**Правило железное:** никакого production-кода без падающего теста.

```
RED  →  GREEN  →  REFACTOR
```

### Что покрывается тестами

| Слой | Директория | Тесты |
|---|---|---|
| Domain | `metacritic_game_tracker/domain/` | `tests/` |
| Shared | `metacritic_game_tracker/shared/` | `tests/` |
| Infrastructure (детерминированные части: парсинг HTML, дедуп) | `metacritic_game_tracker/infrastructure/` | `tests/` |

### Что не покрывается

- LLM-клиенты (сам HTTP-вызов)
- Промпт-строки
- DB-миграции
- Cron-скрипты (тестировать модули отдельно)
- Живые HTTP-запросы к Metacritic/YouTube (мокать HTML/JSON фикстурами)

### Запуск тестов

```bash
poetry run pytest tests/ -q
poetry run pytest tests/test_X.py -v
```

## Правила написания кода

- Нет моков для детерминированного кода (парсинг HTML, дедуп-логика)
- `AsyncMock` только для `AsyncSession` и внешних HTTP-клиентов (Metacritic, YouTube, LLM)
- Один тест = одно поведение
- Имена тестов описывают поведение, не реализацию
- Не добавляй docstring и type annotations в код, который не менял

## Наблюдаемость ингестии

Каждый прогон hourly-джобы пишет строку в `pipeline_runs` (стадия `ingest` /
`summarize` / `playthrough`), с разбивкой `items_accepted/rejected/deferred/errored`,
а не только общим счётчиком. Отбракованное — в `pipeline_rejects` с `reason_code`.
См. `sql/migrations/001_pipeline.sql`.

## Токены и стоимость LLM

Любая таблица, хранящая LLM-вызовы (генерация резюме отзывов, заключение по
летсплею), **обязана** иметь колонки:
`model TEXT`, `input_tokens INTEGER`, `output_tokens INTEGER`, `cost_usd NUMERIC(10,6)`, `created_at TIMESTAMPTZ`.

Справочник цен — `meta.llm_model_costs` (миграция `sql/migrations/000_meta.sql`).

## Безопасность

- Весь сторонний текст (отзывы, транскрипт летсплея) перед LLM — через `sanitize_input()` из `metacritic_game_tracker.shared.guardrail`
- Все ответы перед отдачей в веб-интерфейс — через `mask_secrets()` из `metacritic_game_tracker.shared.sanitizer`
- Secrets только через `.env`, никогда в коде
- Мониторинг/force-run (FR-022) — за basic-auth с единственной парой логин/пароль из `.env`, не публично
- Все LLM-ответы валидируй Pydantic-схемой перед использованием

## Финальная проверка

```bash
poetry run ruff check .
poetry run tach check
poetry run pytest tests/ -q
```

Работа завершена только когда ruff чист, tach зелёный, все тесты зелёные.

## Коммиты

Только по явному запросу. Формат: `<type>(<scope>): <описание>`
