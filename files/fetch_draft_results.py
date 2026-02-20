"""
fetch_draft_results.py — Scrape Fantrax Draft Results for All Seasons
=====================================================================
Calls the Fantrax getDraftResults GET endpoint for every season league ID
defined in config.yaml, resolves playerIds to names (via journeys.json cache
first, then getPlayerProfile API for unknowns), resolves teamIds to owner names
via getLeagueInfo, and writes docs/data/draft_results.json.

Usage:
    cd files/
    python fetch_draft_results.py
    python fetch_draft_results.py --config config.yaml --docs-dir ../docs

Output:
    docs/data/draft_results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.fantrax.com"
DRAFT_RESULTS_URL = BASE_URL + "/fxea/general/getDraftResults"
LEAGUE_INFO_URL   = BASE_URL + "/fxea/general/getLeagueInfo"
PLAYER_PROFILE_URL = BASE_URL + "/fxpa/req"

API_VERSION = "182.0.1"
MAIN_LEAGUE_ID = "f0ksi2jtmi4yj35i"  # 2026 — used for getPlayerProfile resolution

# Ground-truth owner history keyed by real_name → {year: team_name}
# Mirrors OWNER_HISTORY in build_dashboard.py
OWNER_HISTORY = {
    "Matthew Zujewski": {
        2026: "Top Gunnar", 2025: "Quentin Pasquantino",
        2024: "My Team is Better Than Reed's", 2023: "The Juice is Loose",
        2022: "Purple Hayes", 2021: "Jung Gunnars",
        2020: "The Juice is Loose", 2019: "My Team is Better Than Reed's",
    },
    "Liam Burns": {
        2026: "Boot & Raleigh", 2025: "Boot & Raleigh",
        2024: "Everybody Loves Ramon", 2023: "Soto's Johto League Champions",
        2022: "Sohto League Champions", 2021: "Sohto League Champions",
        2020: "Soto's Johto League Champions", 2019: "Everybody Loves Ramon",
    },
    "Jason Bartolini": {
        2026: "Gho-Strider", 2025: "Gho-Strider",
        2024: "Waiting for Cespedes", 2023: "Waiting for Cespedes",
        2022: "The Riley Reid's", 2021: "The J-Rod Squad",
        2020: "The Riley Reid's", 2019: "Waiting for Cespedes",
    },
    "Jordan Papula": {
        2026: "Mojo Dojo Casas House", 2025: "Mojo Dojo Casas House",
        2024: "Bay of Puigs", 2023: "Bay of Puigs",
        2022: "The Phamtom Menace", 2021: "Attack of the Crons",
        2020: "The Phamtom Menace", 2019: "Bay of Puigs",
    },
    "Trent Radding": {
        2026: "Partially Torked", 2025: "A Few Jung Men",
        2024: "A Few Jung Men", 2023: "Championship or Bust (2021)",
        2022: "Fully Torked", 2021: "Turner Burners",
        2020: "Championship or Bust (2021)", 2019: "Team CarmenCiardiello",
    },
    "Jose Garcia-Chope": {
        2026: "Rates & Carrolls", 2025: "Rates & Carrolls",
        2024: "Shark(are)nado", 2023: "Shark(are)nado",
        2022: "Shark(are)nado", 2021: "The KamikOzzie's",
        2020: "Shark(are)nado", 2019: "Shark(are)nado",
    },
    "Reed Heim": {
        2026: "Reed's Trading Post", 2025: "Heimlich Maneuver",
        2024: "Lil' Tikes", 2023: "Lil' Tikes",
        2022: "If You Give a Mouse a Mookie", 2021: "Heimlich Maneuver",
        2020: "If You Give a Mouse a Mookie", 2019: "Lil' Tikes",
    },
    "Owen Hern": {
        2026: "The Juan-Binary Murderers' Row", 2025: "The New Murderers' Row",
        2024: "DJ LeMachine", 2023: "DJ LeMachine",
        2022: "DJ LeMachine", 2021: "DJ LeMachine",
        2020: "DJ LeMachine", 2019: "DJ LeMachine",
    },
    "Evan Soraci": {
        2026: "The Roman Empire", 2025: "The Kirby Superstars",
        2024: "The 430 Million Dollar Man", 2023: "The Wuhan BatEaters",
        2022: "Power Troutage", 2021: "The Kirby Superstars",
        2020: "The Wuhan BatEaters", 2019: "The 430 Million Dollar Man",
    },
    "Alex Beim": {
        2026: "The Undisputed ERA", 2025: "Hold Me Closer, Ohtani Dancer",
        2024: "Acuña Matata", 2023: "The Cole Train",
        2022: "The Manbolorians", 2021: "Hold Me Closer, Ohtani Dancer",
        2020: "The Cole Train", 2019: "Acuña Matata",
    },
    "Jack Dunne": {
        2026: "Wallace & deGromit", 2025: "The Wire Nation",
        2024: "Richmond Mazers", 2023: "Richmond Mazers",
        2022: "Petey Blinders", 2021: "Booze Cruz",
        2020: "Richmond Mazers", 2019: "Richmond Mazers",
    },
    "David Turley": {
        2026: "Yoshi's Riland", 2025: "Yoshi's Riland",
        2024: "Seage(r) Miller Band", 2023: "Lux Luthors",
        2022: "Ranger Things", 2021: "Ward Of The Rings",
        2020: "Kershawshank Redemption",  # 2020 team name (appeared in 2021 draft)
        2019: "Seage(r) Miller Band",
    },
}

# Build reverse lookup: team_name_lower → real_name (year-agnostic)
# Fantrax getLeagueInfo may return current-season team names for historical leagues,
# so we match by name only — team names are unique per owner across the league's history.
TEAM_TO_OWNER: Dict[str, str] = {}
for owner_name, seasons in OWNER_HISTORY.items():
    for yr, team in seasons.items():
        TEAM_TO_OWNER[team.lower().strip()] = owner_name

# Manual aliases for team name variants that appear in Fantrax draft data
# (Fantrax may show different capitalization or alternate names from draft-era league snapshots)
TEAM_TO_OWNER.update({
    "the petey blinders": "Jack Dunne",        # variant of "Petey Blinders"
    "kershawshank redemption": "David Turley", # 2020 name; appears in 2021 draft data
})


def normalize_team_name(name: str) -> str:
    """Fix double-encoded UTF-8 from Fantrax API and normalize apostrophes."""
    try:
        # API sometimes returns latin-1 bytes decoded as unicode — re-encode and fix
        fixed = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        fixed = name
    # Normalize smart quotes/apostrophes to ASCII
    fixed = fixed.replace("\u2019", "'").replace("\u2018", "'")
    return fixed.strip()


# ---------------------------------------------------------------------------
# Fantrax session helpers
# ---------------------------------------------------------------------------

def make_session(jsessionid: str, fx_rm: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set("JSESSIONID", jsessionid, domain="www.fantrax.com")
    if fx_rm:
        s.cookies.set("FX_RM", fx_rm, domain="www.fantrax.com")
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "X-Fantrax-Api": API_VERSION,
    })
    return s


def get_draft_picks(session: requests.Session, league_id: str, delay: float) -> Optional[Dict]:
    """GET /fxea/general/getDraftResults — returns full raw response dict."""
    url = f"{DRAFT_RESULTS_URL}?leagueId={league_id}"
    try:
        resp = session.get(url, timeout=20)
        time.sleep(delay)
        if resp.status_code != 200:
            print(f"    [WARN] getDraftResults HTTP {resp.status_code} for league {league_id}")
            return None
        return resp.json()
    except Exception as e:
        print(f"    [ERR] getDraftResults failed for {league_id}: {e}")
        return None


def get_team_info(session: requests.Session, league_id: str, delay: float) -> Dict[str, str]:
    """GET /fxea/general/getLeagueInfo — returns {teamId: team_name}."""
    url = f"{LEAGUE_INFO_URL}?leagueId={league_id}"
    try:
        resp = session.get(url, timeout=20)
        time.sleep(delay)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        team_info = data.get("teamInfo", {})
        # teamInfo is {teamId: {name: str, ...}} or {teamId: str}
        result = {}
        for tid, val in team_info.items():
            if isinstance(val, dict):
                raw_name = val.get("name", val.get("teamName", ""))
            else:
                raw_name = str(val)
            result[tid] = normalize_team_name(raw_name)
        return result
    except Exception as e:
        print(f"    [ERR] getLeagueInfo failed for {league_id}: {e}")
        return {}


def resolve_player_name_api(session: requests.Session, player_id: str, delay: float) -> Optional[str]:
    """POST getPlayerProfile via fxpa/req — returns display name or None."""
    payload = {
        "msgs": [{"method": "getPlayerProfile", "data": {
            "playerId": player_id,
            "leagueId": MAIN_LEAGUE_ID,
        }}],
        "refUrl": f"https://www.fantrax.com/fantasy/league/{MAIN_LEAGUE_ID}/players",
        "version": API_VERSION,
        "returnEnvelope": True,
    }
    try:
        resp = session.post(
            PLAYER_PROFILE_URL,
            json=payload,
            headers={"Content-Type": "application/json",
                     "Referer": f"https://www.fantrax.com/fantasy/league/{MAIN_LEAGUE_ID}/players"},
            timeout=15,
        )
        time.sleep(delay)
        data = resp.json()
        responses = data.get("responses", [])
        if not responses:
            return None
        misc = responses[0].get("data", {}).get("miscData", {})
        return misc.get("name") or None
    except Exception as e:
        print(f"    [ERR] getPlayerProfile failed for {player_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Load journeys.json player name cache
# ---------------------------------------------------------------------------

def load_player_cache(docs_dir: Path) -> Dict[str, str]:
    """Return {player_id: player_name} from journeys.json player_index."""
    jpath = docs_dir / "data" / "journeys.json"
    if not jpath.exists():
        print("  [WARN] journeys.json not found — will resolve all names via API")
        return {}
    with open(jpath) as f:
        data = json.load(f)
    cache = {}
    for pid, info in data.get("player_index", {}).items():
        name = info.get("player_name", "")
        if name:
            cache[pid] = name
    print(f"  Loaded {len(cache)} player names from journeys.json cache")
    return cache


# ---------------------------------------------------------------------------
# Core scraping logic
# ---------------------------------------------------------------------------

def scrape_season(
    session: requests.Session,
    year: int,
    league_id: str,
    player_cache: Dict[str, str],
    delay: float,
) -> Optional[Dict]:
    """Scrape draft results for one season. Returns structured season dict."""
    print(f"  Season {year} (league: {league_id})")

    # 1. Fetch raw draft results
    raw = get_draft_picks(session, league_id, delay)
    if raw is None:
        return None

    picks_raw = raw.get("draftPicks", [])
    if not picks_raw:
        print(f"    [SKIP] No picks returned for {year}")
        return None

    draft_date = raw.get("draftDate", "")
    draft_type  = raw.get("draftType", "")
    num_rounds  = max((p.get("round", 0) for p in picks_raw), default=0)

    print(f"    {len(picks_raw)} picks, {num_rounds} rounds, date={draft_date[:10] if draft_date else '?'}")

    # 2. Fetch team → name mapping for this season
    team_name_map = get_team_info(session, league_id, delay)
    print(f"    Resolved {len(team_name_map)} teams via getLeagueInfo")

    # 3. Collect all unknown playerIds
    unknown_pids = [
        p["playerId"] for p in picks_raw
        if p.get("playerId") and p["playerId"] not in player_cache
    ]
    if unknown_pids:
        print(f"    Resolving {len(unknown_pids)} unknown player names via API...")
        for pid in unknown_pids:
            name = resolve_player_name_api(session, pid, delay)
            if name:
                player_cache[pid] = name
                print(f"      {pid} → {name}")
            else:
                player_cache[pid] = f"Unknown ({pid})"
                print(f"      {pid} → [unresolved]")

    # 4. Build structured picks list
    picks_out: List[Dict] = []
    for p in picks_raw:
        team_id    = p.get("teamId", "")
        player_id  = p.get("playerId", "")
        team_name  = team_name_map.get(team_id, "")
        player_name = player_cache.get(player_id, f"Unknown ({player_id})")

        # Resolve owner real name by team name (year-agnostic — Fantrax may
        # return current-season team names for historical league IDs)
        owner_name = TEAM_TO_OWNER.get(team_name.lower().strip(), "")

        picks_out.append({
            "draft_year":    year,
            "round":         p.get("round", 0),
            "pick_in_round": p.get("pickInRound", p.get("pick", 0)),
            "overall_pick":  p.get("pick", 0),
            "team_id":       team_id,
            "team_name":     team_name,
            "owner_name":    owner_name,
            "player_id":     player_id,
            "player_name":   player_name,
        })

    return {
        "year":       year,
        "league_id":  league_id,
        "draft_date": draft_date[:10] if draft_date else "",
        "draft_type": draft_type,
        "num_rounds": num_rounds,
        "num_picks":  len(picks_out),
        "picks":      picks_out,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch Fantrax draft results for all seasons")
    p.add_argument("--config",   default="config.yaml", help="Path to config.yaml")
    p.add_argument("--docs-dir", default="../docs",     help="Path to docs/ directory")
    p.add_argument("--delay",    type=float, default=None,
                   help="Seconds between API calls (overrides config)")
    p.add_argument("--seasons",  type=int, nargs="+",
                   help="Only scrape specific years, e.g. --seasons 2024 2025")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Load config
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        sys.exit(f"Config not found: {cfg_path}")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    jsessionid = cfg.get("jsessionid", "")
    fx_rm      = cfg.get("extra_cookies", {}).get("FX_RM", "")
    delay      = args.delay if args.delay is not None else float(cfg.get("request_delay", 0.4))
    league_ids: Dict[int, str] = {int(k): v for k, v in cfg.get("all_season_league_ids", {}).items()}

    if not jsessionid:
        sys.exit("No jsessionid in config.yaml — cannot authenticate")
    if not league_ids:
        sys.exit("No all_season_league_ids in config.yaml")

    docs_dir = Path(args.docs_dir).resolve()
    out_path = docs_dir / "data" / "draft_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Filter seasons if requested
    years_to_scrape = sorted(league_ids.keys())
    if args.seasons:
        years_to_scrape = [y for y in years_to_scrape if y in args.seasons]
    print(f"Scraping {len(years_to_scrape)} seasons: {years_to_scrape}")

    session = make_session(jsessionid, fx_rm)
    player_cache = load_player_cache(docs_dir)

    seasons_out: List[Dict] = []
    picks_by_player: Dict[str, Dict] = {}  # player_id → pick info (latest draft)

    for year in years_to_scrape:
        league_id = league_ids[year]
        result = scrape_season(session, year, league_id, player_cache, delay)
        if result:
            seasons_out.append(result)
            # Populate picks_by_player lookup (used by build_dashboard.py join)
            for pick in result["picks"]:
                pid = pick["player_id"]
                if pid and not pid.startswith("Unknown"):
                    picks_by_player[pid] = {
                        "draft_year":    pick["draft_year"],
                        "round":         pick["round"],
                        "pick_in_round": pick["pick_in_round"],
                        "overall_pick":  pick["overall_pick"],
                        "team_name":     pick["team_name"],
                        "owner_name":    pick["owner_name"],
                        "player_name":   pick["player_name"],
                        "player_id":     pid,
                    }

    # Summary stats
    total_picks = sum(s["num_picks"] for s in seasons_out)
    print(f"\nTotal picks across all seasons: {total_picks}")
    print(f"Unique players in picks_by_player index: {len(picks_by_player)}")

    output = {
        "generated_at": __import__("datetime").datetime.now().isoformat()[:19],
        "total_picks":  total_picks,
        "seasons":      seasons_out,
        "picks_by_player": picks_by_player,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {out_path}")
    print("Done. Next step: python build_dashboard.py  (to regenerate picks.json)")


if __name__ == "__main__":
    main()
