# Ducks on the Pond Dynasty — League Tracker

Full-stack dynasty baseball analytics suite for the **Ducks on the Pond Dynasty** (DOTP) league.
Scrapes Fantrax, builds JSON data, and serves an interactive web dashboard on GitHub Pages.

---

## Project Overview

```
files/
  fantrax_tracker_v4.py       Fantrax scraper — outputs 5 CSVs per run
  build_dashboard.py          CSV → JSON pipeline for the web dashboard
  trade_dashboard.py          Standalone matplotlib trade analysis (legacy)
  player_history_dashboard.py Standalone matplotlib player history (legacy)
  config.yaml                 Auth credentials + league IDs (.gitignore'd)
  requirements.txt            Python dependencies

docs/                         GitHub Pages root
  index.html                  Landing page — league overview & season history
  standings.html              Standings — all-time & per-season stats, year switcher
  trade.html                  Trade analysis (7 interactive charts + player inline view)
  player_history.html         Player history (6 interactive charts)
  team.html                   Team deep-dive — any owner's roster, trades & journey
  data/
    teams.json                Owner stats, season history (~12KB)
    trades.json               All trade events, pairs, assets_by_party (~270KB)
    journeys.json             Player ownership stints & tenure stats (~1.5MB)
    rosters.json              Current rosters (~360KB)
  js/
    nav.js                    Nav bar injection, dark mode, anti-FOUC
    charts.js                 Shared Chart.js defaults + helpers
    standings_charts.js       Standings page — all-time & per-season stats
    trade_charts.js           7 trade charts + owner compare + inline players
    player_charts.js          6 player history charts
    team_charts.js            Team view — roster table, trade timeline + inline players
    chatbot.js                Floating Claude chatbot (streaming)
  css/
    style.css                 CSS vars, components, dark mode, button system
```

**League stats:** 12 owners · 8 seasons (2019–2026) · 352 trade events · 564 unique players

---

## Quick Start

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

Edit `config.yaml`:

```yaml
league_id: f0ksi2jtmi4yj35i       # Current season (2026)
jsessionid: node0abc123xyz...     # Refresh from Chrome when it expires
extra_cookies:
  FX_RM: "_qpxz..."               # Longer-lived cookie (grab once from DevTools)

all_season_league_ids:
  2026: f0ksi2jtmi4yj35i
  2025: hzoys3dqm33njr46
  2024: 5sl7nj1nlnvzh38r
  2023: wqnspl0hlais8k4m
  2022: 6pi0c5kdkv3h5bwd
  2021: a3jf2c8bkho611s8
  2020: u18ctt3qk4988e7f
  2019: kk1gbg94jq2o309s

request_delay: 0.4
data_root: "fantrax_data"
```

### 3. Scrape data from Fantrax

```bash
# Current season only (fast, ~2 min with caching)
python fantrax_tracker_v4.py

# All 8 seasons (runs each sequentially, players fetched in parallel)
python fantrax_tracker_v4.py --all-seasons

# Specific seasons
python fantrax_tracker_v4.py --seasons 2024 2025

# Force re-fetch (ignore player cache)
python fantrax_tracker_v4.py --refresh --all-seasons --workers 10

# More parallel threads (default: 8)
python fantrax_tracker_v4.py --all-seasons --workers 10
```

### 4. Build the dashboard JSON

```bash
python build_dashboard.py
```

Reads CSVs from `fantrax_data/latest/output/` → writes 4 JSON files to `docs/data/`.

### 5. Preview locally

```bash
python -m http.server 8080 --directory docs
# Open http://localhost:8080
```

> **Must use HTTP** (not `file://`) — the dashboard uses `fetch()` to load JSON.

### 6. Deploy to GitHub Pages

```bash
git add docs/data/
git commit -m "Refresh data — $(date +'%b %d %Y')"
git push
```

Repo Settings → Pages → Branch: `main`, Folder: `/docs`

---

## Update Workflow (Day-to-Day)

```bash
# 1. Refresh JSESSIONID in config.yaml if you get auth errors
# 2. Scrape current season
python fantrax_tracker_v4.py
# 3. Rebuild JSON
python build_dashboard.py
# 4. Push to GitHub
git add docs/data/ && git commit -m "Data refresh" && git push
```

---

## Getting Your JSESSIONID

