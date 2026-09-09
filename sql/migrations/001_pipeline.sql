-- Наблюдаемость hourly-ингестии (см. .specify/../specs/001-metacritic-game-tracker/spec.md).
-- Один прогон = одна стадия (ingest / summarize / playthrough).
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              SERIAL PRIMARY KEY,
    stage           TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running','completed','failed')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    items_in        INTEGER     NOT NULL DEFAULT 0,
    items_accepted  INTEGER     NOT NULL DEFAULT 0,
    items_rejected  INTEGER     NOT NULL DEFAULT 0,
    items_deferred  INTEGER     NOT NULL DEFAULT 0,
    items_errored   INTEGER     NOT NULL DEFAULT 0,
    code_version    TEXT,
    source          TEXT,       -- 'new_releases' | 'see_all_newest'
    error_message   TEXT,
    meta            JSONB       NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_stage ON pipeline_runs(stage, started_at DESC);

CREATE TABLE IF NOT EXISTS pipeline_rejects (
    id            SERIAL PRIMARY KEY,
    stage         TEXT        NOT NULL,
    run_id        INTEGER     REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    item_ref      TEXT        NOT NULL,
    reason_code   TEXT        NOT NULL,
    reason_detail TEXT,
    payload       JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pipeline_rejects_reason ON pipeline_rejects(stage, reason_code, created_at DESC);
