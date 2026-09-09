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
from metacritic_game_tracker.infrastructure.llm.llm_client import call_llm
from metacritic_game_tracker.infrastructure.llm.review_summarizer import summarize_reviews
from metacritic_game_tracker.infrastructure.scheduler.tick import decide
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
    handlers=[logging.StreamHandler(), logging.FileHandler(LOGS_DIR / "worker.log")],
)
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
    )
    run_row = await use_case.run()
    log.info("Ingest run finished: status=%s items_in=%s", run_row.status, run_row.items_in)


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

    async def llm_call(route, prompt):
        return await call_llm(route, prompt, http_client)

    async def summarize(quotes, audience):
        return await summarize_reviews(quotes, audience, llm_call)

    from metacritic_game_tracker.application.enrichment import ReviewEnrichmentUseCase
    review_use_case = ReviewEnrichmentUseCase(session, fetch_reviews, summarize)

    async def do_work_for_step(step, game):
        audience = "critic" if step == "critic_summary" else "user"
        await review_use_case.run(game, audience, sample_size=20)

    use_case = BackfillEnrichmentUseCase(session, config)
    run_row = await use_case.run(
        do_work_for_step, stage="review_refresh", steps=("critic_summary", "user_summary")
    )
    log.info("Review refresh finished: status=%s items_in=%s", run_row.status, run_row.items_in)


async def _run_playthrough(session, http_client: httpx.AsyncClient) -> PipelineRunORM | None:
    """Pipeline 3 of 3: YouTube playthrough takeaways. Gated by
    `enrichment.playthrough_enabled` — a deployment without a YouTube API key
    (or one that hasn't opted in) gets no attempted run at all, not a run
    that immediately fails on every game."""
    config = RuntimeConfig(session)
    if not await config.get_bool("enrichment.playthrough_enabled"):
        return None

    async def llm_call(route, prompt):
        return await call_llm(route, prompt, http_client)

    async def do_work_for_step(step, game):
        playthrough_use_case = FindPlaythroughTakeawayUseCase(
            session=session,
            budget=YoutubeQuotaBudget(session, config),
            search_videos=lambda q: yt_search_videos(q, http_client, os.environ["YOUTUBE_API_KEY"]),
            get_transcript=yt_get_transcript,
            llm_call=llm_call,
        )
        await playthrough_use_case.run(game)

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
                        if kind in ("scheduled", "review_refresh"):
                            await _run_review_refresh(session, http_client)
                        if kind in ("scheduled", "playthrough"):
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
