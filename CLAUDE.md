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

Два процесса из одного образа: `app` (веб, только читает) и `worker` (планировщик
ингестии). Веб-слой никогда не запускает ингестию сам — иначе каждый воркер uvicorn
поднял бы свой планировщик и дублировал парсинг.

| Среда | Как |
|---|---|
| Разработка (тесты, lint) | `poetry run ...` на хосте, локальная БД (порт 5439) |
| Production | `podman compose up -d` (поднимает `db` + `app` + `worker`) |
| Ручной прогон ингестии | кнопка в `/monitoring` (кладёт строку в `run_requests`, worker подхватывает) |

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

## Наблюдаемость

Никакого Grafana, никаких дашбордов, никакого алертинга. Из мониторинга в проекте —
только то, что реально нужно:

- **Каждый вызов LLM** — строка в `llm_calls` (`model`, `input_tokens`, `output_tokens`,
  `cost_usd`, `created_at`). Цены — из `meta.llm_model_costs`. Это единственные таблицы,
  ради которых стоит смотреть в БД специально.
- **Критичные сбои — уровнем `CRITICAL`/`ERROR` в обычный лог**, не отдельной метрикой.
  В частности: гейт A (payload не соответствует ожидаемой схеме источника) логирует
  `CRITICAL` и прерывает прогон — **курсор пагинации при этом не двигается**, иначе
  сломанный прогон навсегда пропустит страницы игр (листинг не отматывается назад).
- **Никаких `except: pass`** и обработчиков, которые только логируют без пробрасывания
  — либо счётчик/строка в `pipeline_rejects` с `reason_code`, либо `raise`.
- Отбракованное не читается обратно ниже по течению: очередь backfill исключает
  `enrichment_attempts.state = 'abandoned'`.

`pipeline_runs`/`pipeline_rejects` остаются — они нужны самому пайплайну (планировщик
проверяет по ним, был ли уже прогон; backfill проверяет причины отказов), не для панелей.

Отправка почты, если понадобится (ручной вызов, будущая автоматика) —
`metacritic_game_tracker/infrastructure/alerting/email.py`, через Resend API
(`RESEND_API_KEY`/`ALERT_EMAIL_TO` в `.env`), без SMTP-сервера. Пока никуда
автоматически не подключена — просто готовый примитив.

## Data quality

Два гейта — код, не таблица метрик (research.md §14):

- **Гейт A, на сыром payload** — соответствие ожидаемой схеме источника. Падение →
  `CRITICAL` в лог + прогон прерывается, курсор не двигается.
- **Гейт B, на распарсенной записи** — обязательные поля. Нет id/названия/платформы →
  запись отбраковывается (`pipeline_rejects`). Нет описания/разработчика/обложки —
  запись всё равно попадает в каталог и встаёт в очередь backfill на переизвлечение.

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
