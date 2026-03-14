"""Fetch and parse the Spine Log Google Doc into structured daily records.

Actual entry format (v2, March 2026)
--------------------------------------
    ═══════════════════════════════════════════
    SPINE ENTRY | 2026-03-13 | Friday | EDT
    ═══════════════════════════════════════════

    FOOD & BEVERAGE
    ─────────────────────────────
    ...food items...
    Water: 92 oz
    Alcohol: 2 cocktails — Black Manhattan, Martini

    GI
    ─────────────────────────────
    07:05: Bristol 5 | urgency: low

    SLEEP  (prior night)
    ─────────────────────────────
    Bed: 11:23pm → Wake: 6:47am
    Duration: 7.4 hrs | Apple Watch
    Deep: 64 min | Core: 226 min | REM: 150 min | Awake: 11 min
    HRV: 31 ms

    EXERCISE
    ─────────────────────────────
    ...

    MOOD & FOCUS
    ─────────────────────────────
    Mood: 4/5
    Focus: 3/5

Missing / not-logged fields are returned as None, never as 0.
"""

import re
from datetime import datetime
from typing import Optional

import pandas as pd
from googleapiclient.discovery import build

from google_auth import get_credentials

DOC_ID = "1HVFwRoAInOMjZ_FMwsrdMt7HKCXjsVpV_EEwdGOQxUo"

# ── compiled patterns ─────────────────────────────────────────────────────────

# Entry separator lines (═══...)
_SEP_RE = re.compile(r"^[═\u2550]{3,}\s*$")

# Sub-section divider lines (─────...)
_SUBSEP_RE = re.compile(r"^[─\u2500\-]{3,}\s*$")

# SPINE ENTRY header line
_HEADER_RE = re.compile(
    r"SPINE\s+ENTRY\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(\w+)(?:\s*\|\s*(.+))?",
    re.IGNORECASE,
)

# "— not logged" / "— none logged"
_NOT_LOGGED_RE = re.compile(r"(?:^|\s)[—–]\s*(?:not\s+logged|none\s+logged)", re.IGNORECASE)

# Known section name prefixes (upper-cased). Matched via startswith so that
# "SLEEP  (prior night)" still resolves to "SLEEP".
_SECTION_PREFIXES = [
    "FOOD & BEVERAGE",
    "MOOD & FOCUS",   # check longer names first to avoid prefix collisions
    "EXERCISE",
    "SLEEP",
    "GI",
]


# ── small helpers ─────────────────────────────────────────────────────────────


def _section_name(line: str) -> Optional[str]:
    """Return the canonical section name if *line* is a section header, else None."""
    s = line.strip().upper()
    for name in _SECTION_PREFIXES:
        if s == name or (s.startswith(name) and len(s) > len(name) and s[len(name)] in " \t("):
            return name
    return None


def _safe_float(text: str) -> Optional[float]:
    try:
        return float(str(text).strip())
    except (ValueError, AttributeError):
        return None


def _safe_int(text: str) -> Optional[int]:
    try:
        return int(str(text).strip())
    except (ValueError, AttributeError):
        return None


def _not_logged(value: str) -> bool:
    return bool(_NOT_LOGGED_RE.search(value))


# ── document fetching ─────────────────────────────────────────────────────────


def fetch_document_text(doc_id: str = DOC_ID) -> str:
    """Return the full text of the Google Doc as a newline-joined string."""
    creds = get_credentials()
    service = build("docs", "v1", credentials=creds)
    doc = service.documents().get(documentId=doc_id).execute()

    lines: list[str] = []
    for element in doc.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if paragraph is None:
            continue
        text = ""
        for pe in paragraph.get("elements", []):
            text_run = pe.get("textRun")
            if text_run:
                text += text_run.get("content", "")
        lines.append(text.rstrip("\n"))

    return "\n".join(lines)


# ── entry splitting ───────────────────────────────────────────────────────────


def _split_entries(text: str) -> list[str]:
    """Return one raw text chunk per SPINE ENTRY, with separator/divider lines stripped.

    Because each entry is wrapped in ═══ lines both above *and* below its
    header, splitting on ═══ would separate the header from its body. Instead
    we locate every SPINE ENTRY header line and use those as split points.
    """
    lines = text.splitlines()
    header_positions = [i for i, line in enumerate(lines) if _HEADER_RE.search(line)]

    chunks: list[str] = []
    for idx, start in enumerate(header_positions):
        end = header_positions[idx + 1] if idx + 1 < len(header_positions) else len(lines)
        # Keep all lines in range, but drop ═══ and ─── separator lines
        chunk_lines = [
            l for l in lines[start:end]
            if not _SEP_RE.match(l) and not _SUBSEP_RE.match(l)
        ]
        chunks.append("\n".join(chunk_lines))

    return chunks


