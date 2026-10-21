# Ducks on the Pond Dynasty — League Tracker

Dynasty baseball analytics suite for the **Ducks on the Pond Dynasty** (DOTP) league.
Scrapes Fantrax, builds JSON data, and serves an interactive web dashboard on GitHub Pages.

---

## Project Overview

```
files/
  fantrax_tracker_v4.py       Fantrax scraper — outputs 5 CSVs per run
  history_store.py            Persistent SQLite history, source provenance, player discovery
  collection_state.py         Scoped profile caches, validation, successful-run pointers
  tests/test_collection.py    Offline regression tests for collection and preservation
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

**Published February 2026 snapshot:** 12 owners · 8 configured seasons (2019–2026) · 352 observed trade events · 564 rostered players. These are not certified all-time coverage totals.

## October 2026: collection and historical storage upgrade

The collector now discovers players from saved season rosters, transaction records,
and draft results, including players absent from the current roster. A local SQLite
database preserves observations and their source CSV rows. Re-importing unchanged
snapshots is safe: it does not duplicate observations or alter the originals.

Initial recovery found **35 usable snapshots, 1,397 player IDs, and 8,034 distinct
transaction observations**. The latter are not verified league transaction totals:
324 same-player/date/action groups contain variants requiring reconciliation, and
155 known players have no transaction records in the saved sources. Legacy cache
scope is explicitly unverified. Raw source files remain unchanged.

Run commands in this README from `files/`, unless stated otherwise:

```bash
cd files
# Offline recovery and coverage report; no Fantrax access needed.
python history_store.py
# Read-only access check; does not change current data.
python fantrax_tracker_v4.py --check-auth
# Fresh current-season rosters AND profiles for the historical player inventory.
python fantrax_tracker_v4.py --refresh
```

The database is `fantrax_data/history.sqlite3`; the detailed offline import report
is `fantrax_data/history_report.json`. They remain local under the existing ignored
data directory. Back up the entire directory, including original snapshots, to
preserve source evidence. The import report describes the last explicit
`history_store.py` run; rerun it after collection to update the report.

Collection safeguards:
- Profiles are cached by **league ID, season, and player ID**, with source fetch
  timestamps and a default 24-hour lifetime. The old shared cache is never reused.
- `--refresh` bypasses caches; `--cache-max-age-hours 0` disables cache reuse.
- All workers share one request pace. Transient network errors, throttling, and
  selected server errors receive up to three attempts.
- Every requested profile must succeed; missing teams, malformed profiles,
  unrecognized transactions, duplicate roster players, and unexpectedly large
  roster decreases prevent publication. Inspect an intentional decrease before
  using `--allow-roster-shrink`.
- A new run does not replace `latest` until CSV export, validation, and history
  import succeed. Each season gets its own `latest_by_league` pointer. Historical
  refreshes cannot replace the highest configured season's current-roster pointer.
- A manifest records success, collection identity, profile fetch times, and cache
  use. A failed/interrupted run remains unapproved and cannot feed the dashboard.

The existing dashboard still reads one successful current-season collection.
The database is the foundation for later reconciliation and historical views; it
does **not** silently feed unverified legacy transaction unions into charts.
Trade-direction fixes, draft-pick reconciliation, continuous ownership logic,
statistical corrections, and scheduling remain separate milestones.

Run the offline checks from the repository root:

```bash
python -m unittest discover -s files/tests -v
```

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
jsessionid: ""                  # Optional if FX_RM works for your login
api_version: "187.3.6"           # Observed in Chrome, October 2026
extra_cookies:
  FX_RM: "_qpxz..."               # Copy from your logged-in Chrome session

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
cache_max_age_hours: 24
```

### 3. Scrape data from Fantrax

```bash
# Current season, including the historical player inventory (24-hour cache)
python fantrax_tracker_v4.py

# All 8 seasons (runs sequentially with shared profile pacing)
python fantrax_tracker_v4.py --all-seasons

# Specific seasons
python fantrax_tracker_v4.py --seasons 2024 2025

# Force re-fetch (ignore player cache)
python fantrax_tracker_v4.py --refresh --all-seasons

# Resume with fresh cached profiles after an interrupted run
python fantrax_tracker_v4.py --cache-max-age-hours 24
```