1. Open Chrome and log into [fantrax.com](https://www.fantrax.com)
2. Press **F12** → **Application** tab → **Cookies** → `fantrax.com`
3. Copy `JSESSIONID` → paste into `config.yaml`
4. Also grab `FX_RM` (lasts much longer, only needs occasional refresh)

⚠️ `JSESSIONID` expires roughly every 24 hours. If you see `"Session expired"` errors, grab a fresh one.

---

## Scraper CLI Reference

```
python fantrax_tracker_v4.py [OPTIONS]

Core options:
  --config FILE          Config file path (default: config.yaml)
  --league-id ID         Override league ID for current-season run
  --jsessionid COOKIE    Override JSESSIONID
  --data-root DIR        Output folder (default: fantrax_data)
  --delay SECONDS        Request delay between API calls (default: 0.4)
  --refresh              Re-fetch all cached player profiles
  --verbose, -v          Verbose logging

Multi-season options:
  --all-seasons          Run all seasons defined in config.yaml
  --seasons YEAR [...]   Run specific year(s), e.g. --seasons 2024 2025
  --workers N            Parallel threads for player fetching (default: 8)
```

---

## Output Files

```
fantrax_data/
├── latest -> run_20260219_120000/     # symlink to most recent run
├── cache/                             # Cached player profiles (speeds up re-runs)
│   └── player_abc123.json
└── run_20260219_120000/
    ├── input/config.json              # Config snapshot (no secrets)
    ├── output/
    │   ├── teams.csv                  # 12 teams with owners
    │   ├── current_rosters.csv        # All rostered players (current season)
    │   ├── transaction_history.csv    # Every transaction event
    │   ├── player_journeys.csv        # Ownership stints per player
    │   └── owner_team_mapping.csv     # All seasons × all owners × team names
    ├── logs/tracker_*.log
    └── raw_responses/                 # Raw API JSON (for debugging)
```

---

## Dashboard Features

### Standings (`standings.html`) — NEW
- Season switcher (All-Time or any single season 2021–2026)
- Sortable stats table: trades, unique players, median tenure, top trade partner
- Unique players bar chart (per season or all-time)
- Trade activity stacked bar (per season or grouped by year for all-time)
- Median tenure comparison chart
- Team name history grid — every owner × every season

### Trade Analysis (`trade.html`)
| Chart | Type | Interactivity |
|---|---|---|
| Trade Participation by Owner | Horizontal bar | Click bar → filter all charts |
| Trade Partner Matrix | D3 heatmap | Hover for counts; click cell → trade list modal |
| Trade Network | D3 force-directed | Drag nodes (stay pinned); hover edges |
| Activity Timeline | Line | Hover tooltips |
| Activity Heatmap | D3 year × month grid | Hover for counts |
| 2-Team vs 3-Team | Stacked bar | Per-season breakdown |
| Volume by Season/Owner | Grouped bar | Year-over-year comparison |
| **Trade Events List** | Table | Players received shown inline with post-trade tenure (days); ★ = still on roster |
| **Owner Compare** | Modal | Select any two owners → see every trade they've made |

### Player History (`player_history.html`)
| Chart | Notes |
|---|---|
| Most Traveled Players | Uses **distinct owners** (not team names) — renames don't inflate count |
| Owner Throughput | Unique players rostered per owner |
| Ownership Flow Network | D3 directed graph (nodes stay pinned on drag) |
| Acquisition Breakdown | TRADED / CLAIMED / DRAFTED stacked bar (KEPT excluded), filterable by owner |
| Roster Composition | Donut grid per team |
| Tenure Distribution | Histogram + median line; grouped bar by acquisition type (KEPT excluded) |

### Team View (`team.html`)
- Owner dropdown + `?owner=Name` deep link
- Identity card with season history ribbon (2021→2026)
- Sortable roster table: position, status badge, acquisition type, roster since date, times owned
- All Players Ever Rostered table: sortable, shows times owned / total days / last acquired
- Trade history timeline: players received shown inline (★ = still on roster); click for full details
- Per-season trade count + unique player count chart

### Chatbot
- Floating 💬 button on every page
- Powered by Claude (`claude-haiku-4-5`), streaming via direct browser fetch
- Your Anthropic API key stored in `localStorage` (never sent anywhere else)
- Context-aware system prompt built from league JSON data at page load

---

## Owner / Team Name Mapping

The 8-year history is hardcoded in `fantrax_tracker_v4.py` → `OWNERS` dict. This is the ground truth for resolving historical team names to real owners.

Example: `"Claimed by Jung Gunnars"` → Matthew Zujewski (2021 team name).

**Important:** When measuring player mobility, the dashboard counts **distinct owners** (by real name), not distinct team names. A player who stays with the same owner through a team rename counts as staying on one team.

---

## Troubleshooting

| Error | Fix |
|---|---|
| `Session expired` / `NOT_LOGGED_IN` | Grab fresh `JSESSIONID` from Chrome DevTools |
| `No teams returned` | Check you're logged into Fantrax; JSESSIONID must be current |
| Charts not loading | Run `python build_dashboard.py` to generate `docs/data/*.json` |
| Stale player data | Run with `--refresh` to bypass cache |
| Blank charts on `file://` | Use `python -m http.server 8080 --directory docs` instead |

---

## Key Implementation Notes

- **Unicode:** `transaction_history.csv` uses U+2019 smart quotes in team names. Always call `normalize_quotes()` before comparing across CSVs.
- **Trade deduplication:** 641 TRADED rows → 352 unique events after dedup on `(date, details)`.
- **API version:** Must use `182.0.1` (not `179.0.1`).
- **Player names:** Derived from `miscData.urlName` slug in `getPlayerProfile` — not directly available in roster endpoints.
- **Two trade detail formats:** `"X trades away Y"` (most) and `"X to Y"` (some multi-team trades).

---

Built for the Ducks on the Pond Dynasty League 🦆⚾
