-- Каждый вызов LLM (резюме отзывов критиков/игроков, заключение по летсплею).
CREATE TABLE IF NOT EXISTS llm_calls (
    id             SERIAL PRIMARY KEY,
    call_type      TEXT          NOT NULL,  -- 'critic_summary' | 'user_summary' | 'playthrough_takeaway'
    game_id        INTEGER,                 -- FK на games, добавится с доменной моделью
    model          TEXT          NOT NULL,
    input_tokens   INTEGER       NOT NULL DEFAULT 0,
    output_tokens  INTEGER       NOT NULL DEFAULT 0,
    cost_usd       NUMERIC(10,6) NOT NULL DEFAULT 0,
    status         TEXT          NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','error','fallback')),
    error_message  TEXT,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_type ON llm_calls(call_type, created_at DESC);

-- Пересчёт cost_usd при обновлении справочника meta.llm_model_costs:
-- UPDATE llm_calls t SET cost_usd = (
--     SELECT t.input_tokens/1e6*c.input_cost_per_1m + t.output_tokens/1e6*c.output_cost_per_1m
--     FROM meta.llm_model_costs c
--     WHERE c.model = t.model AND c.provider = 'openrouter'
--       AND c.valid_from <= t.created_at::date AND (c.valid_until IS NULL OR c.valid_until >= t.created_at::date)
--     ORDER BY c.valid_from DESC LIMIT 1
-- );
