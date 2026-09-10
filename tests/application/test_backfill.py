from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from metacritic_game_tracker.application.backfill import (
    BackfillEnrichmentUseCase,
    RunBudgetExhausted,
)
from metacritic_game_tracker.infrastructure.db.models import (
    EnrichmentAttemptORM,
    GameORM,
    PipelineRejectORM,
)


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


async def test_games_missing_for_detail_fields_targets_missing_recoverable_columns(mock_session):
    """FR-028: description/developer/cover_image are recoverable gaps that must
    be queued for re-extraction, not silently left unfilled."""
    result = MagicMock()
    result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute.return_value = result
    use_case = BackfillEnrichmentUseCase(mock_session, _config())

    await use_case._games_missing("detail_fields")

    stmt = mock_session.execute.call_args_list[0].args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "description" in compiled
    assert "developer" in compiled
    assert "cover_image_url" in compiled


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

    async def do_work(step, game, run_id):
        if game.id == 2:
            raise RuntimeError("boom")

    run_row = await use_case.run(do_work, stage="review_refresh", steps=("critic_summary",))

    assert run_row.items_in == 2
    assert run_row.items_accepted == 1


async def test_run_does_not_count_a_no_op_result_as_accepted(mock_session):
    """Real bug, caught live: playthrough's do_work returns False for "no
    findable playthrough" — a normal outcome (budget exhausted, no video, no
    transcript), not an error, so process_game_step doesn't raise/retry it.
    But the OLD code discarded the return value entirely and always counted
    it as accepted — 134/134 "accepted" in monitoring with zero rows actually
    written anywhere. Only a real product (return value not explicitly False)
    counts toward items_accepted."""
    use_case = BackfillEnrichmentUseCase(mock_session, _config())
    game1 = GameORM(id=1, metacritic_id=1, metacritic_slug="g1", title="G1")
    game2 = GameORM(id=2, metacritic_id=2, metacritic_slug="g2", title="G2")

    async def fake_games_missing(step):
        return [(game1, None), (game2, None)]

    use_case._games_missing = fake_games_missing

    async def do_work(step, game, run_id):
        return game.id == 1  # game1 finds a playthrough, game2 finds nothing

    run_row = await use_case.run(do_work, stage="playthrough", steps=("playthrough",))

    assert run_row.items_in == 2
    assert run_row.items_accepted == 1


async def test_run_stops_early_and_records_one_reject_when_do_work_signals_budget_exhausted(mock_session):
    """Real bug, caught live: playthrough's do_work returned False (silently)
    for every remaining game once the daily YouTube quota ran out — 134 games
    all looping through fetches that could never succeed, and the Errors Log
    stayed completely empty (a returned False isn't an exception, so nothing
    ever reached pipeline_rejects), making a 0-accepted run look causeless.
    do_work now raises RunBudgetExhausted once, backfill stops iterating
    immediately and records exactly ONE reject — not one per remaining game."""
    use_case = BackfillEnrichmentUseCase(mock_session, _config())
    game1 = GameORM(id=1, metacritic_id=1, metacritic_slug="g1", title="G1")
    game2 = GameORM(id=2, metacritic_id=2, metacritic_slug="g2", title="G2")
    game3 = GameORM(id=3, metacritic_id=3, metacritic_slug="g3", title="G3")

    async def fake_games_missing(step):
        return [(game1, None), (game2, None), (game3, None)]

    use_case._games_missing = fake_games_missing

    async def do_work(step, game, run_id):
        if game.id == 2:
            raise RunBudgetExhausted("daily YouTube quota exhausted")
        return True

    run_row = await use_case.run(do_work, stage="playthrough", steps=("playthrough",))

    assert run_row.items_in == 2  # game1 processed, game2 triggered the stop — game3 never reached
    assert run_row.items_accepted == 1
    reject_rows = [c.args[0] for c in mock_session.add.call_args_list if isinstance(c.args[0], PipelineRejectORM)]
    assert len(reject_rows) == 1
    assert reject_rows[0].reason_code == "budget_exhausted"
    assert reject_rows[0].item_ref == "2"


async def test_run_updates_current_item_in_meta_as_it_processes_each_game(mock_session):
    """Monitoring shows which game a manual run is currently processing —
    meta.current_item must be set (and committed) per item, not only in the
    single commit at the end, so a concurrent SSE poll from another session
    can actually see it while the run is still in flight."""
    use_case = BackfillEnrichmentUseCase(mock_session, _config())
    game1 = GameORM(id=1, metacritic_id=1, metacritic_slug="g1", title="Elden Ring")
    game2 = GameORM(id=2, metacritic_id=2, metacritic_slug="g2", title="Valheim")

    async def fake_games_missing(step):
        return [(game1, None), (game2, None)]

    use_case._games_missing = fake_games_missing

    run_row = await use_case.run(AsyncMock(), stage="review_refresh", steps=("critic_summary",))

    assert run_row.meta["current_item"] == "Valheim"
    assert mock_session.commit.await_count >= 3  # initial "running" + one per item


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
