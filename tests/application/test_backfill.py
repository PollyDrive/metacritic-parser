from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.application.backfill import BackfillEnrichmentUseCase
from metacritic_game_tracker.infrastructure.db.models import EnrichmentAttemptORM, GameORM


def _config(max_attempts=5, backoff_base_minutes=30):
    config = MagicMock()
    values = {"backfill.max_attempts": max_attempts, "backfill.backoff_base_minutes": backoff_base_minutes}
    config.get_int = AsyncMock(side_effect=lambda k: values[k])
    return config


def _use_case(session=None, config=None) -> BackfillEnrichmentUseCase:
    if session is None:
        session = AsyncMock()
        session.add = MagicMock()
    return BackfillEnrichmentUseCase(session, config or _config())


async def test_missing_output_is_queued_even_though_the_game_was_seen_today():
    """FR-023: 'seen today' must not be conflated with 'fully enriched'."""
    game = GameORM(id=1, metacritic_id=1, metacritic_slug="g", title="G")
    use_case = _use_case()

    async def do_work(g):
        do_work.called_with = g

    outcome = await use_case.process_game_step(game, "critic_summary", attempt=None, do_work=do_work)

    assert outcome.status == "succeeded"
    assert do_work.called_with is game


async def test_a_game_in_backoff_is_skipped_not_retried_early():
    game = GameORM(id=1, metacritic_id=1, metacritic_slug="g", title="G")
    attempt = EnrichmentAttemptORM(
        id=1, game_id=1, step="critic_summary", attempts=1, state="retrying",
        last_attempt_at=datetime.now(UTC), next_retry_at=datetime.now(UTC) + timedelta(hours=1),
    )
    use_case = _use_case()
    do_work = AsyncMock()

    outcome = await use_case.process_game_step(game, "critic_summary", attempt=attempt, do_work=do_work)

    assert outcome.status == "retrying"
    do_work.assert_not_awaited()


async def test_failure_past_the_attempt_ceiling_is_abandoned_and_recorded():
    game = GameORM(id=1, metacritic_id=1, metacritic_slug="g", title="G")
    attempt = EnrichmentAttemptORM(
        id=1, game_id=1, step="critic_summary", attempts=4, state="retrying",
        last_attempt_at=datetime.now(UTC), next_retry_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    session = AsyncMock()
    session.add = MagicMock()
    use_case = _use_case(session=session, config=_config(max_attempts=5))

    async def failing(g):
        raise RuntimeError("llm timeout")

    outcome = await use_case.process_game_step(game, "critic_summary", attempt=attempt, do_work=failing)

    assert outcome.status == "abandoned"
    assert attempt.state == "abandoned"
    assert attempt.attempts == 5
    session.add.assert_called_once()
    rejected = session.add.call_args[0][0]
    assert rejected.reason_code == "enrichment_abandoned"


async def test_failure_below_the_ceiling_schedules_a_backoff_retry():
    game = GameORM(id=1, metacritic_id=1, metacritic_slug="g", title="G")
    use_case = _use_case(config=_config(max_attempts=5, backoff_base_minutes=30))

    async def failing(g):
        raise RuntimeError("timeout")

    outcome = await use_case.process_game_step(game, "critic_summary", attempt=None, do_work=failing)

    assert outcome.status == "retrying"
    assert outcome.attempt.attempts == 1
    assert outcome.attempt.state == "retrying"
    assert outcome.attempt.next_retry_at > datetime.now(UTC)


async def test_games_missing_for_playthrough_orders_by_best_metascore_then_recency(mock_session):
    """research.md §6: budget is limited, so higher-Metascore (then more recent)
    games are searched for a playthrough first."""
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute.return_value = result
    use_case = BackfillEnrichmentUseCase(mock_session, _config())

    await use_case._games_missing("playthrough")

    stmt = mock_session.execute.call_args_list[0].args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "order by" in compiled
    assert "metascore" in compiled
    assert "first_seen_at" in compiled


async def test_run_creates_and_completes_its_own_pipeline_run_row(mock_session):
    """Each pipeline gets its own visible pipeline_runs row (monitoring shows
    independent status per pipeline, not one shared 'backfill' blob)."""
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute.return_value = result
    use_case = BackfillEnrichmentUseCase(mock_session, _config())

    run_row = await use_case.run(
        AsyncMock(), stage="review_refresh", steps=("critic_summary", "user_summary")
    )

    assert run_row.stage == "review_refresh"
    assert run_row.status == "completed"
    assert run_row.finished_at is not None
    mock_session.commit.assert_awaited()


async def test_run_counts_items_in_and_items_accepted(mock_session):
    use_case = BackfillEnrichmentUseCase(mock_session, _config())
    game1 = GameORM(id=1, metacritic_id=1, metacritic_slug="g1", title="G1")
    game2 = GameORM(id=2, metacritic_id=2, metacritic_slug="g2", title="G2")

    async def fake_games_missing(step):
        return [(game1, None), (game2, None)]

    use_case._games_missing = fake_games_missing

    async def do_work(step, game):
        if game.id == 2:
            raise RuntimeError("boom")

    run_row = await use_case.run(do_work, stage="review_refresh", steps=("critic_summary",))

    assert run_row.items_in == 2
    assert run_row.items_accepted == 1


async def test_an_abandoned_step_is_never_reattempted():
    game = GameORM(id=1, metacritic_id=1, metacritic_slug="g", title="G")
    attempt = EnrichmentAttemptORM(
        id=1, game_id=1, step="critic_summary", attempts=5, state="abandoned",
        last_attempt_at=datetime.now(UTC), next_retry_at=datetime.now(UTC) - timedelta(days=1),
    )
    use_case = _use_case()
    do_work = AsyncMock()

    outcome = await use_case.process_game_step(game, "critic_summary", attempt=attempt, do_work=do_work)

    assert outcome.status == "abandoned"
    do_work.assert_not_awaited()
