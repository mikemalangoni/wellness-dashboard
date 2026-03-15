"""Streamlit wellness dashboard for the Spine Log."""

import numpy as np
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from spine_parser import get_dataframes

st.set_page_config(page_title="Wellness Dashboard", page_icon="🌿", layout="wide")
st.title("Wellness Dashboard — Spine Log")

# ── data loading ──────────────────────────────────────────────────────────────


@st.cache_data(ttl=300)
def load_data():
    return get_dataframes()


with st.spinner("Fetching data from Google Docs…"):
    try:
        entries_df, gi_events_df, exercise_df = load_data()
    except Exception as exc:
        st.error(f"Could not load data: {exc}")
        st.stop()

if entries_df.empty:
    st.warning("No entries found in the document.")
    st.stop()

# Global date bounds for tab date pickers
_all_dates = pd.concat(
    [entries_df["date"]]
    + ([gi_events_df["date"]] if not gi_events_df.empty else [])
    + ([exercise_df["date"]] if not exercise_df.empty else [])
).dropna()
_min_date = _all_dates.min().date()
_max_date = _all_dates.max().date()

# Summary strip
col1, col2, col3, col4 = st.columns(4)
col1.metric("Entries", len(entries_df))
col2.metric(
    "Avg Sleep",
    f"{entries_df['sleep_duration'].mean():.1f} h"
    if entries_df["sleep_duration"].notna().any()
    else "—",
)
col3.metric(
    "Avg Mood",
    f"{entries_df['mood'].mean():.1f} / 5"
    if entries_df["mood"].notna().any()
    else "—",
)
col4.metric("GI Events", len(gi_events_df) if not gi_events_df.empty else 0)

st.divider()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["💤 Sleep Trends", "🫀 GI Log", "🧠 Mood & Focus", "🏃 Exercise", "🏅 Running", "🔗 Correlations"])

# ── TAB 1 — Sleep Trends ──────────────────────────────────────────────────────

with tab1:
    st.header("Sleep Trends")

    _dr1 = st.date_input(
        "Date range",
        value=(_min_date, _max_date),
        min_value=_min_date,
        max_value=_max_date,
        key="sleep_date_range",
    )

    sleep_df = entries_df[
        ["date", "sleep_duration", "deep_min", "core_min", "rem_min", "awake_min", "hrv"]
    ].copy()
    if len(_dr1) == 2:
        _s1, _e1 = _dr1
        sleep_df = sleep_df[(sleep_df["date"].dt.date >= _s1) & (sleep_df["date"].dt.date <= _e1)]

    has_duration = sleep_df["sleep_duration"].notna().any()

    if not has_duration:
        st.info("No sleep duration data found yet.")
    else:
        # Duration over time
        dur_data = sleep_df.dropna(subset=["sleep_duration"])
        fig_dur = px.line(
            dur_data,
            x="date",
            y="sleep_duration",
            title="Sleep Duration",
            labels={"sleep_duration": "Hours", "date": "Date"},
            markers=True,
        )
        fig_dur.add_hline(
            y=8,
            line_dash="dash",
            line_color="green",
            annotation_text="8 h target",
            annotation_position="top right",
        )
        fig_dur.update_layout(hovermode="x unified", yaxis=dict(rangemode="tozero"))
        st.plotly_chart(fig_dur, use_container_width=True)

        # Apple Watch sleep-stage breakdown
        stage_cols = ["deep_min", "core_min", "rem_min", "awake_min"]
        watch_df = sleep_df.dropna(subset=stage_cols, how="all")

        if watch_df.empty:
            st.info("No Apple Watch sleep-stage data found yet.")
        else:
            st.subheader("Sleep Stage Breakdown (Apple Watch)")

            stages = watch_df[["date"] + stage_cols].melt(
                id_vars="date", var_name="stage", value_name="minutes"
            )
            stage_labels = {
                "deep_min": "Deep",
                "core_min": "Core",
                "rem_min": "REM",
                "awake_min": "Awake",
            }
            stages["stage"] = stages["stage"].map(stage_labels)
            stages = stages.dropna(subset=["minutes"])

            fig_stages = px.bar(
                stages,
                x="date",
                y="minutes",
                color="stage",
                title="Sleep Stage Minutes",
                labels={"minutes": "Minutes", "date": "Date", "stage": "Stage"},
                barmode="stack",
                color_discrete_map={
                    "Deep": "#1f4e79",
                    "Core": "#2e75b6",
                    "REM": "#9dc3e6",
                    "Awake": "#ffd966",
                },
                category_orders={"stage": ["Deep", "Core", "REM", "Awake"]},
            )
            fig_stages.update_layout(hovermode="x unified")
            st.plotly_chart(fig_stages, use_container_width=True)

            # HRV
            hrv_data = sleep_df.dropna(subset=["hrv"])
            if not hrv_data.empty:
                fig_hrv = px.line(
                    hrv_data,
                    x="date",
                    y="hrv",
                    title="HRV Over Time",
                    labels={"hrv": "HRV (ms)", "date": "Date"},
                    markers=True,
                )
                fig_hrv.update_layout(hovermode="x unified")
                st.plotly_chart(fig_hrv, use_container_width=True)