### 4. Build the dashboard JSON

```bash
python build_dashboard.py
```

Reads CSVs from `fantrax_data/latest/output/` → writes 5 JSON files to `docs/data/`.
Standings and draft results are separate collection steps; see the update workflow.

### 5. Preview locally

```bash
python -m http.server 8080 --directory ../docs
# Open http://localhost:8080
```

> **Must use HTTP** (not `file://`) — the dashboard uses `fetch()` to load JSON.

### 6. Deploy to GitHub Pages

```bash
git add ../docs/data/
git commit -m "Refresh data — $(date +'%b %d %Y')"
git push
```

Repo Settings → Pages → Branch: `main`, Folder: `/docs`

---

## Full refresh using league transaction logs (recommended)

The full refresh now downloads every page of executed, non-deleted claim/drop and
trade logs for all configured seasons. It checks page/group totals, saves original
responses, and includes pure draft-pick/budget trades. Current roster assignments
must agree with the reconstructed player history before publication. Player profiles
remain available as a secondary diagnostic collector.

Run from `files/`, using a new folder for each refresh:

```bash
python fetch_standings.py --out fantrax_data/refresh_NEW/data/standings.json
python fetch_draft_results.py --docs-dir fantrax_data/refresh_NEW
python refresh_league_logs.py --out fantrax_data/refresh_NEW/league_logs
python build_log_snapshot.py --refresh-root fantrax_data/refresh_NEW
python build_dashboard.py --docs-dir fantrax_data/refresh_NEW
```

Stop if any command fails. Validate the staged seven dashboard JSON files, then copy
only those JSON files to `docs/data/`. Raw responses and credentials stay local.
`build_log_snapshot.py` retains stable transaction IDs, explicit trade asset types,
actual draft timestamps, and the original source archive. It preserves original
snapshots and updates `fantrax_data/latest` only after validation.

The October 21, 2026 refresh covers 2019–2026: 12 teams, 569 rostered players,
1,928 historical players, 9,803 player transactions, 665 trades, 96 standings rows,
and 926 selections across 960 draft slots. There are 34 source slots without a
player selection and 12 historical stints with no recorded closing move. The current
roster overrides current-status inference for those stints; no exit date is invented.
All 407 traded-pick references are retained. Only 73 have explicit slot numbers that
confirm the selected player; 230 remain ambiguous, 47 unknown, and 57 future picks.
Stable player IDs distinguish players who share a name.

