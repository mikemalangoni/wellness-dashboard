"""
Generate a weekly wellness synthesis using GitHub Models (OpenAI-compatible API).
Reads the skill file at .claude/wellness_analysis.md as the system prompt.
Saves output to the reports table in Neon Postgres.

Run after ingest.py completes. Called from GitHub Actions.
Skips gracefully if fewer than 4 entries exist for the past 7 days.

Requires GITHUB_TOKEN in environment. In Actions this is available automatically
via secrets.GITHUB_TOKEN — no extra secret needed.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

from openai import OpenAI
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

SKILL_PATH = Path(__file__).parent / ".claude" / "wellness_analysis.md"
MODEL = "gpt-4o-mini"  # free via GitHub Models; swap to "gpt-4o" for more capability
GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
MIN_ENTRIES = 4  # skip report generation if fewer than this many entries this week


def _connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    return psycopg2.connect(url)


def fetch_week_data(cur, period_start: date, period_end: date) -> list[dict]:
    cur.execute("""
        SELECT
            date, weekday,
            sleep_duration, deep_pct, rem_pct, core_pct, awake_min, hrv,
            bed_time, wake_time,
            mood, focus,
            water_oz, alcohol_count, alcohol_desc,
            bm_count, avg_bristol, max_urgency,
            total_exercise_min, did_exercise, rest_day
        FROM entries
        WHERE date >= %s AND date <= %s
        ORDER BY date
    """, (period_start, period_end))
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_baseline(cur, period_start: date) -> dict:
    """30-day rolling averages ending at period_start (exclusive) for comparison."""
    baseline_end = period_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=29)
    cur.execute("""
        SELECT
            ROUND(AVG(sleep_duration)::numeric, 1) AS avg_sleep,
            ROUND(AVG(hrv)::numeric, 0)            AS avg_hrv,
            ROUND(AVG(mood)::numeric, 1)           AS avg_mood,
            ROUND(AVG(focus)::numeric, 1)          AS avg_focus,
            ROUND(AVG(deep_pct * 100)::numeric, 1) AS avg_deep_pct,
            ROUND(AVG(rem_pct * 100)::numeric, 1)  AS avg_rem_pct,
            ROUND(AVG(water_oz)::numeric, 0)       AS avg_water,
            ROUND(AVG(bm_count)::numeric, 1)       AS avg_bm,
            ROUND(AVG(avg_bristol)::numeric, 1)    AS avg_bristol,
            COUNT(*)                               AS n_days
        FROM entries
        WHERE date >= %s AND date <= %s
    """, (baseline_start, baseline_end))
    cols = [desc[0] for desc in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else {}


def format_context(week_data: list[dict], baseline: dict, period_start: date, period_end: date) -> str:
    """Assemble a readable text context block to pass as the user message."""
    lines = [
        f"## Weekly Data: {period_start.strftime('%B %d')} – {period_end.strftime('%B %d, %Y')}",
        f"({len(week_data)} entries this week)\n",
        "### 30-Day Baseline (prior 30 days)",
    ]

    def b(key, unit=""):
        v = baseline.get(key)
        return f"{v}{unit}" if v is not None else "—"

    lines += [
        f"- Avg sleep: {b('avg_sleep', 'h')}",
        f"- Avg HRV: {b('avg_hrv', ' ms')}",
        f"- Avg mood: {b('avg_mood', '/5')}, avg focus: {b('avg_focus', '/5')}",
        f"- Avg deep sleep: {b('avg_deep_pct', '%')}, avg REM: {b('avg_rem_pct', '%')}",
        f"- Avg water: {b('avg_water', ' oz')}",
        f"- Avg BMs/day: {b('avg_bm')}, avg Bristol: {b('avg_bristol')}",
        f"- Based on {baseline.get('n_days', '?')} days\n",
        "### Daily Entries This Week",
    ]

    for e in week_data:
        d = e['date']
        day_label = f"{e.get('weekday', '')} {d}"

        sleep = f"{e['sleep_duration']}h" if e.get('sleep_duration') else "—"
        hrv = f"{e['hrv']} ms" if e.get('hrv') else "—"
        mood = f"{e['mood']}/5" if e.get('mood') else "—"
        focus = f"{e['focus']}/5" if e.get('focus') else "—"

        deep = f"{round(float(e['deep_pct']) * 100, 1)}%" if e.get('deep_pct') else "—"
        rem = f"{round(float(e['rem_pct']) * 100, 1)}%" if e.get('rem_pct') else "—"
        awake = f"{e['awake_min']} min awake" if e.get('awake_min') else ""

        alcohol = f"alcohol: {e['alcohol_count']}" if e.get('alcohol_count') else ""
        if e.get('alcohol_desc') and alcohol:
            alcohol += f" ({e['alcohol_desc']})"

        exercise = f"exercise: {e['total_exercise_min']} min" if e.get('total_exercise_min') else (
            "rest day" if e.get('rest_day') else "no exercise logged"
        )

        bm = f"BMs: {e['bm_count']} (Bristol avg {e['avg_bristol']})" if e.get('bm_count') else "—"
        water = f"{e['water_oz']} oz water" if e.get('water_oz') else ""

        parts = [p for p in [sleep, f"HRV {hrv}", f"deep {deep}", f"REM {rem}", awake,
                              f"mood {mood}", f"focus {focus}", exercise, bm, water, alcohol] if p and p != "—"]
        lines.append(f"**{day_label}:** {' | '.join(parts)}")

    lines += [
        "\n### Your Task",
        "Using the framework in your instructions, generate the weekly synthesis. "
        "Focus on what's actually interesting and meaningful. Skip metrics that didn't move.",
    ]

    return "\n".join(lines)


def generate_synthesis(system_prompt: str, user_message: str) -> tuple[str, str, int, int]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    client = OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=token)
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    content = response.choices[0].message.content
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    return content, response.model, input_tokens, output_tokens


def upsert_report(cur, report_date: date, period_start: date, period_end: date,
                  content: str, model: str, input_tokens: int, output_tokens: int) -> None:
    cur.execute("""
        INSERT INTO reports (report_date, period_start, period_end, content, model, input_tokens, output_tokens)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (report_date) DO UPDATE SET
            period_start  = EXCLUDED.period_start,
            period_end    = EXCLUDED.period_end,
            content       = EXCLUDED.content,
            model         = EXCLUDED.model,
            input_tokens  = EXCLUDED.input_tokens,
            output_tokens = EXCLUDED.output_tokens,
            generated_at  = NOW()
    """, (report_date, period_start, period_end, content, model, input_tokens, output_tokens))


def main():
    period_end = date.today() - timedelta(days=1)   # yesterday
    period_start = period_end - timedelta(days=6)   # 7-day window
    report_date = period_end                         # keyed to end of period

    if not SKILL_PATH.exists():
        sys.exit(f"Skill file not found at {SKILL_PATH}")

    system_prompt = SKILL_PATH.read_text()

    conn = _connect()
    try:
        with conn.cursor() as cur:
            week_data = fetch_week_data(cur, period_start, period_end)

            if len(week_data) < MIN_ENTRIES:
                print(f"Only {len(week_data)} entries this week (min {MIN_ENTRIES}). Skipping report.")
                return

            baseline = fetch_baseline(cur, period_start)
            user_message = format_context(week_data, baseline, period_start, period_end)

            print(f"Calling {MODEL} for weekly synthesis ({period_start} – {period_end})…")
            content, model, in_tok, out_tok = generate_synthesis(system_prompt, user_message)
            print(f"  Generated {out_tok} tokens (used {in_tok} input tokens)")

            upsert_report(cur, report_date, period_start, period_end, content, model, in_tok, out_tok)
        conn.commit()
        print(f"Done — report saved for {report_date}.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
