"""Worker entry point: separate process from the web tier (research.md §3).

Polls `tick.decide()` — due-ness anchored in `pipeline_runs`, not an in-memory
timer, so a restart doesn't reset the schedule. Three independent pipelines,
each with its own `pipeline_runs` row: ingest (new games), review refresh
(Decayed TTL critic/user summaries), and playthrough (YouTube takeaways). A
scheduled tick runs all three; a manual `run_requests` row runs only the one
pipeline it names (`kind`).
"""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from metacritic_game_tracker.application.backfill import BackfillEnrichmentUseCase
from metacritic_game_tracker.application.ingest import IngestGamesUseCase
from metacritic_game_tracker.application.playthrough import FindPlaythroughTakeawayUseCase
from metacritic_game_tracker.infrastructure.config.runtime import RuntimeConfig
from metacritic_game_tracker.infrastructure.db.models import PipelineRunORM, RunRequestORM
from metacritic_game_tracker.infrastructure.db.repositories import (
    GameRepository,
    IngestStateRepository,
)
from metacritic_game_tracker.infrastructure.db.session import session_scope
from metacritic_game_tracker.infrastructure.dq import gates
from metacritic_game_tracker.infrastructure.llm.llm_client import call_llm
from metacritic_game_tracker.infrastructure.llm.review_summarizer import summarize_reviews
from metacritic_game_tracker.infrastructure.scheduler.tick import decide, dispatch_due, stage_due
from metacritic_game_tracker.infrastructure.scraper import parser
from metacritic_game_tracker.infrastructure.scraper.metacritic_client import MetacriticClient
from metacritic_game_tracker.infrastructure.youtube.quota_budget import YoutubeQuotaBudget
from metacritic_game_tracker.infrastructure.youtube.youtube_client import (
    get_transcript as yt_get_transcript,
)
from metacritic_game_tracker.infrastructure.youtube.youtube_client import (
    search_videos as yt_search_videos,
)

load_dotenv()

LOGS_DIR = Path(os.environ.get("LOGS_DIR", "logs"))
LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOGS_DIR / "worker.log", maxBytes=10 * 1024 * 1024, backupCount=5
        ),
    ],
)
# httpx logs the full request URL (including query string) at INFO — the
# YouTube Data API key travels as a `?key=` query param, so at the app's own
# INFO level that secret would otherwise land in plaintext in worker.log.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 10
_LISTING_URLS = {
    "new_releases": "https://www.metacritic.com/game/",
    "see_all": "https://www.metacritic.com/browse/game/all/all/all-time/new/",
}


async def _run_one_ingest(session, http_client: httpx.AsyncClient) -> None:
    config = RuntimeConfig(session)
    delay = await config.get_float("scraper.request_delay_seconds")
    retries = await config.get_int("scraper.max_retries")
    timeout = await config.get_int("scraper.timeout_seconds")
    client = MetacriticClient(http_client, delay_seconds=delay, max_retries=retries, timeout_seconds=timeout)

    async def fetch_listing(source):
        from metacritic_game_tracker.domain.rules import NewReleasesSource

        if isinstance(source, NewReleasesSource):
            html = await client.fetch(_LISTING_URLS["new_releases"])
        else:
            html = await client.fetch(f"{_LISTING_URLS['see_all']}?page={source.page}")
        return parser.list_games(html)

    async def fetch_detail(stub):
        return await client.fetch(f"https://www.metacritic.com/game/{stub.metacritic_slug}/")

    async def fetch_reviews(slug, audience):
        page = "critic-reviews" if audience == "critic" else "user-reviews"
        return await client.fetch(f"https://www.metacritic.com/game/{slug}/{page}/")

    async def fetch_review_json(url):
        return await client.fetch(url)

    async def summarize(quotes, audience):
        async def llm_call(route, prompt):
            return await call_llm(route, prompt, http_client)

        return await summarize_reviews(quotes, audience, llm_call)

    use_case = IngestGamesUseCase(
        session=session,
        config=config,
        ingest_state_repo=IngestStateRepository(session),
        game_repo=GameRepository(session),
        fetch_listing=fetch_listing,
        fetch_detail=fetch_detail,
        fetch_reviews=fetch_reviews,
        summarize=summarize,
        fetch_review_json=fetch_review_json,
    )
    run_row = await use_case.run()
    log.info("Ingest run finished: status=%s items_in=%s", run_row.status, run_row.items_in)


