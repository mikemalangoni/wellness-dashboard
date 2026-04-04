"""Fetch the Spine Log Google Doc, parse it, and upsert into Neon Postgres.

Requires DATABASE_URL in the environment (or a .env file).
Run manually or via GitHub Actions nightly cron.
"""

import os
import sys

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from spine_parser import get_dataframes

load_dotenv()


# ── connection ────────────────────────────────────────────────────────────────


def _connect() -> psycopg2.extensions.connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    return psycopg2.connect(url)


# ── aggregate helpers ─────────────────────────────────────────────────────────


def _gi_aggregates(gi_df: pd.DataFrame) -> pd.DataFrame:
    """Return per-date GI aggregates: bm_count, avg_bristol, max_urgency."""
    if gi_df.empty:
        return pd.DataFrame(columns=["date", "bm_count", "avg_bristol", "max_urgency"])
    agg = gi_df.groupby("date").agg(
        bm_count=("bristol", "count"),
        avg_bristol=("bristol", "mean"),
        max_urgency=("urgency", "max"),
    ).reset_index()
    agg["avg_bristol"] = agg["avg_bristol"].round(2)
    return agg


def _exercise_aggregates(ex_df: pd.DataFrame) -> pd.DataFrame:
    """Return per-date exercise aggregates: total_exercise_min, did_exercise."""
    if ex_df.empty:
        return pd.DataFrame(columns=["date", "total_exercise_min", "did_exercise"])
    agg = ex_df.groupby("date").agg(
        total_exercise_min=("duration_min", "sum"),
    ).reset_index()
    agg["did_exercise"] = True
    agg["total_exercise_min"] = agg["total_exercise_min"].where(
        agg["total_exercise_min"] > 0, None
    )
    return agg


# ── upsert helpers ────────────────────────────────────────────────────────────


def _val(row: pd.Series, col: str):
    """Return None for NaN/NaT, otherwise the raw value."""
    v = row.get(col)
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def upsert_entries(cur, df: pd.DataFrame) -> None:
    sql = """
        INSERT INTO entries (
            date, weekday, timezone,
            bed_time, wake_time, sleep_duration,
            deep_min, core_min, rem_min, awake_min,
            deep_pct, rem_pct, core_pct, hrv,
            water_oz, alcohol_count, alcohol_desc,
            mood, focus,
            bm_count, avg_bristol, max_urgency,
            total_exercise_min, did_exercise, rest_day
        ) VALUES %s
        ON CONFLICT (date) DO UPDATE SET
            weekday             = EXCLUDED.weekday,
            timezone            = EXCLUDED.timezone,
            bed_time            = EXCLUDED.bed_time,
            wake_time           = EXCLUDED.wake_time,
            sleep_duration      = EXCLUDED.sleep_duration,
            deep_min            = EXCLUDED.deep_min,
            core_min            = EXCLUDED.core_min,
            rem_min             = EXCLUDED.rem_min,
            awake_min           = EXCLUDED.awake_min,
            deep_pct            = EXCLUDED.deep_pct,
            rem_pct             = EXCLUDED.rem_pct,
            core_pct            = EXCLUDED.core_pct,
            hrv                 = EXCLUDED.hrv,
            water_oz            = EXCLUDED.water_oz,
            alcohol_count       = EXCLUDED.alcohol_count,
            alcohol_desc        = EXCLUDED.alcohol_desc,
            mood                = EXCLUDED.mood,
            focus               = EXCLUDED.focus,
            bm_count            = EXCLUDED.bm_count,
            avg_bristol         = EXCLUDED.avg_bristol,
            max_urgency         = EXCLUDED.max_urgency,
            total_exercise_min  = EXCLUDED.total_exercise_min,
            did_exercise        = EXCLUDED.did_exercise,
            rest_day            = EXCLUDED.rest_day
    """
    rows = [
        (
            _val(r, "date"),
            _val(r, "weekday"),
            _val(r, "timezone"),
            _val(r, "bed_time"),
            _val(r, "wake_time"),
            _val(r, "sleep_duration"),
            _val(r, "deep_min"),
            _val(r, "core_min"),
            _val(r, "rem_min"),
            _val(r, "awake_min"),
            _val(r, "deep_pct"),
            _val(r, "rem_pct"),
            _val(r, "core_pct"),
            _val(r, "hrv"),
            _val(r, "water_oz"),
            _val(r, "alcohol_count"),
            _val(r, "alcohol_desc"),
            _val(r, "mood"),
            _val(r, "focus"),
            _val(r, "bm_count"),
            _val(r, "avg_bristol"),
            _val(r, "max_urgency"),
            _val(r, "total_exercise_min"),
            _val(r, "did_exercise"),
            _val(r, "rest_day"),
        )
        for _, r in df.iterrows()
    ]
    psycopg2.extras.execute_values(cur, sql, rows)


def upsert_gi_events(cur, df: pd.DataFrame) -> None:
    if df.empty:
        return
    dates = tuple(df["date"].dt.date.unique())
    cur.execute("DELETE FROM gi_events WHERE date = ANY(%s)", (list(dates),))
    sql = "INSERT INTO gi_events (date, event_time, bristol, urgency) VALUES %s"
    rows = [
        (
            _val(r, "date"),
            _val(r, "event_time"),
            _val(r, "bristol"),
            _val(r, "urgency"),
        )
        for _, r in df.iterrows()
    ]
    psycopg2.extras.execute_values(cur, sql, rows)


def upsert_exercise_sessions(cur, df: pd.DataFrame) -> None:
    if df.empty:
        return
    dates = tuple(df["date"].dt.date.unique())
    cur.execute("DELETE FROM exercise_sessions WHERE date = ANY(%s)", (list(dates),))
    sql = """
        INSERT INTO exercise_sessions
            (date, activity_type, activity_raw, duration_min, hr_avg, cadence_spm, effort, distance_mi)
        VALUES %s
    """
    rows = [
        (
            _val(r, "date"),
            _val(r, "activity_type"),
            _val(r, "activity_raw"),
            _val(r, "duration_min"),
            _val(r, "hr_avg"),
            _val(r, "cadence_spm"),
            _val(r, "effort"),
            _val(r, "distance_mi"),
        )
        for _, r in df.iterrows()
    ]
    psycopg2.extras.execute_values(cur, sql, rows)


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("Fetching and parsing Google Doc…")
    entries_df, gi_df, ex_df = get_dataframes()
    print(f"  Parsed {len(entries_df)} entries, {len(gi_df)} GI events, {len(ex_df)} exercise sessions")

    # Deduplicate — keep last occurrence if the parser produced duplicate dates
    entries_df = entries_df.drop_duplicates(subset="date", keep="last")
    gi_df = gi_df.drop_duplicates(keep="last")
    ex_df = ex_df.drop_duplicates(keep="last")

    # Compute cross-table aggregates and merge into entries
    gi_agg = _gi_aggregates(gi_df)
    ex_agg = _exercise_aggregates(ex_df)
    entries_df = entries_df.merge(gi_agg, on="date", how="left")
    entries_df = entries_df.merge(ex_agg, on="date", how="left")
    entries_df["did_exercise"] = entries_df["did_exercise"].fillna(False)

    print("Connecting to Neon…")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # entries first (parent), then child event tables
            upsert_entries(cur, entries_df)
            upsert_gi_events(cur, gi_df)
            upsert_exercise_sessions(cur, ex_df)
        conn.commit()
        print(f"Done — upserted {len(entries_df)} entries.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
