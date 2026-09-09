"""Russian labels and explanations for the settings page (contracts/web-ui.md,
US5) — the `runtime_config` seed rows themselves stay in English (the
canonical, technical description column); this is presentation-only
translation for the operator console, keyed by `runtime_config.key`."""
from __future__ import annotations

RU_LABELS: dict[str, str] = {
    "ingest.enabled": "Плановая загрузка включена",
    "ingest.runs_per_hour": "Запусков в час",
    "ingest.games_per_run": "Игр за один запуск",
    "ingest.active_hours_start": "Начало окна активности",
    "ingest.active_hours_end": "Конец окна активности",
    "ingest.timezone": "Часовой пояс (граница суток)",
    "scraper.request_delay_seconds": "Задержка между запросами, сек",
    "scraper.max_retries": "Повторных попыток при сбое",
    "scraper.timeout_seconds": "Таймаут запроса, сек",
    "reviews.critic_sample_size": "Отзывов критиков для резюме",
    "reviews.user_sample_size": "Отзывов игроков для резюме",
    "enrichment.playthrough_enabled": "Летсплей-заключения включены",
    "enrichment.youtube_daily_search_budget": "Дневной бюджет запросов YouTube",
    "backfill.max_attempts": "Попыток перед отказом",
    "backfill.backoff_base_minutes": "База экспоненциальной задержки, мин",
    "dq.max_reject_ratio": "Порог отбраковки для остановки прогона",
}

# "Зачем нужна настройка" — на один-два предложения длиннее RU_LABELS,
# объясняет практическое последствие изменения значения, а не просто
# повторяет название.
RU_WHY: dict[str, str] = {
    "ingest.enabled": (
        "Общий выключатель плановой загрузки новых игр. Выключите, чтобы "
        "полностью остановить обход Metacritic (например, на обслуживание), "
        "не трогая остальные настройки — воркер продолжит работать, но "
        "пропускать плановые прогоны."
    ),
    "ingest.runs_per_hour": (
        "Как часто воркер проверяет Metacritic на новые игры. Больше — "
        "каталог свежее, но выше нагрузка на источник и на LLM-бюджет."
    ),
    "ingest.games_per_run": (
        "Сколько игр обрабатывается за один прогон. Ограничивает разовую "
        "нагрузку на скрапер и стоимость LLM-вызовов за один запуск."
    ),
    "ingest.active_hours_start": (
        "Начало окна, в которое разрешён плановый запуск загрузки. Вне "
        "этого окна воркер тикает, но не запускает ингест."
    ),
    "ingest.active_hours_end": (
        "Конец окна активности плановой загрузки — см. «Начало окна "
        "активности»."
    ),
    "ingest.timezone": (
        "Часовой пояс, по которому определяется граница суток — влияет на "
        "счётчик «игр за день» и на окно активных часов выше."
    ),
    "scraper.request_delay_seconds": (
        "Пауза между запросами к Metacritic. Снижает риск блокировки по IP "
        "за слишком частые обращения — не ставьте 0."
    ),
    "scraper.max_retries": (
        "Сколько раз повторить запрос при сетевой ошибке, прежде чем "
        "считать страницу недоступной и отбраковать её."
    ),
    "scraper.timeout_seconds": (
        "Сколько ждать ответ от Metacritic на один запрос, прежде чем "
        "считать его зависшим и повторить попытку."
    ),
    "reviews.critic_sample_size": (
        "Сколько отзывов критиков передаётся в LLM для резюме. Больше "
        "выборка — точнее резюме, но дороже и медленнее вызов."
    ),
    "reviews.user_sample_size": (
        "То же самое, но для отзывов игроков — см. «Отзывов критиков для "
        "резюме»."
    ),
    "enrichment.playthrough_enabled": (
        "Включает поиск летсплеев на YouTube и генерацию заключения по ним "
        "для карточек игр. Требует настроенный YOUTUBE_API_KEY в .env — без "
        "него прогон пайплайна летсплеев просто не будет запускаться."
    ),
    "enrichment.youtube_daily_search_budget": (
        "Дневной лимит «единиц» YouTube Data API на поиск летсплеев (поиск "
        "стоит 100 единиц за запрос). Защищает бесплатную квоту Google от "
        "исчерпания в течение дня."
    ),
    "backfill.max_attempts": (
        "Сколько раз повторить попытку обогащения (резюме отзывов или "
        "летсплей) при сбое, прежде чем окончательно отказаться от игры до "
        "ручного вмешательства."
    ),
    "backfill.backoff_base_minutes": (
        "Базовая задержка перед повторной попыткой после сбоя обогащения — "
        "растёт экспоненциально с каждой следующей неудачной попыткой."
    ),
    "dq.max_reject_ratio": (
        "Доля отбракованных записей в одном прогоне ингеста, при "
        "превышении которой прогон прерывается целиком, не трогая курсор "
        "пагинации — защита от массового сбоя парсера на изменившейся "
        "разметке."
    ),
}


def label_for(key: str) -> str:
    return RU_LABELS.get(key, key)


def why_for(key: str) -> str:
    return RU_WHY.get(key, "")