Bulk endpoint request fields were cross-checked against the
[go-fantrax client documentation](https://pkg.go.dev/github.com/pmurley/go-fantrax/auth_client)
and verified against the league's live responses. No recurring scheduler or Git
push is part of these commands.

## Update Workflow (Day-to-Day)

```bash
# Run from files/. Stop if a collection command fails.
python fantrax_tracker_v4.py --check-auth
python fantrax_tracker_v4.py --refresh
python history_store.py
# Standings and draft collectors are still legacy code: write to a staging folder
# and verify season coverage before replacing docs/data/standings.json or draft_results.json.
python fetch_standings.py --out fantrax_data/staging/standings.json
python fetch_draft_results.py --docs-dir fantrax_data/staging
# After reviewing/importing staged draft results, rebuild into a preview directory.
# Copy the reviewed draft_results.json into preview/data/ first for pick matching.
python build_dashboard.py --docs-dir fantrax_data/preview
```

The standings staging file is `staging/standings.json`; draft results are written
to `staging/data/draft_results.json`. Both helpers support FX_RM-only login and refuse
to replace output when requested seasons or owners are unresolved. Standings use
column labels, retain raw responses, and sum innings as outs. Review staged data
before publishing. Player profiles share a paced request queue; HTTP-200 slowdown
warnings trigger a 60-second cooldown and a slower pace. Successful profiles remain
cached so an interrupted collection can resume without fetching them again.
No scheduling or automatic Git pushes have been enabled.

---

## Getting Your Fantrax Login Cookie

1. Open Chrome and log into [fantrax.com](https://www.fantrax.com)
2. Press **F12** → **Application** tab → **Cookies** → `fantrax.com`
3. Copy `FX_RM` into `extra_cookies.FX_RM` in your local `config.yaml`.
4. Leave `jsessionid` empty if Chrome does not show it. If present and needed, copy it too.
5. Run `python fantrax_tracker_v4.py --check-auth` to verify league access.

The October 2026 login was verified with `FX_RM` alone. Cookies can expire; refresh them if access fails. Keep credentials out of Git and shared logs. The standings and draft helpers also support FX_RM-only login.

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
  --check-auth           Verify current league access without collecting data
  --cache-max-age-hours N  Reuse profiles younger than N hours (default: 24)
  --draft-results FILE   Draft JSON to seed historical player discovery
  --allow-roster-shrink  Accept an inspected roster decrease greater than 20%

Multi-season options:
  --all-seasons          Run all seasons defined in config.yaml
  --seasons YEAR [...]   Run specific year(s), e.g. --seasons 2024 2025
  --workers N            Parallel threads for player fetching (default: 8)
```

---

## Output Files

```
fantrax_data/
├── history.sqlite3                    # Historical observations + source provenance
├── history_report.json                # Last offline import/coverage report
├── latest -> run_<timestamp>_<id>/     # Last successful current-season run
├── latest_by_league/<league_id>        # Last successful run for each season's league
├── cache/<league_id>/<season>/         # Scoped cache with fetch timestamps
│   └── player_abc123.json
└── run_<timestamp>_<id>/
    ├── manifest.json                  # Collection status, identity, profile freshness
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

## Dashboard Features — October 2026 redesign

The dashboard remains a buildless static site in `docs/`, compatible with the existing GitHub Pages setup. The active pages use `docs/css/dashboard.css` and `docs/js/dashboard.js`; the older chart scripts remain in the repository but are no longer loaded by these pages.

| Page | Current experience |
|---|---|
| `index.html` | League overview, selected-team metrics, season standings, recent trades, roster acquisition breakdown, annual finishes |
| `team.html` | Team directory or `?owner=Name` clubhouse, searchable roster, performance comparison, trades, franchise history |
| `player_history.html` | All 1,928 historical players; search, team/status/position filters, sortable columns, pagination, quick view |
| `player.html?id=PLAYER_ID` | Dedicated profile, current owner, dated ownership timeline, related trades |
| `trade.html` | Records first; season/team/partner/type/search filters, detail dialog, monthly activity, owner participation |
| `standings.html` | Season standings and category-rank heatmap; lower ERA/WHIP rank better; ties share rank |
| `drafts.html` | Searchable draft selections, current ownership, traded-pick outcomes with uncertainty labels |
| `history.html` | Season leaders, cumulative points, and most-traveled players |

Shared navigation includes global player/team search, season context, a remembered selected team, responsive mobile navigation, keyboard focus states, native accessible dialogs, and URL-backed filters/sorting/pagination. Browser Back dismisses quick views without losing the previous search. The bottom-left team picker explicitly saves your preferred team and updates the overview; browsing another team does not overwrite that preference. The picker supports keyboard dismissal and mobile navigation. Roster status normalizes the source value `INJURED_RESERVE` to `IR` for display and filtering.

### Graphics

`docs/assets/dotp-crest.png` is the new transparent duck/baseball crest. `docs/assets/pond-ballpark.png` is the clubhouse illustration. The UI adds coordinated team monogram shields and a custom line-icon set. Generation prompts and asset provenance are in `docs/assets/BRAND.txt`. Fonts have system fallbacks if Google Fonts is unavailable.

### Data boundaries

- Season selection changes standings, trades, and historical team names. Current rosters remain explicitly labeled as the 2026 snapshot.
- Finishing-position charts represent annual snapshots, not daily standings.
- The trade exporter exposes player names and pick assets. Budget amounts remain visible in the complete source record rather than being guessed into recipient columns.
- Related player trades are labeled as name matches; ambiguous names are not automatically linked to an individual profile.
- Only explicit draft slots establish confirmed pick outcomes. Unresolved and future picks retain their status.
- The old browser-key chatbot is not loaded in the new interface. An integrated assistant, external player valuations/production feeds, and unattended refresh scheduling remain later work.

### Redesign verification

Validated desktop (1280 px) and phone (390 px) layouts, all eight main views, player search and empty states, the 98-player IR filter, reset, player quick views, Back navigation, team comparisons, owner/season trade filters, and asset loading. No browser errors or page-level horizontal overflow were observed in those checks. Wide tables scroll within their containers. All 569 current roster players and every selected draft player resolve to a player profile. JavaScript syntax and local HTML asset references were checked.

This redesign is a local working-tree change until the existing GitHub Pages deployment workflow is run.

---

## Owner / Team Name Mapping

The 8-year history is hardcoded in `fantrax_tracker_v4.py` → `OWNERS` dict. This is the ground truth for resolving historical team names to real owners.

Example: `"Claimed by Jung Gunnars"` → Matthew Zujewski (2021 team name).

**Important:** When measuring player mobility, the dashboard counts **distinct owners** (by real name), not distinct team names. A player who stays with the same owner through a team rename counts as staying on one team.

---

## Troubleshooting

| Error | Fix |
|---|---|
| `Session expired` / `NOT_LOGGED_IN` | Refresh `FX_RM` (or `JSESSIONID` if present) from Chrome DevTools |
| `No teams returned` | Check league ID and refresh your Fantrax login cookies |
| Charts not loading | Run `python build_dashboard.py` to generate `docs/data/*.json` |
| Stale player data | Run with `--refresh` to bypass cache |
| Blank charts on `file://` | Use `python -m http.server 8080 --directory docs` instead |

---

## Key Implementation Notes

- **Unicode:** `transaction_history.csv` uses U+2019 smart quotes in team names. Always call `normalize_quotes()` before comparing across CSVs.
- **Trade deduplication:** 641 TRADED rows → 352 unique events after dedup on `(date, details)`.
- **API version:** The tracker defaults to `187.3.6`, observed in Chrome in October 2026. Override `api_version` in local config when Fantrax changes it; all three collectors use this setting.
- **Player names:** Derived from `miscData.urlName` slug in `getPlayerProfile` — not directly available in roster endpoints.
- **Two trade detail formats:** `"X trades away Y"` (most) and `"X to Y"` (some multi-team trades).

---

Built for the Ducks on the Pond Dynasty League 🦆⚾

### Interactive league stories — October 21, 2026

The local dashboard now includes:

- **Standings:** a cumulative weekly race for 2025 (28 periods) and 2026 (27 periods), with owner comparison, rank/points switch, a week slider, movement summaries, and an accessible data table. Earlier seasons explicitly show that weekly history has not been collected. The full-season leaderboard remains separate from the selected week.
- **Category contrast:** a twelve-step green–cream–terracotta scale shared by the standings heatmap and team category bars. Numeric ranks and a legend accompany the colors; tied category results share a rank.
- **Trades:** incoming/outgoing player counts by partner, clickable partner routes and calendar months, filtered deal/asset totals, and a “Where are they now?” table in trade details. Three-way transfers count only explicit sender/recipient matches. Pick/budget-only deals may have zero players. Current ownership can reflect later reacquisitions; these views do not estimate trade profit or declare winners.
- **Draft room:** late-round selections still rostered, class survival rates, and A–D retention grades across all eight drafts. Survival is current league-rostered selections divided by actual selections (unfilled slots excluded). Within-class competition ranks 1–3 earn A, 4–6 B, 7–9 C, 10–12 D; tied rates share rank/grade, and no selections receive no grade. These are retention grades, not performance or dynasty-value grades. The inaugural 2019 draft differs from later supplemental drafts, and newer classes have had less time to develop. “Late-round” means rounds strictly after the midpoint, with the middle round of odd-length drafts excluded.
- **Player profiles:** a keyboard-operable acquisition scrubber and play/pause replay. Stops preserve recorded exits and gaps; consecutive stops do not imply direct trades. Playback stops on navigation, tab hiding, and manual scrubbing. Player explorer links feature the most-traveled players.
- **Overview:** direct entry points into the new stories; the saved team preference still drives the default owner.

The pure calculations live in `docs/js/league_insights.js`; shared views remain in `docs/js/dashboard.js` and `docs/css/dashboard.css`. This is a local, static GitHub Pages-compatible update; it does not publish or schedule anything.

Refresh weekly standings from the repository root, after refreshing season totals:

```bash
python3 files/fetch_weekly_standings.py --seasons 2025 2026
```

Use `--refresh` to replace cached historical weeks. The collector uses the existing ignored `files/config.yaml`, paces read-only Fantrax requests, caches raw responses under ignored `files/fantrax_data/weekly_standings/`, and exports only public-facing owner/rank/point records to `docs/data/weekly_standings.json`. Each season is published atomically only after the period/cumulative selection, full team coverage, variation across weeks, and final-week reconciliation pass. A final-week mismatch asks for a season standings refresh instead of publishing inconsistent data. Fantrax’s echoed displayed date range remains full-season even in period mode, so the chart uses the actual scoring-period label.

Validation:

```bash
python3 -m unittest discover -s files/tests -v
node files/tests/test_league_insights.cjs
node --check docs/js/dashboard.js
```

Next data work: player-season production and value at acquisition, followed by production-based draft grades and trade returns. Keep those separate from the current ownership/retention metrics.

### Final interaction pass — October 21, 2026

- Grade-table team names now expand the owner's actual selections inline. Each row under “Your draft classes” also expands its picks. The new two-team comparison shows the selected year's picks and retention results side by side. The bottom historical leaderboard sorts by average within-class survival rank, giving each rated year equal weight and excluding years without selections; tied averages share rank. Annual grade links open the filtered selections.
- Weekly standings now include all ten scoring categories from the already archived Fantrax responses. Both two-team and twelve-team chart modes are available, with controls below the plot. Cumulative rate stats retain Fantrax's source precision rather than averaging period rates. All 240 final-week category values reconcile to the two season exports. Missing category values remain missing and break chart lines.
- Player names lead directly to the full journey. Player tables also have explicit Journey links, Details popup buttons, and separate chevrons for inline history. Trade rows likewise separate Details popups from inline chevron disclosures.
- “Show all trades” clears team, partner, month, text, and type filters in one click. Selecting “All teams” clears an otherwise-hidden partner restriction. Yellow navigation accents, panel edges, category cards, and journey buttons provide more contrast.
- Rebuild category exports without any network calls using `python3 files/fetch_weekly_standings.py --seasons 2025 2026 --offline`.

**Trade production grading remains outstanding.** Fantrax's UI exposes MLB, Fantasy Team, and Full Fantasy Team statistics, plus dated live-scoring views. The collected exports do not yet contain a complete date-bounded, active-lineup production ledger for acquired and departed players. Neither total MLB production nor current-roster retention can substitute for that ledger. A valid next collector must preserve player ID, owner, scoring date/period, active lineup eligibility, the trade's effective acquisition date, and the exit date; handle reacquisitions and multi-team deals; reconcile counted totals to Fantrax; and retain rate denominators/innings outs. Only then can a documented production grade be assigned. No speculative production grades were added in this pass.

Verification for this pass: 34 Python tests plus JavaScript draft/trade/history checks; final-week category reconciliation; browser checks for both expand controls versus popups, draft picks/comparison, all-team category switching, and resetting filtered trades.

### Category point view and league-history chart

The weekly category chart now defaults to the actual category roto points in Fantrax's `Standings - Point Totals` table. A side toggle switches to raw counting/rate statistics. This preserves fractional tie awards (for example, 7.5 points), rather than treating a rank as a points award. All ten categories reconcile to the overall roto total for each of the 660 exported team/week records. Overall rank and total-point charts retain their existing scales, and the category-units toggle is disabled for those two views. The toggle stacks below the chart on narrow screens.

League History now plots all twelve owners across all eight seasons, with finishing-rank and roto-point modes, a clickable legend to highlight/clear a franchise, and a season-results table. Team-name changes are joined through the stable owner identity.

Trade grading investigation progressed to a verified read-only `getTeamRosterInfo` request. The public Fantrax roster client maps `statsType=2` to `FANTASY` and `statsType=3` to `FANTASY_FULL`; the response also exposes `seasonOrProjection`, `timeframeTypeCode`, `startDate`, `endDate`, and scoring-period selections. A current-roster `FANTASY` request for Miller Time in 2026 returned 228 HR and 1,286 K versus the recorded season totals of 249 HR and 1,349 K. It therefore fails full-season production reconciliation and cannot support complete trade grades yet. The raw probe and reference client bundles are kept under ignored `files/fantrax_data/`; they are not dashboard assets. Next work must cover historical/ departed players and each post-trade active-lineup window before assigning grades.

Validation: 35 Python tests, including fractional category awards and rejecting inconsistent point totals; existing JavaScript calculation checks; browser verification of default roto mode, raw switching, ERA labeling, all 96 owner/season plot points, history highlighting, and desktop/mobile layouts.

### Trade production recovery — October 21, 2026

The former current-roster gap is resolved by `getTeamRosterInfo` with `statsType=3` (**Full Fantasy Team**). It includes departed players. Miller Time reconciles exactly to 249 HR and 1,349 K, and to all seven counting categories. Eleven of twelve 2026 teams reconcile fully; Alex Beim's source records remain 39 K and 9 W+QS below the season standings. That discrepancy is retained in the export and visibly flagged with provisional grade asterisks. No player record is adjusted to force a team balance.

`files/fetch_trade_production.py` collects all 2026 trade receipts using unique player IDs matched to the recorded acquisition stint. Each source request is restricted to the receiving team and the dates from the day after acquisition through the day before departure (capped to the source season). Trade/exit days are conservatively omitted because the saved history has dates rather than precise lineup-effective timestamps. Later reacquisitions are separate windows. The collector validates the echoed team, stats mode and date selection, caches raw responses privately, and atomically exports `docs/data/trade_production_2026.json`. Missing players and values remain missing; actual source zeros are preserved. IP retains baseball notation. Per-player OBP, ERA and WHIP are shown as source rates, never averaged; zero-game rates display as unavailable.

Trade Explorer now displays received-production grades, highlights leading returns, and exposes each acquired player's counted dates and stats in Details. Grades measure **same-season received counting production**, not net trade profit or dynasty value. Each of R, HR, RBI, SB, K, SVH3 and W+QS is divided by that season's league-median team total; the seven shares are summed. A/B/C/D follow competition-percentile quartiles among fully covered receiving sides; ties share grades and zero production earns D. Picks, budget, outgoing cost, rate categories and future seasons are excluded. Sides with no received players or incomplete player/count coverage are not graded. Longer holding periods have more opportunity, and this is disclosed in the UI. Earlier seasons explicitly show “not collected.”

Refresh or rebuild:

```bash
python3 files/fetch_trade_production.py --season 2026 --refresh
python3 files/fetch_trade_production.py --season 2026 --offline
python3 -m unittest discover -s files/tests -q
```

Raw responses and credentials stay ignored. The new regression checks cover departed players, missing values versus zeros, wrong stats modes/teams/dates, acquisition/exit boundaries, season caps, tied grades, and the export's player records against the cached source responses. These updates remain local and are not deployed.

Collected result: 92 trade events, 148 received-player entries, 145 available player/window records and 123 graded receiving sides. Colton Cowser is absent from the applicable response; Gary Sanchez and Luis Perales have no full scoring day within their recorded ownership windows. All three remain unavailable, not zero. All 40 Python tests pass, as do the JavaScript calculation checks and syntax validation. Browser checks verified grades, Miller Time's player-detail dates/stats, season availability, clearing filters, and layouts at 390px and 1280px with no page overflow or console errors.
