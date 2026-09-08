CREATE SCHEMA IF NOT EXISTS meta;

-- Справочник цен на LLM-модели. Обновляй valid_from/valid_until при смене цен —
-- это позволяет пересчитывать исторические расходы без потери данных.
CREATE TABLE IF NOT EXISTS meta.llm_model_costs (
    id                  SERIAL PRIMARY KEY,
    model               TEXT         NOT NULL,
    provider            TEXT         NOT NULL,
    input_cost_per_1m   NUMERIC(12,6) NOT NULL,
    output_cost_per_1m  NUMERIC(12,6) NOT NULL,
    context_window      INTEGER,
    valid_from          DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_until         DATE,
    notes               TEXT,
    UNIQUE (model, provider, valid_from)
);

INSERT INTO meta.llm_model_costs
    (model, provider, input_cost_per_1m, output_cost_per_1m, context_window, valid_from)
VALUES
    ('anthropic/claude-haiku-4-5',   'openrouter',  0.80,   4.00,  200000, '2026-01-01'),
    ('anthropic/claude-sonnet-4-5',  'openrouter',  3.00,  15.00,  200000, '2026-01-01'),
    ('moonshotai/kimi-k2-thinking',  'openrouter',  1.00,   3.00,  131072, '2026-01-01')
ON CONFLICT DO NOTHING;
