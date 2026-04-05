CREATE TABLE IF NOT EXISTS reports (
    id            SERIAL PRIMARY KEY,
    report_date   DATE NOT NULL UNIQUE,   -- Sunday of the week being summarized
    period_start  DATE NOT NULL,
    period_end    DATE NOT NULL,
    content       TEXT NOT NULL,          -- markdown narrative from Claude
    model         TEXT,                   -- e.g. 'claude-sonnet-4-5'
    input_tokens  INTEGER,
    output_tokens INTEGER,
    generated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS reports_report_date_idx ON reports (report_date DESC);
