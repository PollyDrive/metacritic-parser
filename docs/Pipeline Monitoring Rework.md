# Pipeline Monitoring Rework: Granular Activity Tracking

В текущей архитектуре таблица `pipeline_runs` хранит только общую статистику (сколько элементов зашло, сколько принято/отклонено). Из-за этого невозможно провалиться в детали конкретного запуска или посмотреть историю обработки отдельной игры. 

Чтобы выполнить новые требования (сколько отзывов подтянуто, по каким играм, дельта с прошлого раза, полная история по игре), нам нужно добавить гранулярное логирование событий на уровне каждой игры.

## Proposed Changes

Мы добавим новую таблицу `game_activity_events` (Audit Log), которая будет хранить детализированную историю всех действий системы над каждой игрой.

### 1. Database Model (Новая таблица)

#### `[NEW] sql/migrations/006_game_activity_events.sql`
Создаем таблицу `game_activity_events`:
- `id` (serial PK)
- `game_id` (FK → games)
- `run_id` (FK → pipeline_runs)
- `event_type` (text: `'ingest_new'`, `'ingest_update'`, `'review_refresh'`, `'playthrough_generated'`)
- `created_at` (timestamptz)
- `details` (JSONB) — гибкий payload для хранения метрик:
  - Для `review_refresh`: `{"audience": "critic", "reviews_found": 20, "previous_reviews": 15, "delta": "+5"}`
  - Для `ingest_new`: `{"source": "new_releases"}`

#### `[MODIFY] metacritic_game_tracker/infrastructure/db/models.py`
Добавим `GameActivityEventORM`, замапленную на новую таблицу. Настроим связи (`relationship`) с `GameORM` и `PipelineRunORM`.

### 2. Application Logic (Запись событий)

#### `[MODIFY] metacritic_game_tracker/application/enrichment.py`
При генерации `ReviewSummary` или `PlaythroughTakeaway`:
- Извлекаем предыдущее количество отзывов из БД перед парсингом.
- Считаем дельту (`reviews_found - previous_reviews`).
- Сохраняем `GameActivityEventORM` с деталями в транзакцию.

#### `[MODIFY] metacritic_game_tracker/application/ingest.py`
При добавлении или обновлении игры (`game_repo.upsert`) — пишем событие `ingest_new` или `ingest_update` в `game_activity_events`.

### 3. Monitoring UI Rework (Интерфейс)

#### `[MODIFY] metacritic_game_tracker/infrastructure/web/routes_monitoring.py`
- Добавим новый эндпоинт и вкладку **"Activity Feed"** (или **"Game Events"**).
- Добавим возможность кликнуть на конкретный запуск во вкладке "Run History", чтобы увидеть список всех событий (`events`), которые произошли во время этого запуска.
- Добавим просмотр истории по конкретной игре (например, фильтр по `game_id` или `slug`).

#### `[MODIFY] metacritic_game_tracker/infrastructure/web/templates/monitoring.html`
- Вкладка **Run History**: Добавим кнопку "View Details", открывающую список затронутых игр.
- Новая вкладка **Activity Feed**: Хронологическая лента событий по всем играм с бейджами (например: *[Review Refresh] Elden Ring: +5 critic reviews*).

## Open Questions

> [!IMPORTANT]
> **Вопрос по интерфейсу**: Хочешь ли ты добавить отдельную страницу `monitoring/run/<id>`, чтобы при клике на запуск открывалась детальная сводка (со списком игр и дельт по отзывам), или лучше всё выводить прямо на главной странице мониторинга в виде разворачивающихся списков (accordion) / модалок?

> [!WARNING]
> **Отслеживание количества отзывов**: В текущей архитектуре мы парсим отзывы из HTML, передаем их в LLM и удаляем сырые тексты. Саму "цифру" (сколько было до этого) мы нигде исторически не хранили. Я добавлю колонку `parsed_reviews_count` в `ReviewSummaryORM` или буду просто считать `delta` на лету, опираясь на последнее сохраненное событие в `game_activity_events`. Согласен на такой подход?

## Verification Plan

### Automated Tests
- Добавим тесты на создание `GameActivityEventORM` при вызове `IngestGamesUseCase.run` и `ReviewEnrichmentUseCase.run`.
- Проверим вычисление `delta` при повторном запуске обновления отзывов.

### Manual Verification
- Сделаем мануальный запуск инжеста через веб-интерфейс.
- Убедимся, что на дашборде появились записи с конкретными играми и точным количеством спарсенных отзывов.