async def _run_detail_backfill(session, http_client: httpx.AsyncClient) -> None:
    """FR-028: re-extract description/developer/cover_image for games Gate B
    admitted with a recoverable gap. Runs on its own `detail_backfill` stage —
    not folded into `review_refresh`'s pipeline_runs, since that stage's
    cadence is now throttled to every few hours (stage_due) while this needs
    ingest's own hourly cadence to actually drain its (currently small)
    backlog at a reasonable pace. Full upsert, same as a normal ingest —
    re-fetching a detail page has no cheaper partial-field extraction path."""
    config = RuntimeConfig(session)
    delay = await config.get_float("scraper.request_delay_seconds")
    retries = await config.get_int("scraper.max_retries")
    timeout = await config.get_int("scraper.timeout_seconds")
    client = MetacriticClient(http_client, delay_seconds=delay, max_retries=retries, timeout_seconds=timeout)
    game_repo = GameRepository(session)

    async def do_work_for_step(step, game, run_id):
        html = await client.fetch(f"https://www.metacritic.com/game/{game.metacritic_slug}/")
        resolved = parser.get_resolved_game(html)
        gates.check_source(resolved)
        parsed = parser.build_parsed_game(resolved)
        verdict = gates.check_record(parsed)
        if not verdict.admitted:
            raise ValueError(f"Gate B still rejects re-fetch: {verdict.reason_code}")
        updated_game, _ = await game_repo.upsert(parsed)
        await game_repo.upsert_platform_scores(updated_game, parsed)

    use_case = BackfillEnrichmentUseCase(session, config)
    run_row = await use_case.run(do_work_for_step, stage="detail_backfill", steps=("detail_fields",))
    log.info("Detail backfill finished: status=%s items_in=%s", run_row.status, run_row.items_in)


async def _run_review_refresh(session, http_client: httpx.AsyncClient) -> None:
    """Pipeline 2 of 3: missing or Decayed-TTL-expired critic/user summaries."""
    config = RuntimeConfig(session)
    delay = await config.get_float("scraper.request_delay_seconds")
    retries = await config.get_int("scraper.max_retries")
    timeout = await config.get_int("scraper.timeout_seconds")
    client = MetacriticClient(http_client, delay_seconds=delay, max_retries=retries, timeout_seconds=timeout)

    async def fetch_reviews(slug, audience):
        page = "critic-reviews" if audience == "critic" else "user-reviews"
        return await client.fetch(f"https://www.metacritic.com/game/{slug}/{page}/")

    async def fetch_review_json(url):
        return await client.fetch(url)

    async def llm_call(route, prompt):
        return await call_llm(route, prompt, http_client)

    async def summarize(quotes, audience):
        return await summarize_reviews(quotes, audience, llm_call)

    from metacritic_game_tracker.application.enrichment import ReviewEnrichmentUseCase
    from metacritic_game_tracker.infrastructure.llm.cost import get_cost_usd
    review_use_case = ReviewEnrichmentUseCase(
        session, fetch_reviews, summarize, fetch_review_json,
        get_cost_usd=lambda model, i, o: get_cost_usd(session, model, i, o),
    )

    critic_n = await config.get_int("reviews.critic_sample_size")
    user_n = await config.get_int("reviews.user_sample_size")
    growth_threshold = await config.get_int("reviews.growth_threshold")
    recent_tier_days = await config.get_int("review_refresh.recent_tier_days")
    mid_tier_days = await config.get_int("review_refresh.mid_tier_days")
    max_age_weeks = await config.get_int("review_refresh.max_age_weeks")
    games_per_run = await config.get_int("review_refresh.games_per_run")

    async def do_work_for_step(step, game, run_id):
        is_critic = step == "critic_summary"
        audience = "critic" if is_critic else "user"
        sample_size = critic_n if is_critic else user_n
        await review_use_case.run(
            game, audience, sample_size=sample_size, growth_threshold=growth_threshold, run_id=run_id,
            recent_tier_days=recent_tier_days, mid_tier_days=mid_tier_days, max_age_weeks=max_age_weeks,
        )

    use_case = BackfillEnrichmentUseCase(session, config)
    run_row = await use_case.run(
        do_work_for_step, stage="review_refresh", steps=("critic_summary", "user_summary"),
        games_per_run=games_per_run,
    )
    log.info("Review refresh finished: status=%s items_in=%s", run_row.status, run_row.items_in)


