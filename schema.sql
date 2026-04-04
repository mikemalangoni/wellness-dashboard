-- Wellness dashboard schema
-- Run once against your Neon database to create all tables.

CREATE TABLE IF NOT EXISTS entries (
    date            DATE PRIMARY KEY,
    weekday         TEXT,
    timezone        TEXT,

    -- sleep
    bed_time        TIMESTAMPTZ,
    wake_time       TIMESTAMPTZ,
    sleep_duration  NUMERIC,
    deep_min        NUMERIC,
    core_min        NUMERIC,
    rem_min         NUMERIC,
    awake_min       NUMERIC,
    deep_pct        NUMERIC,
    rem_pct         NUMERIC,
    core_pct        NUMERIC,
    hrv             NUMERIC,

    -- intake
    water_oz        NUMERIC,
    alcohol_count   INTEGER,
    alcohol_desc    TEXT,

    -- mood
    mood            INTEGER,
    focus           INTEGER,

    -- GI daily aggregates (derived at ingest time)
    bm_count        INTEGER,
    avg_bristol     NUMERIC,
    max_urgency     INTEGER,    -- 1=low 2=moderate 3=high

    -- exercise daily aggregates (derived at ingest time)
    total_exercise_min  INTEGER,
    did_exercise        BOOLEAN,
    rest_day            BOOLEAN
);

CREATE TABLE IF NOT EXISTS gi_events (
    id          SERIAL PRIMARY KEY,
    date        DATE NOT NULL REFERENCES entries(date) ON DELETE CASCADE,
    event_time  TIME,
    bristol     INTEGER,
    urgency     INTEGER         -- 1=low 2=moderate 3=high
);

CREATE INDEX IF NOT EXISTS gi_events_date_idx ON gi_events(date);

CREATE TABLE IF NOT EXISTS exercise_sessions (
    id            SERIAL PRIMARY KEY,
    date          DATE NOT NULL REFERENCES entries(date) ON DELETE CASCADE,
    activity_type TEXT,
    activity_raw  TEXT,
    duration_min  INTEGER,
    hr_avg        INTEGER,
    cadence_spm   INTEGER,
    effort        INTEGER,
    distance_mi   NUMERIC
);

CREATE INDEX IF NOT EXISTS exercise_sessions_date_idx ON exercise_sessions(date);