# ── TAB 2 — GI Log ───────────────────────────────────────────────────────────

with tab2:
    st.header("GI Log")

    _dr2 = st.date_input(
        "Date range",
        value=(_min_date, _max_date),
        min_value=_min_date,
        max_value=_max_date,
        key="gi_date_range",
    )

    if gi_events_df.empty:
        st.info("No GI events logged yet.")
    else:
        _gi2 = gi_events_df.copy()
        _ent2 = entries_df.copy()
        if len(_dr2) == 2:
            _s2, _e2 = _dr2
            _gi2 = _gi2[(_gi2["date"].dt.date >= _s2) & (_gi2["date"].dt.date <= _e2)]
            _ent2 = _ent2[(_ent2["date"].dt.date >= _s2) & (_ent2["date"].dt.date <= _e2)]

        # Bristol scatter + mood & focus trendlines
        fig_bristol = make_subplots(specs=[[{"secondary_y": True}]])

        # Symmetric scale: 4 = green, 1 and 7 = red, 2/6 = orange, 3/5 = yellow
        BRISTOL_COLORS = {
            1: "#d7191c",
            2: "#f17c4a",
            3: "#fec981",
            4: "#1a9641",
            5: "#fec981",
            6: "#f17c4a",
            7: "#d7191c",
        }

        # Bristol dots (colour-coded by score)
        for score in sorted(_gi2["bristol"].dropna().unique()):
            subset = _gi2[_gi2["bristol"] == score]
            color_hex = BRISTOL_COLORS.get(int(score), "#888888")
            fig_bristol.add_trace(
                go.Scatter(
                    x=subset["date"],
                    y=subset["bristol"],
                    mode="markers",
                    marker=dict(size=11, color=color_hex, line=dict(width=1, color="white")),
                    name=f"Bristol {int(score)}",
                    customdata=subset[["time", "urgency"]].values,
                    hovertemplate="Bristol %{y}<br>%{customdata[0]}<br>Urgency: %{customdata[1]}<extra></extra>",
                ),
                secondary_y=False,
            )

        # Mood trendline
        mood_data = _ent2.dropna(subset=["mood"])
        if not mood_data.empty:
            fig_bristol.add_trace(
                go.Scatter(
                    x=mood_data["date"],
                    y=mood_data["mood"],
                    mode="lines",
                    name="Mood",
                    line=dict(color="rgba(147,112,219,0.35)", width=1.5, dash="dot"),
                ),
                secondary_y=True,
            )

        # Focus trendline
        focus_data = _ent2.dropna(subset=["focus"])
        if not focus_data.empty:
            fig_bristol.add_trace(
                go.Scatter(
                    x=focus_data["date"],
                    y=focus_data["focus"],
                    mode="lines",
                    name="Focus",
                    line=dict(color="rgba(100,149,237,0.35)", width=1.5, dash="dot"),
                ),
                secondary_y=True,
            )

        fig_bristol.update_layout(
            title="Bristol Score per Bowel Movement with Mood & Focus",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig_bristol.update_yaxes(range=[0.5, 7.5], dtick=1, title_text="Bristol Score (1–7)", secondary_y=False)
        fig_bristol.update_yaxes(range=[0.5, 5.5], dtick=1, title_text="Score (1–5)", secondary_y=True)
        st.plotly_chart(fig_bristol, use_container_width=True)

        # BM frequency per day + water & alcohol overlay
        bm_freq = (
            _gi2.groupby("date").size().reset_index(name="bm_count")
        )
        overlay = _ent2[["date", "water_oz", "alcohol_count"]].copy()
        merged = bm_freq.merge(overlay, on="date", how="left")

        fig_gi = make_subplots(specs=[[{"secondary_y": True}]])

        fig_gi.add_trace(
            go.Bar(
                x=merged["date"],
                y=merged["bm_count"],
                name="BM Count",
                marker_color="steelblue",
                opacity=0.8,
            ),
            secondary_y=False,
        )

        water_rows = merged.dropna(subset=["water_oz"])
        if not water_rows.empty:
            fig_gi.add_trace(
                go.Scatter(
                    x=water_rows["date"],
                    y=water_rows["water_oz"],
                    name="Water (oz)",
                    mode="lines+markers",
                    line=dict(color="deepskyblue", dash="dot", width=2),
                ),
                secondary_y=True,
            )

        alcohol_rows = merged.dropna(subset=["alcohol_count"])
        if not alcohol_rows.empty:
            fig_gi.add_trace(
                go.Scatter(
                    x=alcohol_rows["date"],
                    y=alcohol_rows["alcohol_count"],
                    name="Alcohol (count)",
                    mode="lines+markers",
                    line=dict(color="orange", width=2),
                ),
                secondary_y=True,
            )

        fig_gi.update_layout(
            title="BM Frequency, Water & Alcohol",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig_gi.update_yaxes(title_text="BM Count", secondary_y=False, rangemode="tozero")
        fig_gi.update_yaxes(
            title_text="Water (oz) / Alcohol (count)", secondary_y=True, rangemode="tozero"
        )
        st.plotly_chart(fig_gi, use_container_width=True)

        # Raw event table (collapsed)
        with st.expander("Raw GI events"):
            st.dataframe(
                _gi2.rename(
                    columns={
                        "date": "Date",
                        "time": "Time",
                        "bristol": "Bristol",
                        "urgency": "Urgency",
                    }
                ),
                use_container_width=True,
            )

# ── TAB 3 — Mood & Focus ─────────────────────────────────────────────────────

with tab3:
    st.header("Mood & Focus")

    _dr3 = st.date_input(
        "Date range",
        value=(_min_date, _max_date),
        min_value=_min_date,
        max_value=_max_date,
        key="mood_date_range",
    )

    mf_df = entries_df[["date", "mood", "focus"]].copy()
    _gi3 = gi_events_df.copy()
    if len(_dr3) == 2:
        _s3, _e3 = _dr3
        mf_df = mf_df[(mf_df["date"].dt.date >= _s3) & (mf_df["date"].dt.date <= _e3)]
        _gi3 = _gi3[(_gi3["date"].dt.date >= _s3) & (_gi3["date"].dt.date <= _e3)]

    if mf_df[["mood", "focus"]].isna().all().all():
        st.info("No mood or focus data found yet.")
    else:
        # Average daily Bristol score as a GI-comfort proxy
        if not _gi3.empty:
            avg_bristol = (
                _gi3.groupby("date")["bristol"]
                .mean()
                .reset_index(name="avg_bristol")
            )
            mf_df = mf_df.merge(avg_bristol, on="date", how="left")
        else:
            mf_df["avg_bristol"] = pd.NA

        fig_mf = make_subplots(specs=[[{"secondary_y": True}]])

        mood_rows = mf_df.dropna(subset=["mood"])
        if not mood_rows.empty:
            fig_mf.add_trace(
                go.Scatter(
                    x=mood_rows["date"],
                    y=mood_rows["mood"],
                    name="Mood",
                    mode="lines+markers",
                    line=dict(color="mediumpurple", width=2),
                ),
                secondary_y=False,
            )

        focus_rows = mf_df.dropna(subset=["focus"])
        if not focus_rows.empty:
            fig_mf.add_trace(
                go.Scatter(
                    x=focus_rows["date"],
                    y=focus_rows["focus"],
                    name="Focus",
                    mode="lines+markers",
                    line=dict(color="cornflowerblue", width=2),
                ),
                secondary_y=False,
            )

        bristol_rows = mf_df.dropna(subset=["avg_bristol"])
        if not bristol_rows.empty:
            fig_mf.add_trace(
                go.Scatter(
                    x=bristol_rows["date"],
                    y=bristol_rows["avg_bristol"],
                    name="Avg Bristol (GI comfort)",
                    mode="lines+markers",
                    line=dict(color="tomato", dash="dot", width=2),
                ),
                secondary_y=True,
            )

        fig_mf.update_layout(
            title="Mood & Focus with GI Comfort",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig_mf.update_yaxes(
            title_text="Score (1–5)",
            range=[0.5, 5.5],
            dtick=1,
            secondary_y=False,
        )
        fig_mf.update_yaxes(
            title_text="Avg Bristol Score (1–7)",
            range=[0.5, 7.5],
            secondary_y=True,
        )
        st.plotly_chart(fig_mf, use_container_width=True)

        # Correlation note
        if not bristol_rows.empty and not mood_rows.empty:
            merged_corr = mf_df.dropna(subset=["mood", "avg_bristol"])
            if len(merged_corr) >= 3:
                corr = merged_corr["mood"].corr(merged_corr["avg_bristol"])
                st.caption(
                    f"Pearson correlation (mood vs avg Bristol): **{corr:.2f}** "
                    f"(based on {len(merged_corr)} days with both values)"
                )

# ── TAB 4 — Exercise ─────────────────────────────────────────────────────────

with tab4:
    st.header("Exercise & Activity")

    _dr4 = st.date_input(
        "Date range",
        value=(_min_date, _max_date),
        min_value=_min_date,
        max_value=_max_date,
        key="exercise_date_range",
    )

    if exercise_df.empty:
        st.info("No exercise data found.")
    else:
        _ex4 = exercise_df.copy()
        _ent4 = entries_df.copy()
        if len(_dr4) == 2:
            _s4, _e4 = _dr4
            _ex4 = _ex4[(_ex4["date"].dt.date >= _s4) & (_ex4["date"].dt.date <= _e4)]
            _ent4 = _ent4[(_ent4["date"].dt.date >= _s4) & (_ent4["date"].dt.date <= _e4)]

        # ── Exercise × Mood correlation ───────────────────────────────────────
        daily_ex = (
            _ex4[_ex4["duration_min"].notna()]
            .groupby("date")["duration_min"]
            .sum()
            .reset_index(name="exercise_min")
        )
        daily_mood = _ent4[["date", "mood"]].dropna(subset=["mood"])
        ex_mood = (
            daily_ex.merge(daily_mood, on="date", how="outer")
            .sort_values("date")
            .reset_index(drop=True)
        )
        ex_mood["exercise_min"] = ex_mood["exercise_min"].fillna(0)

        if ex_mood["mood"].notna().sum() >= 5:
            # Dual-axis line chart
            fig_exmood = make_subplots(specs=[[{"secondary_y": True}]])
            fig_exmood.add_trace(
                go.Bar(
                    x=ex_mood["date"],
                    y=ex_mood["exercise_min"],
                    name="Exercise (min)",
                    marker_color="rgba(46,117,182,0.5)",
                ),
                secondary_y=False,
            )
            mood_line = ex_mood.dropna(subset=["mood"])
            fig_exmood.add_trace(
                go.Scatter(
                    x=mood_line["date"],
                    y=mood_line["mood"],
                    name="Mood",
                    mode="lines+markers",
                    line=dict(color="mediumpurple", width=2),
                    marker=dict(size=6),
                ),
                secondary_y=True,
            )
            fig_exmood.update_layout(
                title="Exercise Minutes vs Mood",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            fig_exmood.update_yaxes(title_text="Exercise (min)", rangemode="tozero", secondary_y=False)
            fig_exmood.update_yaxes(title_text="Mood (1–5)", range=[0.5, 5.5], dtick=1, secondary_y=True)
            st.plotly_chart(fig_exmood, use_container_width=True)

            # Cross-correlation at lags -3 to +3
            ex_vals = ex_mood["exercise_min"].values
            mood_vals = ex_mood["mood"].values
            lags = list(range(-3, 4))
            corrs = []
            for lag in lags:
                if lag >= 0:
                    a = ex_vals[:len(ex_vals) - lag] if lag > 0 else ex_vals
                    b = mood_vals[lag:] if lag > 0 else mood_vals
                else:
                    a = ex_vals[-lag:]
                    b = mood_vals[:len(mood_vals) + lag]
                mask = ~(np.isnan(a) | np.isnan(b))
                if mask.sum() >= 5:
                    corrs.append(float(np.corrcoef(a[mask], b[mask])[0, 1]))
                else:
                    corrs.append(0.0)

            best_lag = lags[int(np.argmax(np.abs(corrs)))]
            best_corr = corrs[lags.index(best_lag)]

            bar_colors = [
                "#2e75b6" if c >= 0 else "#e05c2a" for c in corrs
            ]
            fig_xcorr = go.Figure(go.Bar(
                x=[f"Lag {l:+d}d" for l in lags],
                y=corrs,
                marker_color=bar_colors,
                hovertemplate="Lag %{x}<br>Correlation: %{y:.2f}<extra></extra>",
            ))
            fig_xcorr.add_hline(y=0, line_color="white", line_width=1)
            fig_xcorr.update_layout(
                title="Cross-correlation: Exercise → Mood at Different Lags",
                yaxis=dict(title="Pearson r", range=[-1, 1]),
                xaxis_title="Lag (negative = mood leads exercise, positive = exercise leads mood)",
            )
            st.plotly_chart(fig_xcorr, use_container_width=True)

            # Plain-English interpretation
            if abs(best_corr) < 0.1:
                interp = "No meaningful correlation between exercise and mood in this dataset yet."
            elif best_lag == 0:
                interp = f"Strongest correlation on the **same day** (r = {best_corr:.2f}) — exercise and mood move together."
            elif best_lag > 0:
                interp = (
                    f"Exercise appears to be a **leading indicator** of mood — "
                    f"the strongest correlation (r = {best_corr:.2f}) is at +{best_lag} day(s), "
                    f"meaning exercise today predicts {'better' if best_corr > 0 else 'lower'} mood {best_lag} day(s) later."
                )
            else:
                interp = (
                    f"Mood appears to **precede** exercise — "
                    f"the strongest correlation (r = {best_corr:.2f}) is at {best_lag} day(s), "
                    f"suggesting {'higher' if best_corr > 0 else 'lower'} mood leads to more exercise {abs(best_lag)} day(s) later."
                )
            st.info(interp)

        st.divider()
        detailed = _ex4.copy()

        ACTIVITY_COLORS = {
            "Strength": "#2e75b6",
            "Run":      "#e05c2a",
            "Walk":     "#4caf50",
            "Movement": "#ab8fd0",
            "Cycling":  "#f9a825",
            "Yoga":     "#26a69a",
            "Swimming": "#00acc1",
            "Activity": "#bdbdbd",
        }

        # ── Chart 1: grouped bars — one narrow bar per session, grouped by date ─
        plot_df = detailed.copy()
        PLACEHOLDER_MIN = 15  # height for sessions with no logged duration
        plot_df["display_min"] = plot_df["duration_min"].fillna(PLACEHOLDER_MIN)
        plot_df["duration_label"] = plot_df["duration_min"].apply(
            lambda x: f"{int(x)} min" if pd.notna(x) else "duration not logged"
        )
        # Marker to dim bars with no real duration
        plot_df["has_duration"] = plot_df["duration_min"].notna()

        if not plot_df.empty:
            fig_act = go.Figure()

            for atype in sorted(plot_df["activity_type"].unique()):
                subset = plot_df[plot_df["activity_type"] == atype]
                color = ACTIVITY_COLORS.get(atype, "#888")

                # Timed sessions — full opacity
                timed_s = subset[subset["has_duration"]]
                if not timed_s.empty:
                    fig_act.add_trace(go.Bar(
                        x=timed_s["date"],
                        y=timed_s["display_min"],
                        name=atype,
                        marker_color=color,
                        opacity=1.0,
                        customdata=timed_s[["activity_raw", "duration_label", "hr_avg", "effort", "distance_mi"]].values,
                        hovertemplate=(
                            "<b>%{customdata[0]}</b><br>"
                            "%{customdata[1]}<br>"
                            "HR avg: %{customdata[2]}<br>"
                            "Effort: %{customdata[3]}<br>"
                            "Distance: %{customdata[4]} mi"
                            "<extra></extra>"
                        ),
                        legendgroup=atype,
                        showlegend=True,
                    ))

                # Untimed sessions — dimmed, same color
                untimed_s = subset[~subset["has_duration"]]
                if not untimed_s.empty:
                    fig_act.add_trace(go.Bar(
                        x=untimed_s["date"],
                        y=untimed_s["display_min"],
                        name=atype,
                        marker_color=color,
                        opacity=0.35,
                        customdata=untimed_s[["activity_raw", "duration_label", "hr_avg", "effort", "distance_mi"]].values,
                        hovertemplate=(
                            "<b>%{customdata[0]}</b><br>"
                            "%{customdata[1]}<br>"
                            "HR avg: %{customdata[2]}<br>"
                            "Effort: %{customdata[3]}<br>"
                            "Distance: %{customdata[4]} mi"
                            "<extra></extra>"
                        ),
                        legendgroup=atype,
                        showlegend=False,  # avoid duplicate legend entries
                    ))

            fig_act.update_layout(
                title="Activity Sessions over Time (dimmed = duration not logged)",
                barmode="group",
                bargap=0.3,
                bargroupgap=0.05,
                hovermode="x unified",
                yaxis_title="Minutes",
                xaxis_title="Date",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_act, use_container_width=True)

        timed = detailed[detailed["duration_min"].notna()]

        # ── Chart 3: activity type breakdown (pie) ───────────────────────────
        col_pie, col_stats = st.columns([1, 1])

        with col_pie:
            type_totals = detailed.groupby("activity_type").size().reset_index(name="count")
            fig_pie = px.pie(
                type_totals,
                names="activity_type",
                values="count",
                title="Activity Mix (all time)",
                color="activity_type",
                color_discrete_map=ACTIVITY_COLORS,
            )
            fig_pie.update_traces(textposition="inside", textinfo="percent+label")
            fig_pie.update_layout(showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_stats:
            st.subheader("Summary")
            total_days = _ex4["date"].nunique()
            active_days = detailed["date"].nunique()
            total_min = timed["duration_min"].sum() if not timed.empty else 0
            st.metric("Days with activity", f"{active_days} / {total_days}")
            if not timed.empty:
                st.metric("Total logged minutes", f"{int(total_min)} min")
                st.metric("Avg minutes / timed day",
                          f"{total_min / timed['date'].nunique():.0f} min")
            st.dataframe(
                type_totals.rename(columns={"activity_type": "Type", "count": "Sessions"})
                           .sort_values("Sessions", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

# ── TAB 5 — Running ───────────────────────────────────────────────────────────

with tab5:
    st.header("Running")

    _dr5 = st.date_input(
        "Date range",
        value=(_min_date, _max_date),
        min_value=_min_date,
        max_value=_max_date,
        key="running_date_range",
    )

    runs = exercise_df[exercise_df["activity_type"] == "Run"].copy() if not exercise_df.empty else pd.DataFrame()
    if not runs.empty and len(_dr5) == 2:
        _s5, _e5 = _dr5
        runs = runs[(runs["date"].dt.date >= _s5) & (runs["date"].dt.date <= _e5)]

    if runs.empty:
        st.info("No runs logged yet.")
    else:
        # Compute pace (min/mile) where both duration and distance are available
        has_pace = runs["duration_min"].notna() & runs["distance_mi"].notna() & (runs["distance_mi"] > 0)
        runs.loc[has_pace, "pace_min_mi"] = runs.loc[has_pace, "duration_min"] / runs.loc[has_pace, "distance_mi"]

        def fmt_pace(p):
            if pd.isna(p):
                return "—"
            mins = int(p)
            secs = int(round((p - mins) * 60))
            return f"{mins}:{secs:02d} /mi"

        # ── summary metrics ───────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total runs", len(runs))
        total_dist = runs["distance_mi"].sum()
        c2.metric("Total distance", f"{total_dist:.1f} mi" if total_dist > 0 else "—")
        avg_pace = runs["pace_min_mi"].mean() if "pace_min_mi" in runs and runs["pace_min_mi"].notna().any() else None
        c3.metric("Avg pace", fmt_pace(avg_pace))
        avg_hr = runs["hr_avg"].mean()
        c4.metric("Avg HR", f"{avg_hr:.0f} bpm" if pd.notna(avg_hr) else "—")

        st.divider()

        RUN_COLOR = "#e05c2a"

        # ── distance over time ────────────────────────────────────────────────
        dist_runs = runs.dropna(subset=["distance_mi"])
        if not dist_runs.empty:
            fig_dist = px.bar(
                dist_runs, x="date", y="distance_mi",
                title="Distance per Run",
                labels={"distance_mi": "Miles", "date": "Date"},
                color_discrete_sequence=[RUN_COLOR],
            )
            fig_dist.update_traces(marker_color=RUN_COLOR, width=1000 * 3600 * 24 * 0.6)
            fig_dist.update_layout(hovermode="x unified", showlegend=False)
            st.plotly_chart(fig_dist, use_container_width=True)

        # ── pace over time ────────────────────────────────────────────────────
        if "pace_min_mi" in runs.columns:
            pace_runs = runs.dropna(subset=["pace_min_mi"])
            if not pace_runs.empty:
                pace_runs = pace_runs.copy()
                pace_runs["pace_label"] = pace_runs["pace_min_mi"].apply(fmt_pace)
                fig_pace = go.Figure()
                fig_pace.add_trace(go.Scatter(
                    x=pace_runs["date"],
                    y=pace_runs["pace_min_mi"],
                    mode="lines+markers",
                    line=dict(color=RUN_COLOR, width=2),
                    marker=dict(size=8),
                    customdata=pace_runs["pace_label"].values,
                    hovertemplate="Pace: %{customdata}<extra></extra>",
                    name="Pace",
                ))
                # Invert y-axis — lower pace (faster) should appear higher
                fig_pace.update_yaxes(
                    autorange="reversed",
                    tickvals=list(range(6, 14)),
                    ticktext=[fmt_pace(v) for v in range(6, 14)],
                    title="Pace (min/mi)",
                )
                fig_pace.update_layout(title="Pace over Time (lower = faster)",
                                       hovermode="x unified", showlegend=False)
                st.plotly_chart(fig_pace, use_container_width=True)

        # ── HR and cadence side by side ───────────────────────────────────────
        col_hr, col_cad = st.columns(2)

        with col_hr:
            hr_runs = runs.dropna(subset=["hr_avg"])
            if not hr_runs.empty:
                fig_hr = px.scatter(
                    hr_runs, x="date", y="hr_avg",
                    title="Avg HR per Run",
                    labels={"hr_avg": "bpm", "date": "Date"},
                    trendline="lowess",
                    color_discrete_sequence=[RUN_COLOR],
                )
                fig_hr.update_traces(marker_size=9)
                fig_hr.update_layout(showlegend=False)
                st.plotly_chart(fig_hr, use_container_width=True)

        with col_cad:
            cad_runs = runs.dropna(subset=["cadence_spm"]) if "cadence_spm" in runs.columns else pd.DataFrame()
            if not cad_runs.empty:
                fig_cad = px.scatter(
                    cad_runs, x="date", y="cadence_spm",
                    title="Avg Cadence per Run",
                    labels={"cadence_spm": "spm", "date": "Date"},
                    trendline="lowess",
                    color_discrete_sequence=["#f9a825"],
                )
                fig_cad.update_traces(marker_size=9)
                fig_cad.update_layout(showlegend=False)
                st.plotly_chart(fig_cad, use_container_width=True)

# ── TAB 6 — Correlations ──────────────────────────────────────────────────────

with tab6:
    st.header("GI × Sleep Correlations")

    _dr6 = st.date_input(
        "Date range",
        value=(_min_date, _max_date),
        min_value=_min_date,
        max_value=_max_date,
        key="corr_date_range",
    )

    lag = st.slider(
        "Lag (days): GI on day X vs. sleep on night X + lag",
        min_value=-2,
        max_value=2,
        value=0,
        step=1,
        help="Negative = sleep leads GI (sleep night X affects GI day X+|lag|); 0 = same night; Positive = GI leads sleep (GI day X affects sleep night X+lag).",
    )

    # ── build daily GI summary ────────────────────────────────────────────────
    if gi_events_df.empty:
        st.info("No GI data to correlate.")
    else:
        _gi6 = gi_events_df.copy()
        _ent6 = entries_df.copy()
        if len(_dr6) == 2:
            _s6, _e6 = _dr6
            _gi6 = _gi6[(_gi6["date"].dt.date >= _s6) & (_gi6["date"].dt.date <= _e6)]
            _ent6 = _ent6[(_ent6["date"].dt.date >= _s6) & (_ent6["date"].dt.date <= _e6)]

        daily_gi = (
            _gi6.groupby("date")
            .agg(bm_count=("bristol", "count"), avg_bristol=("bristol", "mean"))
            .reset_index()
        )
        hydration = _ent6[["date", "water_oz", "alcohol_count"]].copy()
        daily_gi = daily_gi.merge(hydration, on="date", how="left")

        # ── build daily sleep summary ─────────────────────────────────────────
        sleep_cols = ["date", "sleep_duration", "deep_min", "rem_min", "core_min", "awake_min", "hrv"]
        daily_sleep = _ent6[sleep_cols].copy()

        # Apply lag: shift sleep dates so GI day X aligns with sleep night X+lag
        if lag != 0:
            daily_sleep = daily_sleep.copy()
            daily_sleep["date"] = daily_sleep["date"] - pd.Timedelta(days=lag)

        merged = daily_gi.merge(daily_sleep, on="date", how="inner")

        GI_METRICS = {
            "bm_count":      "BM Count",
            "avg_bristol":   "Avg Bristol",
            "water_oz":      "Water (oz)",
            "alcohol_count": "Alcohol (count)",
        }
        SLEEP_METRICS = {
            "sleep_duration": "Sleep Duration (h)",
            "deep_min":       "Deep (min)",
            "rem_min":        "REM (min)",
            "core_min":       "Core (min)",
            "awake_min":      "Awake (min)",
            "hrv":            "HRV (ms)",
        }

        MIN_N = 5  # minimum overlapping points to show a correlation

        # Build correlation matrix and N matrix
        gi_keys = list(GI_METRICS.keys())
        sleep_keys = list(SLEEP_METRICS.keys())
        corr_matrix = []
        n_matrix = []
        annot_matrix = []

        for gk in gi_keys:
            row_corr, row_n, row_annot = [], [], []
            for sk in sleep_keys:
                pair = merged[[gk, sk]].dropna()
                n = len(pair)
                if n >= MIN_N:
                    r = float(pair[gk].corr(pair[sk]))
                    row_corr.append(r)
                    row_n.append(n)
                    row_annot.append(f"{r:.2f}<br>(n={n})")
                else:
                    row_corr.append(None)
                    row_n.append(n)
                    row_annot.append(f"n={n}<br>(insufficient)")
            corr_matrix.append(row_corr)
            n_matrix.append(row_n)
            annot_matrix.append(row_annot)

        # Replace None with NaN for Plotly
        z_plot = [[v if v is not None else float("nan") for v in row] for row in corr_matrix]

        fig_heatmap = go.Figure(go.Heatmap(
            z=z_plot,
            x=[SLEEP_METRICS[k] for k in sleep_keys],
            y=[GI_METRICS[k] for k in gi_keys],
            colorscale=[
                [0.0,  "#d7191c"],
                [0.5,  "#f7f7f7"],
                [1.0,  "#2166ac"],
            ],
            zmin=-1,
            zmax=1,
            text=annot_matrix,
            texttemplate="%{text}",
            hovertemplate="GI: %{y}<br>Sleep: %{x}<br>r = %{z:.2f}<extra></extra>",
            colorbar=dict(title="Pearson r", tickvals=[-1, -0.5, 0, 0.5, 1]),
        ))

        lag_label = f"Lag {lag:+d}d — GI day X vs. sleep night X{lag:+d}" if lag != 0 else "Lag 0 — GI day X vs. sleep same night"
        fig_heatmap.update_layout(
            title=lag_label,
            xaxis=dict(side="bottom", tickangle=-30),
            yaxis=dict(autorange="reversed"),
            height=340,
        )
        st.plotly_chart(fig_heatmap, use_container_width=True)

        st.caption(
            f"Grey cells = fewer than {MIN_N} days with both metrics logged. "
            "Blue = positive correlation, red = negative."
        )