async def _run_playthrough(session, http_client: httpx.AsyncClient) -> PipelineRunORM | None:
    """Pipeline 3 of 3: YouTube playthrough takeaways. Whether this gets
    called at all — scheduled runs only, or a manual trigger too, regardless
    of `enrichment.playthrough_enabled` — is decided by `main()`'s
    `dispatch_due()` call, not here (FR-009, feature 003): a deployment
    without a YouTube API key (or one that hasn't opted in) gets no
    *scheduled* run at all, but an explicit manual "Run now" still runs it."""
    config = RuntimeConfig(session)
    transcript_delay = await config.get_float("enrichment.youtube_transcript_delay_seconds")

    async def llm_call(route, prompt):
        return await call_llm(route, prompt, http_client)

    from metacritic_game_tracker.infrastructure.llm.cost import get_cost_usd

    async def do_work_for_step(step, game, run_id):
        playthrough_use_case = FindPlaythroughTakeawayUseCase(
            session=session,
            budget=YoutubeQuotaBudget(session, config),
            search_videos=lambda q: yt_search_videos(q, http_client, os.environ["YOUTUBE_API_KEY"]),
            get_transcript=yt_get_transcript,
            llm_call=llm_call,
            get_cost_usd=lambda model, i, o: get_cost_usd(session, model, i, o),
            transcript_delay_seconds=transcript_delay,
        )
        return await playthrough_use_case.run(game, run_id=run_id)

    use_case = BackfillEnrichmentUseCase(session, config)
    run_row = await use_case.run(do_work_for_step, stage="playthrough", steps=("playthrough",))
    log.info("Playthrough finished: status=%s items_in=%s", run_row.status, run_row.items_in)
    return run_row


async def _mark_stuck_runs_failed() -> None:
    """The ingest use case commits its "running" row separately from the
    batch's final commit, so the monitoring page can see progress mid-run
    (research.md §2). That means a crash after that early commit leaves the
    row stuck at "running" forever — which would also permanently block
    POST /monitoring/run's overlap check. Close it out explicitly."""
    from sqlalchemy import select

    from metacritic_game_tracker.infrastructure.db.models import PipelineRunORM

    async with session_scope() as cleanup_session:
        result = await cleanup_session.execute(
            select(PipelineRunORM).where(PipelineRunORM.status == "running")
        )
        stuck_runs = list(result.scalars().all())
        for run in stuck_runs:
            run.status = "failed"
            run.error_message = "Worker crashed mid-run"
            run.finished_at = datetime.now(UTC)
        if stuck_runs:
            await cleanup_session.commit()


async def main() -> None:
    log.info("Worker starting")
    # A container restart (deploy, OOM-kill, `podman restart`) kills the
    # process outright — no exception ever reaches the loop's own `except`
    # branch below, so a row left at "running" by the previous process
    # would otherwise stay stuck forever, permanently blocking
    # POST /monitoring/run's overlap check (see _mark_stuck_runs_failed).
    await _mark_stuck_runs_failed()
    async with httpx.AsyncClient() as http_client:
        while True:
            async with session_scope() as session:
                config = RuntimeConfig(session)
                decision = await decide(session, config, datetime.now(UTC))
                if decision.should_run:
                    log.info("Tick: running (%s)", decision.reason)
                    kind = "scheduled"
                    if decision.run_request_id is not None:
                        request = await session.get(RunRequestORM, decision.run_request_id)
                        request.picked_up_at = datetime.now(UTC)
                        kind = request.kind or "ingest"  # pre-migration rows had no kind
                    try:
                        if kind in ("scheduled", "ingest"):
                            await _run_one_ingest(session, http_client)
                            await _run_detail_backfill(session, http_client)
                        # review_refresh and playthrough don't need ingest's
                        # hourly cadence (Decayed TTL refreshes are due every
                        # 3-7 days; playthrough's daily budget burns in one
                        # burst) — a manual "Run now" (kind == the stage name)
                        # always fires regardless of that pipeline's own enable
                        # switch (FR-009); only a scheduled tick is gated by
                        # both the switch and stage_due (dispatch_due).
                        review_refresh_due = await stage_due(
                            session, "review_refresh",
                            await config.get_int("review_refresh.interval_hours"),
                            datetime.now(UTC),
                        )
                        if dispatch_due(
                            kind, "review_refresh",
                            await config.get_bool("enrichment.review_summary_enabled"),
                            review_refresh_due,
                        ):
                            await _run_review_refresh(session, http_client)
                        playthrough_due = await stage_due(
                            session, "playthrough",
                            await config.get_int("playthrough.interval_hours"),
                            datetime.now(UTC),
                        )
                        if dispatch_due(
                            kind, "playthrough",
                            await config.get_bool("enrichment.playthrough_enabled"),
                            playthrough_due,
                        ):
                            await _run_playthrough(session, http_client)
                        await session.commit()
                    except Exception:
                        log.exception("Ingestion run failed")
                        await session.rollback()
                        await _mark_stuck_runs_failed()
                else:
                    log.debug("Tick: skipped (%s)", decision.reason)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
