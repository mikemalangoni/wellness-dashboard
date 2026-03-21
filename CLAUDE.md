# Wellness Dashboard — Claude Context

## What this is
A personal Streamlit dashboard that reads from a Google Doc ("Spine Log") via the Google Docs API and visualizes health/wellness data over time.

## Key files
- `google_auth.py` — OAuth 2.0 desktop flow; saves `token.json` on first run
- `spine_parser.py` — fetches and parses the Google Doc into structured DataFrames
- `app.py` — six-tab Streamlit dashboard
- `Dockerfile` + `entrypoint.sh` — production container; credentials injected at runtime from Fly secrets
- `fly.toml` — Fly.io deployment config
- `.github/workflows/fly-deploy.yml` — auto-deploys to Fly on push to `main`

## Google Doc
- Doc ID: `1HVFwRoAInOMjZ_FMwsrdMt7HKCXjsVpV_EEwdGOQxUo`
- OAuth scope: `https://www.googleapis.com/auth/documents.readonly`
- `credentials.json` and `token.json` are gitignored; stored as Fly secrets in production

## Spine Log entry format (v2, March 2026)
- Entries wrapped in `═══` separator lines above and below the header
- Header: `SPINE ENTRY | YYYY-MM-DD | Weekday | Timezone` (timezone absent on pre-March 8 entries → defaults to EST)
- Sections: `FOOD & BEVERAGE`, `GI`, `SLEEP  (prior night)`, `EXERCISE`, `MOOD & FOCUS`
- Sub-section dividers: `─────` lines (ignored by parser)
- Missing/not-logged fields → `None`, never `0`

## Parser notes
- Entry splitting: find SPINE ENTRY header lines, not separator lines (headers and content are in separate separator-bounded blocks)
- Sleep: `Bed: HH:MMpm → Wake: HH:MMam` on one line; stages on one line `Deep: X | Core: Y | REM: Z | Awake: W`
- Exercise: non-indented detail lines (HR avg, Cadence, Distance, Effort) treated as sub-details regardless of indentation; duration computed from time ranges if explicit minutes absent
- GI events: `HH:MM: Bristol N | urgency: low/moderate/high`
- Mood/Focus: `N/5` format

## Dashboard tabs
1. **Sleep Trends** — duration, Apple Watch stage breakdown, HRV
2. **GI Log** — Bristol scatter (symmetric color scale, 4=green, 1&7=red), BM frequency, water/alcohol overlay, mood/focus trendlines
3. **Mood & Focus** — mood/focus over time, avg Bristol overlay, Pearson correlation
4. **Exercise** — exercise/mood correlation chart, cross-correlation at lags -3 to +3, activity sessions, pie breakdown
5. **Running** — distance, pace (inverted axis, MM:SS format), HR, cadence with LOWESS trendlines
6. **Correlations** — configurable correlation heatmap across all metrics (mood, sleep, GI, HRV, water, alcohol, exercise); lag slider -7 to +7 days; plain-English tooltip explanations per pair

## Deployment
- Live at: https://wellness.malangoni.com
- Hosted on Fly.io, app: `wellness-malangoni`
- Cloudflare Access gates it with one-time PIN to owner's email
- Deploy manually: `eval "$(/opt/homebrew/bin/brew shellenv)" && fly deploy`
- Auto-deploy: push/merge to `main` triggers GitHub Actions

## Local development
- Run: `wellness` (shell alias → `cd ~/projects/wellness-dashboard && streamlit run app.py`)
- Branch workflow: feature branch → test locally → `fly deploy` to test in prod → merge to main

## Key conventions
- Parser is defensive — bad chunks are silently skipped, never crash
- Missing data = `None`/`NaN`, never `0`
- `spine_parser.py` not `parser.py` (avoids shadowing Python stdlib)
- Data cached in Streamlit for 5 minutes (`@st.cache_data(ttl=300)`)
