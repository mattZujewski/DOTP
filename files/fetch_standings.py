"""
fetch_standings.py — Scrape Fantrax rotisserie standings for all seasons.
Writes docs/data/standings.json.

Usage:
    python fetch_standings.py
    python fetch_standings.py --out ../docs/data/standings.json
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml

# ---------------------------------------------------------------------------
# Owner/team lookup (mirrors fantrax_tracker_v4.py OWNERS dict)
# ---------------------------------------------------------------------------
OWNERS = {
    "MattZujewski": {
        "real_name": "Matthew Zujewski",
        "teams": {
            2026: "Top Gunnar", 2025: "Quentin Pasquantino",
            2024: "My Team is Better Than Reed's", 2023: "The Juice is Loose",
            2022: "Purple Hayes", 2021: "Jung Gunnars",
            2020: "The Juice is Loose", 2019: "My Team is Better Than Reed's",
        },
    },
    "lpburns": {
        "real_name": "Liam Burns",
        "teams": {
            2026: "Boot & Raleigh", 2025: "Boot & Raleigh",
            2024: "Everybody Loves Ramon", 2023: "Soto's Johto League Champions",
            2022: "Sohto League Champions", 2021: "Sohto League Champions",
            2020: "Soto's Johto League Champions", 2019: "Everybody Loves Ramon",
        },
    },
    "sfgiant": {
        "real_name": "Jason Bartolini",
        "teams": {
            2026: "Gho-Strider", 2025: "Gho-Strider",
            2024: "Waiting for Cespedes", 2023: "Waiting for Cespedes",
            2022: "The Riley Reid's", 2021: "The J-Rod Squad",
            2020: "The Riley Reid's", 2019: "Waiting for Cespedes",
        },
    },
    "Jpapula": {
        "real_name": "Jordan Papula",
        "teams": {
            2026: "Mojo Dojo Casas House", 2025: "Mojo Dojo Casas House",
            2024: "Bay of Puigs", 2023: "Bay of Puigs",
            2022: "The Phamtom Menace", 2021: "Attack of the Crons",
            2020: "The Phamtom Menace", 2019: "Bay of Puigs",
        },
    },
    "trentradding": {
        "real_name": "Trent Radding",
        "teams": {
            2026: "Partially Torked", 2025: "A Few Jung Men",
            2024: "A Few Jung Men", 2023: "Championship or Bust (2021)",
            2022: "Fully Torked", 2021: "Turner Burners",
            2020: "Fully Torked", 2019: "Team CarmenCiardiello",
        },
    },
    "Jgchope": {
        "real_name": "Jose Garcia-Chope",
        "teams": {
            2026: "Rates & Carrolls", 2025: "Rates & Carrolls",
            2024: "Shark(are)nado", 2023: "Shark(are)nado",
            2022: "Shark(are)nado", 2021: "The KamikOzzie's",
            2020: "Shark(are)nado", 2019: "Shark(are)nado",
        },
    },
    "rheim": {
        "real_name": "Reed Heim",
        "teams": {
            2026: "Reed's Trading Post", 2025: "Heimlich Maneuver",
            2024: "Lil' Tikes", 2023: "Lil' Tikes",
            2022: "If You Give a Mouse a Mookie", 2021: "Heimlich Maneuver",
            2020: "If You Give a Mouse a Mookie", 2019: "Lil' Tikes",
        },
    },
    "owenhern": {
        "real_name": "Owen Hern",
        "teams": {
            2026: "The Juan-Binary Murderers' Row", 2025: "The New Murderers' Row",
            2024: "DJ LeMachine", 2023: "DJ LeMachine",
            2022: "DJ LeMachine", 2021: "DJ LeMachine",
            2020: "DJ LeMachine", 2019: "DJ LeMachine",
        },
    },
    "esoraci": {
        "real_name": "Evan Soraci",
        "teams": {
            2026: "The Roman Empire", 2025: "The Kirby Superstars",
            2024: "The 430 Million Dollar Man", 2023: "The Wuhan BatEaters",
            2022: "Power Troutage", 2021: "The Kirby Superstars",
            2020: "The Wuhan BatEaters", 2019: "The 430 Million Dollar Man",
        },
    },
    "Beim": {
        "real_name": "Alex Beim",
        "teams": {
            2026: "The Undisputed ERA", 2025: "Hold Me Closer, Ohtani Dancer",
            2024: "Acuña Matata", 2023: "The Cole Train",
            2022: "The Manbolorians", 2021: "Hold Me Closer, Ohtani Dancer",
            2020: "The Cole Train", 2019: "Acuña Matata",
        },
    },
    "Jookuh": {
        "real_name": "Jack Dunne",
        "teams": {
            2026: "Wallace & deGromit", 2025: "The Wire Nation",
            2024: "Richmond Mazers", 2023: "Richmond Mazers",
            2022: "Petey Blinders", 2021: "Booze Cruz",
            2020: "Richmond Mazers", 2019: "Richmond Mazers",
        },
    },
    "dturls55": {
        "real_name": "David Turley",
        "teams": {
            2026: "Yoshi's Riland", 2025: "Yoshi's Riland",
            2024: "Seage(r) Miller Band", 2023: "Lux Luthors",
            2022: "Ranger Things", 2021: "Ward Of The Rings",
            # Also register legacy names Fantrax may surface for 2021 season
            2020: "Lux Luthors", 2019: "Seage(r) Miller Band",
        },
        # Extra aliases that Fantrax may return for historical seasons
        "aliases": ["Kershawshank Redemption"],
    },
}

# Build team-name → owner lookup (normalizing smart quotes)
def _norm(s: str) -> str:
    return s.replace("\u2019", "'").replace("\u2018", "'").replace("\u02bc", "'").lower().strip()

TEAM_TO_OWNER: Dict[str, Dict] = {}
for _uname, _odata in OWNERS.items():
    for _yr, _tname in _odata["teams"].items():
        _info = {"username": _uname, "real_name": _odata["real_name"], "season": _yr}
        TEAM_TO_OWNER[_tname] = _info
        TEAM_TO_OWNER[_norm(_tname)] = _info
    # Register any extra aliases (e.g. legacy team names Fantrax may surface)
    for _alias in _odata.get("aliases", []):
        _info = {"username": _uname, "real_name": _odata["real_name"], "season": 0}
        TEAM_TO_OWNER[_alias] = _info
        TEAM_TO_OWNER[_norm(_alias)] = _info

def owner_from_team(team_name: str) -> Dict:
    for candidate in (team_name, _norm(team_name)):
        if candidate in TEAM_TO_OWNER:
            return TEAM_TO_OWNER[candidate]
    # partial fallback
    nrm = _norm(team_name)
    for k, v in TEAM_TO_OWNER.items():
        if nrm in k or k in nrm:
            return v
    return {"username": "Unknown", "real_name": "Unknown", "season": 0}


INTERNAL_API_URL = "https://www.fantrax.com/fxpa/req"

# Columns in Table index 3 ("Standings - Stat Totals")
STAT_COLS = ["pts", "gp", "ab", "h", "r", "hr", "rbi", "sb", "obp",
             "ip", "k", "era", "whip", "svh3", "wqs"]


def parse_num(s: str) -> Any:
    """Parse a stat string like '2,229' or '2.99' or '-' to number."""
    if not s or s.strip() in ("-", ""):
        return None
    clean = s.replace(",", "").strip()
    try:
        v = float(clean)
        return int(v) if v == int(v) and "." not in clean else round(v, 4)
    except ValueError:
        return None


def fetch_season_standings(
    league_id: str,
    season: int,
    jsessionid: str,
    fx_rm: str = "",
    delay: float = 0.4,
) -> List[Dict]:
    """Fetch standings for a single season. Returns list of team-stat dicts."""
    url = f"{INTERNAL_API_URL}?leagueId={league_id}"
    payload = {
        "uiv": 3,
        "refUrl": f"https://www.fantrax.com/fantasy/league/{league_id}/standings",
        "dt": 2, "at": 0, "av": "0.0",
        "tz": "America/New_York",
        "v": "182.0.1",
        "msgs": [{"method": "getStandings", "data": {}}],
    }
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "text/plain",
        "origin": "https://www.fantrax.com",
        "referer": f"https://www.fantrax.com/fantasy/league/{league_id}/standings",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    cookies = {"JSESSIONID": jsessionid}
    if fx_rm:
        cookies["FX_RM"] = fx_rm

    resp = requests.post(url, headers=headers, cookies=cookies, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    time.sleep(delay)

    # Check auth
    raw_txt = json.dumps(data)
    if "WARNING_NOT_LOGGED_IN" in raw_txt:
        raise RuntimeError(
            f"Session expired. Refresh JSESSIONID in config.yaml. (season {season})"
        )

    results = []
    for resp_item in data.get("responses", []):
        d = resp_item.get("data", {})
        table_list = d.get("tableList", [])

        # Table index 3 = "Standings - Stat Totals" (has both pts ranking + real stat values)
        # Table index 2 = "Standings - Point Totals" (has pts ranking but '-' for some stats)
        # We want index 3 for actual stat values with toolTip precision
        stat_table = None
        for tbl in table_list:
            cap = tbl.get("caption", "")
            if "Stat Totals" in cap:
                stat_table = tbl
                break

        if not stat_table:
            # Fallback to index 3 if caption doesn't match
            if len(table_list) > 3:
                stat_table = table_list[3]

        if not stat_table:
            print(f"  WARNING: No stat table found for season {season}")
            continue

        rows = stat_table.get("rows", [])
        for row in rows:
            fixed_cells = row.get("fixedCells", [])
            cells = row.get("cells", [])

            # fixedCells[0] = rank, fixedCells[1] = team name
            if len(fixed_cells) < 2:
                continue

            rank = parse_num(fixed_cells[0].get("content", ""))
            team_name = fixed_cells[1].get("content", "")
            team_id = fixed_cells[1].get("teamId", "")

            if not team_name:
                continue

            # Map to owner
            owner_info = owner_from_team(team_name)

            # Extract stats from cells (using toolTip for precision when available)
            def cell_val(i):
                if i >= len(cells):
                    return None
                c = cells[i]
                raw = c.get("toolTip") or c.get("content") or ""
                return parse_num(str(raw))

            # Cells: [pts, gp, ab, h, r, hr, rbi, sb, obp, ip, k, era, whip, svh3, wqs]
            row_data = {
                "season": season,
                "rank": rank,
                "team_name": team_name,
                "team_id": team_id,
                "owner_real_name": owner_info.get("real_name", "Unknown"),
                "owner_username": owner_info.get("username", "Unknown"),
                # Stats
                "pts": cell_val(0),
                "gp": cell_val(1),
                "ab": cell_val(2),
                "h": cell_val(3),
                "r": cell_val(4),
                "hr": cell_val(5),
                "rbi": cell_val(6),
                "sb": cell_val(7),
                "obp": cell_val(8),
                "ip": cell_val(9),
                "k": cell_val(10),
                "era": cell_val(11),
                "whip": cell_val(12),
                "svh3": cell_val(13),
                "wqs": cell_val(14),
            }
            results.append(row_data)

    return results


def build_standings_json(all_rows: List[Dict]) -> Dict:
    """Build the final standings.json structure."""
    from datetime import datetime

    seasons = sorted(set(r["season"] for r in all_rows))

    # All-time: sum counting stats, weighted average for rate stats
    # per owner across all seasons
    alltime_by_owner: Dict[str, Dict] = {}
    for row in all_rows:
        own = row["owner_real_name"]
        if own not in alltime_by_owner:
            alltime_by_owner[own] = {
                "owner_real_name": own,
                "owner_username": row["owner_username"],
                "seasons_played": 0,
                "total_pts": 0,
                "total_gp": 0,
                "ab": 0, "h": 0, "r": 0, "hr": 0, "rbi": 0, "sb": 0,
                "ip": 0.0, "k": 0, "svh3": 0.0, "wqs": 0.0,
                # for OBP/ERA/WHIP we track raw counts
                "_obp_sum": 0.0, "_obp_n": 0,
                "_era_sum": 0.0, "_era_n": 0,
                "_whip_sum": 0.0, "_whip_n": 0,
                "best_rank": 13,
                "best_season": None,
                "season_finishes": [],
            }
        o = alltime_by_owner[own]
        o["seasons_played"] += 1
        o["total_pts"] = round(o["total_pts"] + (row["pts"] or 0), 1)
        o["total_gp"] += (row["gp"] or 0)
        for stat in ("ab", "h", "r", "hr", "rbi", "sb", "k"):
            o[stat] = (o[stat] or 0) + (row[stat] or 0)
        o["ip"] = round((o["ip"] or 0) + (row["ip"] or 0), 1)
        o["svh3"] = round((o["svh3"] or 0) + (row["svh3"] or 0), 1)
        o["wqs"] = round((o["wqs"] or 0) + (row["wqs"] or 0), 1)
        if row["obp"] is not None:
            o["_obp_sum"] += row["obp"]; o["_obp_n"] += 1
        if row["era"] is not None:
            o["_era_sum"] += row["era"]; o["_era_n"] += 1
        if row["whip"] is not None:
            o["_whip_sum"] += row["whip"]; o["_whip_n"] += 1

        rank = row["rank"] or 13
        if rank < o["best_rank"]:
            o["best_rank"] = rank
            o["best_season"] = row["season"]
        o["season_finishes"].append({"season": row["season"], "rank": rank, "pts": row["pts"]})

    # Finalise rate stats and clean up
    alltime_list = []
    for own, o in alltime_by_owner.items():
        o["avg_obp"] = round(o["_obp_sum"] / o["_obp_n"], 4) if o["_obp_n"] else None
        o["avg_era"] = round(o["_era_sum"] / o["_era_n"], 3) if o["_era_n"] else None
        o["avg_whip"] = round(o["_whip_sum"] / o["_whip_n"], 4) if o["_whip_n"] else None
        for k in ("_obp_sum", "_obp_n", "_era_sum", "_era_n", "_whip_sum", "_whip_n"):
            del o[k]
        o["avg_pts_per_season"] = round(o["total_pts"] / o["seasons_played"], 2) if o["seasons_played"] else None
        o["season_finishes"] = sorted(o["season_finishes"], key=lambda x: x["season"])
        alltime_list.append(o)

    # Sort by total_pts desc
    alltime_list.sort(key=lambda x: x["total_pts"], reverse=True)
    for i, o in enumerate(alltime_list):
        o["alltime_rank"] = i + 1

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "seasons": seasons,
            "stat_columns": ["pts", "gp", "ab", "h", "r", "hr", "rbi", "sb", "obp",
                             "ip", "k", "era", "whip", "svh3", "wqs"],
        },
        "season_standings": all_rows,
        "alltime_standings": alltime_list,
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch Fantrax standings for all seasons")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--out", default="../docs/data/standings.json", help="Output JSON path")
    parser.add_argument("--seasons", nargs="+", type=int, help="Specific seasons to fetch (default: all)")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        cfg_path = Path(__file__).parent / "config.yaml"

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    jsessionid = cfg["jsessionid"]
    fx_rm = cfg.get("extra_cookies", {}).get("FX_RM", "")
    all_season_ids = {int(k): str(v) for k, v in cfg.get("all_season_league_ids", {}).items()}
    delay = cfg.get("request_delay", 0.4)

    # All seasons 2019–2026
    target_seasons = sorted(s for s in all_season_ids if 2019 <= s <= 2026)
    if args.seasons:
        target_seasons = [s for s in target_seasons if s in args.seasons]

    print(f"Fetching standings for seasons: {target_seasons}")

    all_rows = []
    for season in target_seasons:
        league_id = all_season_ids[season]
        print(f"  {season} (league: {league_id}) ...", end="", flush=True)
        try:
            rows = fetch_season_standings(league_id, season, jsessionid, fx_rm, delay)
            all_rows.extend(rows)
            print(f" {len(rows)} teams OK")
        except Exception as e:
            print(f" ERROR: {e}")

    if not all_rows:
        print("No data fetched. Exiting.")
        return

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result = build_standings_json(all_rows)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {out_path} ({out_path.stat().st_size // 1024} KB)")
    print(f"  {len(all_rows)} team-season records across {len(result['meta']['seasons'])} seasons")
    print(f"  {len(result['alltime_standings'])} unique owners in all-time standings")


if __name__ == "__main__":
    main()