# ── section-level parsers ─────────────────────────────────────────────────────


def _parse_sleep(lines: list[str]) -> dict:
    result: dict = {
        "bed_time": None,
        "wake_time": None,
        "sleep_duration": None,
        "deep_min": None,
        "core_min": None,
        "rem_min": None,
        "awake_min": None,
        "hrv": None,
    }

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # Combined bed→wake line: "Bed: 11:23pm → Wake: 6:47am"
        m = re.match(
            r"Bed\s*[:\-]\s*(.+?)\s*[→\->]+\s*Wake\s*[:\-]\s*(.+)",
            line, re.IGNORECASE,
        )
        if m:
            result["bed_time"] = m.group(1).strip()
            result["wake_time"] = m.group(2).strip()
            continue

        # Separate bed/wake lines (fallback)
        m = re.match(r"Bed(?:\s*time)?\s*[:\-]\s*(.+)", line, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if not _not_logged(val):
                result["bed_time"] = val
            continue

        m = re.match(r"Wake(?:\s*time)?\s*[:\-]\s*(.+)", line, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if not _not_logged(val):
                result["wake_time"] = val
            continue

        # Duration: "Duration: 7.4 hrs | Apple Watch"  or  "Duration (hrs): 8.0"
        m = re.match(
            r"Duration\s*(?:[\(\[]hrs?[\)\]])?\s*[:\-]\s*([\d.]+)",
            line, re.IGNORECASE,
        )
        if m:
            result["sleep_duration"] = _safe_float(m.group(1))
            continue

        # Combined stages line: "Deep: 64 min | Core: 226 min | REM: 150 min | Awake: 11 min"
        if re.search(r"Deep", line, re.IGNORECASE) and re.search(r"Core|REM", line, re.IGNORECASE):
            for field, key in [
                ("Deep", "deep_min"),
                ("Core", "core_min"),
                ("REM", "rem_min"),
                ("Awake", "awake_min"),
            ]:
                sm = re.search(rf"{field}\s*[:\-]\s*([\d.]+)", line, re.IGNORECASE)
                if sm:
                    result[key] = _safe_float(sm.group(1))
            continue

        # Individual stage lines (fallback)
        for field, key in [
            ("Deep", "deep_min"),
            ("Core", "core_min"),
            ("REM", "rem_min"),
            ("Awake", "awake_min"),
        ]:
            m = re.match(rf"{field}\s*[:\-]\s*([\d.]+)", line, re.IGNORECASE)
            if m:
                result[key] = _safe_float(m.group(1))
                break

        # HRV: "HRV: 31 ms"
        m = re.match(r"HRV\s*[:\-]\s*([\d.]+)", line, re.IGNORECASE)
        if m:
            result["hrv"] = _safe_float(m.group(1))

    return result


# GI event: "07:05: Bristol 5 | urgency: low"
#           "8:00 AM — Bristol 4 — some note"   (legacy / alternate)
_GI_EVENT_RE = re.compile(
    r"(\d{1,2}:\d{2}(?:\s*[aApP][mM])?)\s*[:\-–—]\s*Bristol\s*(\d)"
    r"(?:\s*[|—\-–]\s*urgency\s*[:\-]\s*(.+))?",
    re.IGNORECASE,
)

_WATER_RE = re.compile(r"Water\s*[:\-]\s*(.+)", re.IGNORECASE)
_ALCOHOL_RE = re.compile(r"Alcohol\s*[:\-]\s*(.+)", re.IGNORECASE)


def _extract_water_alcohol(lines: list[str]) -> dict:
    fields: dict = {"water_oz": None, "alcohol_count": None, "alcohol_desc": None}

    for raw in lines:
        line = raw.strip()

        m = _WATER_RE.match(line)
        if m:
            val = m.group(1).strip()
            if not _not_logged(val):
                num = re.search(r"([\d.]+)", val)
                if num:
                    fields["water_oz"] = _safe_float(num.group(1))
            continue

        m = _ALCOHOL_RE.match(line)
        if m:
            val = m.group(1).strip()
            if not _not_logged(val):
                # "2 cocktails — Black Manhattan, Martini"
                num = re.match(r"(\d+)", val)
                if num:
                    fields["alcohol_count"] = _safe_int(num.group(1))
                    rest = val[num.end():].strip().lstrip("—–- ").strip()
                    fields["alcohol_desc"] = rest or None
                else:
                    fields["alcohol_desc"] = val
            continue

    return fields


def _parse_gi(lines: list[str]) -> tuple[dict, list[dict]]:
    """Return (gi_fields_dict, gi_events_list)."""
    events: list[dict] = []

    for raw in lines:
        line = raw.strip()
        if not line or _not_logged(line):
            continue
        m = _GI_EVENT_RE.search(line)
        if m:
            events.append(
                {
                    "time": m.group(1).strip(),
                    "bristol": _safe_int(m.group(2)),
                    "urgency": m.group(3).strip() if m.group(3) else None,
                }
            )

    fields = _extract_water_alcohol(lines)
    return fields, events


def _parse_time_to_minutes(t: str) -> Optional[int]:
    """Convert HH:MM or HHMM to minutes since midnight."""
    t = t.strip()
    if ":" in t:
        m = re.match(r"(\d{1,2}):(\d{2})", t)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
    else:
        m = re.match(r"(\d{2})(\d{2})$", t)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
    return None


def _duration_from_range(s: str) -> Optional[int]:
    """Return minutes from a time-range string like '7:13–7:57' or '0716–0800'."""
    m = re.search(r"(\d{1,2}:?\d{2})\s*[–\-]\s*(\d{1,2}:?\d{2})", s)
    if not m:
        return None
    start = _parse_time_to_minutes(m.group(1))
    end = _parse_time_to_minutes(m.group(2))
    if start is None or end is None:
        return None
    diff = end - start
    if diff < 0:
        diff += 24 * 60  # midnight crossing
    return diff if diff > 0 else None


def _normalize_activity(raw: str) -> str:
    r = raw.strip().lower()
    if "strength" in r or "weight" in r or "lift" in r:
        return "Strength"
    if "movement" in r:
        return "Movement"
    if "run" in r or "jog" in r:
        return "Run"
    if "walk" in r:
        return "Walk"
    if "yoga" in r:
        return "Yoga"
    if "bike" in r or "cycl" in r:
        return "Cycling"
    if "swim" in r:
        return "Swimming"
    if r == "activity":
        return "Activity"
    return raw.strip().title()


_EXERCISE_SKIP_RE = re.compile(
    r"^(?:—\s*)?(?:not\s+logged|none\s+logged|rest\s+day|activity)$",
    re.IGNORECASE,
)

# Lines that are sub-details regardless of indentation
_DETAIL_RE = re.compile(
    r"^(?:HR\s*avg|Cadence|Distance|Effort|Notes|Elevation)\s*[:\-]",
    re.IGNORECASE,
)


def _parse_exercise(lines: list[str]) -> list[dict]:
    """Return one dict per activity event in the EXERCISE section."""
    events: list[dict] = []
    current: Optional[dict] = None

    for raw in lines:
        is_indented = raw != raw.lstrip()
        line = raw.strip()
        if not line:
            continue

        # Treat as a sub-detail if indented OR if it matches a known detail pattern
        is_detail = is_indented or bool(_DETAIL_RE.match(line))

        if not is_detail:
            # Skip rest days, not-logged markers, and bare "Activity" placeholders
            if _EXERCISE_SKIP_RE.match(line):
                if current is not None:
                    events.append(current)
                    current = None
                continue

            # Save previous activity
            if current is not None:
                events.append(current)

            # Parse the main activity line: "Name | time | Xmin [| ...]"
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                activity_raw = parts[0]
                duration_min = None
                # 1) explicit "X min"
                for part in parts[1:]:
                    m = re.search(r"(\d+)\s*min", part, re.IGNORECASE)
                    if m:
                        duration_min = _safe_int(m.group(1))
                        break
                # 2) compute from start–end time range
                if duration_min is None:
                    for part in parts[1:]:
                        duration_min = _duration_from_range(part)
                        if duration_min is not None:
                            break
            else:
                activity_raw = line
                duration_min = None

            current = {
                "activity_raw": activity_raw,
                "activity_type": _normalize_activity(activity_raw),
                "duration_min": duration_min,
                "hr_avg": None,
                "cadence_spm": None,
                "effort": None,
                "distance_mi": None,
            }
        else:
            if current is None:
                continue
            # Sub-line details
            m = re.match(r"HR\s*avg\s*[:\-]\s*(\d+)", line, re.IGNORECASE)
            if m:
                current["hr_avg"] = _safe_int(m.group(1))
                continue
            m = re.match(r"Cadence\s*[:\-]\s*(\d+)", line, re.IGNORECASE)
            if m:
                current["cadence_spm"] = _safe_int(m.group(1))
                continue
            m = re.match(r"Effort\s*[:\-]\s*(\d)", line, re.IGNORECASE)
            if m:
                current["effort"] = _safe_int(m.group(1))
                continue
            m = re.search(r"Distance\s*[:\-]\s*([\d.]+)\s*mi", line, re.IGNORECASE)
            if m:
                current["distance_mi"] = _safe_float(m.group(1))
                continue

    if current is not None:
        events.append(current)

    return events


def _parse_mood(lines: list[str]) -> dict:
    result: dict = {"mood": None, "focus": None}

    for raw in lines:
        line = raw.strip()
        # Accept "4/5" or just "4"
        m = re.match(r"Mood\s*[:\-]\s*(\d)(?:/\d+)?", line, re.IGNORECASE)
        if m:
            result["mood"] = _safe_int(m.group(1))
            continue

        m = re.match(r"Focus\s*[:\-]\s*(\d)(?:/\d+)?", line, re.IGNORECASE)
        if m:
            result["focus"] = _safe_int(m.group(1))
            continue

    return result


# ── entry parser ──────────────────────────────────────────────────────────────


def _parse_entry(chunk: str) -> Optional[dict]:
    """Parse one entry chunk. Returns None if the chunk has no valid header."""
    lines = chunk.splitlines()

    # First line should be the SPINE ENTRY header
    entry_date = None
    weekday = None
    timezone = None
    header_idx: Optional[int] = None

    for i, line in enumerate(lines):
        m = _HEADER_RE.search(line)
        if m:
            try:
                entry_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            weekday = m.group(2).strip()
            timezone = m.group(3).strip() if m.group(3) else "EST"
            header_idx = i
            break

    if entry_date is None:
        return None

    # Bucket remaining lines into sections
    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    section_lines: list[str] = []

    for line in lines[header_idx + 1 :]:
        sec = _section_name(line)
        if sec:
            if current is not None:
                sections[current] = section_lines
            current = sec
            section_lines = []
        else:
            if current is not None:
                section_lines.append(line)

    if current is not None:
        sections[current] = section_lines

    # Parse sections
    sleep_data = _parse_sleep(sections.get("SLEEP", []))
    gi_fields, gi_events = _parse_gi(sections.get("GI", []))
    food_fields = _extract_water_alcohol(sections.get("FOOD & BEVERAGE", []))
    mood_data = _parse_mood(sections.get("MOOD & FOCUS", []))
    exercise_events = _parse_exercise(sections.get("EXERCISE", []))

    # Water / alcohol: prefer GI section, fall back to FOOD & BEVERAGE
    water_oz = (
        gi_fields["water_oz"]
        if gi_fields["water_oz"] is not None
        else food_fields["water_oz"]
    )
    alcohol_count = (
        gi_fields["alcohol_count"]
        if gi_fields["alcohol_count"] is not None
        else food_fields["alcohol_count"]
    )
    alcohol_desc = (
        gi_fields["alcohol_desc"]
        if gi_fields["alcohol_desc"] is not None
        else food_fields["alcohol_desc"]
    )

    return {
        "date": entry_date,
        "weekday": weekday,
        "timezone": timezone,
        **sleep_data,
        "water_oz": water_oz,
        "alcohol_count": alcohol_count,
        "alcohol_desc": alcohol_desc,
        **mood_data,
        "_gi_events": gi_events,
        "_exercise_events": exercise_events,
    }


# ── public API ────────────────────────────────────────────────────────────────


def parse_entries(text: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Parse the full doc text into (entries_df, gi_events_df, exercise_df)."""
    chunks = _split_entries(text)

    entries: list[dict] = []
    gi_rows: list[dict] = []
    exercise_rows: list[dict] = []

    for chunk in chunks:
        try:
            entry = _parse_entry(chunk)
        except Exception:
            continue

        if entry is None:
            continue

        gi_events: list[dict] = entry.pop("_gi_events")
        ex_events: list[dict] = entry.pop("_exercise_events")
        entries.append(entry)
        for ev in gi_events:
            gi_rows.append({"date": entry["date"], **ev})
        for ev in ex_events:
            exercise_rows.append({"date": entry["date"], **ev})

    entries_df = pd.DataFrame(entries) if entries else pd.DataFrame()
    gi_events_df = pd.DataFrame(gi_rows) if gi_rows else pd.DataFrame()
    exercise_df = pd.DataFrame(exercise_rows) if exercise_rows else pd.DataFrame()

    for df in [entries_df, gi_events_df, exercise_df]:
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

    if not entries_df.empty:
        entries_df = entries_df.sort_values("date").reset_index(drop=True)
    if not gi_events_df.empty:
        gi_events_df = gi_events_df.sort_values("date").reset_index(drop=True)
    if not exercise_df.empty:
        exercise_df = exercise_df.sort_values("date").reset_index(drop=True)

    return entries_df, gi_events_df, exercise_df


def get_dataframes(doc_id: str = DOC_ID) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch the Google Doc and return (entries_df, gi_events_df, exercise_df)."""
    text = fetch_document_text(doc_id)
    return parse_entries(text)
