CREATE TABLE IF NOT EXISTS games (
    id                  SERIAL PRIMARY KEY,
    metacritic_id       BIGINT       NOT NULL UNIQUE,
    metacritic_slug     TEXT         NOT NULL,
    title               TEXT         NOT NULL,
    cover_image_url     TEXT,
    developer           TEXT,
    description         TEXT,
    video_url           TEXT,
    genres              TEXT[]       NOT NULL DEFAULT '{}',
    first_seen_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_games_genres ON games USING GIN (genres);
CREATE INDEX IF NOT EXISTS idx_games_title ON games (lower(title) text_pattern_ops);

CREATE TABLE IF NOT EXISTS platform_scores (
    id          SERIAL PRIMARY KEY,
    game_id     INTEGER      NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    platform    TEXT         NOT NULL,
    metascore   INTEGER      CHECK (metascore BETWEEN 0 AND 100),
    userscore   NUMERIC(3,1) CHECK (userscore BETWEEN 0.0 AND 10.0),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (game_id, platform)
);

-- llm_calls.game_id had no FK yet (002_llm_calls.sql predates the games table).
ALTER TABLE llm_calls ADD CONSTRAINT fk_llm_calls_game
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS review_summaries (
    id            SERIAL PRIMARY KEY,
    game_id       INTEGER     NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    audience      TEXT        NOT NULL CHECK (audience IN ('critic','user')),
    summary_text  TEXT        NOT NULL,
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    llm_call_id   INTEGER REFERENCES llm_calls(id) ON DELETE SET NULL,
    UNIQUE (game_id, audience)
);
