from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # Every timestamp column in sql/migrations/*.sql is TIMESTAMPTZ, and the
    # rest of the codebase writes tz-aware datetime.now(UTC) everywhere — without
    # this, SQLAlchemy's default DateTime(timezone=False) mapping rejects every
    # single insert/update against a real Postgres connection (caught by a live
    # walkthrough, T072; every unit test mocks the session so this was invisible).
    type_annotation_map = {datetime: DateTime(timezone=True)}


class PipelineRunORM(Base):
    """Maps the pre-existing `pipeline_runs` table (sql/migrations/001_pipeline.sql)."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    items_in: Mapped[int] = mapped_column(default=0)
    items_accepted: Mapped[int] = mapped_column(default=0)
    items_rejected: Mapped[int] = mapped_column(default=0)
    items_deferred: Mapped[int] = mapped_column(default=0)
    items_errored: Mapped[int] = mapped_column(default=0)
    code_version: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class PipelineRejectORM(Base):
    """Maps the pre-existing `pipeline_rejects` table."""

    __tablename__ = "pipeline_rejects"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"))
    item_ref: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime]


class LlmCallORM(Base):
    """Maps the pre-existing `llm_calls` table (sql/migrations/002_llm_calls.sql)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_type: Mapped[str] = mapped_column(Text, nullable=False)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    status: Mapped[str] = mapped_column(Text, default="ok")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]


class LlmModelCostORM(Base):
    """Maps the pre-existing `meta.llm_model_costs` table (sql/migrations/000_meta.sql)."""

    __tablename__ = "llm_model_costs"
    __table_args__ = {"schema": "meta"}

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    input_cost_per_1m: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    output_cost_per_1m: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    context_window: Mapped[int | None]
    valid_from: Mapped[date]
    valid_until: Mapped[date | None]
    notes: Mapped[str | None] = mapped_column(Text)


class GameORM(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    metacritic_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    metacritic_slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    cover_image_url: Mapped[str | None] = mapped_column(Text)
    developer: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    video_url: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None]
    genres: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    first_seen_at: Mapped[datetime]
    last_updated_at: Mapped[datetime]
    next_refresh_at: Mapped[datetime | None]

    platform_scores: Mapped[list[PlatformScoreORM]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    review_summaries: Mapped[list[ReviewSummaryORM]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    playthrough_takeaway: Mapped[PlaythroughTakeawayORM | None] = relationship(
        cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class PlatformScoreORM(Base):
    __tablename__ = "platform_scores"
    __table_args__ = (UniqueConstraint("game_id", "platform"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    metascore: Mapped[int | None]
    userscore: Mapped[float | None]
    updated_at: Mapped[datetime]


class ReviewSummaryORM(Base):
    __tablename__ = "review_summaries"
    __table_args__ = (
        UniqueConstraint("game_id", "audience"),
        CheckConstraint("audience IN ('critic','user')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime]
    llm_call_id: Mapped[int | None] = mapped_column(ForeignKey("llm_calls.id", ondelete="SET NULL"))
    # What this summary actually reflects: the true review count on
    # Metacritic when it was generated (not the SSR page's fixed 10-cap),
    # how many of those were sampled for the LLM, and where to see the rest.
    total_reviews_count: Mapped[int] = mapped_column(nullable=False, default=0)
    sampled_reviews_count: Mapped[int] = mapped_column(nullable=False, default=0)
    source_url: Mapped[str | None] = mapped_column(Text)
    # Which of the game's platforms this summary was actually sampled from —
    # reviews are split per platform on Metacritic, so this is the one with
    # the most reviews for this audience as of the last regeneration.
    source_platform: Mapped[str | None] = mapped_column(Text)


class IngestStateORM(Base):
    __tablename__ = "ingest_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    current_day: Mapped[date] = mapped_column(nullable=False)
    day_processed_count: Mapped[int] = mapped_column(nullable=False, default=0)
    day_new_releases_done: Mapped[bool] = mapped_column(nullable=False, default=False)
    see_all_next_page: Mapped[int] = mapped_column(nullable=False, default=1)
    updated_at: Mapped[datetime]


class GameActivityEventORM(Base):
    __tablename__ = "game_activity_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime]
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    game: Mapped[GameORM] = relationship(lazy="selectin")
    run: Mapped[PipelineRunORM | None] = relationship(lazy="selectin")



class EnrichmentAttemptORM(Base):
    __tablename__ = "enrichment_attempts"
    __table_args__ = (
        UniqueConstraint("game_id", "step"),
        CheckConstraint("step IN ('critic_summary','user_summary','playthrough')"),
        CheckConstraint("state IN ('retrying','abandoned')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    step: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(nullable=False, default=1)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="retrying")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime]
    next_retry_at: Mapped[datetime]


class RunRequestORM(Base):
    __tablename__ = "run_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    requested_at: Mapped[datetime]
    picked_up_at: Mapped[datetime | None]
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"))
    kind: Mapped[str | None] = mapped_column(Text)


class RuntimeConfigORM(Base):
    __tablename__ = "runtime_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(Text, nullable=False)
    min_value: Mapped[float | None]
    max_value: Mapped[float | None]
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime]
    updated_by: Mapped[str | None] = mapped_column(Text)


class PlaythroughTakeawayORM(Base):
    __tablename__ = "playthrough_takeaways"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    video_url: Mapped[str] = mapped_column(Text, nullable=False)
    video_view_count_at_selection: Mapped[int | None] = mapped_column(BigInteger)
    takeaway_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime]
    llm_call_id: Mapped[int | None] = mapped_column(ForeignKey("llm_calls.id", ondelete="SET NULL"))


class YoutubeQuotaUsageORM(Base):
    __tablename__ = "youtube_quota_usage"

    usage_date: Mapped[date] = mapped_column(primary_key=True)
    search_calls: Mapped[int] = mapped_column(nullable=False, default=0)
    units_spent: Mapped[int] = mapped_column(nullable=False, default=0)
