"""
build_dashboard.py — Data Pipeline: CSV → JSON
===============================================
Reads the 5 CSVs produced by fantrax_tracker_v4.py and writes
4 JSON files to docs/data/ for the GitHub Pages dashboard.

Usage:
    python build_dashboard.py
    python build_dashboard.py --data-root fantrax_data --docs-dir ../docs

Workflow:
    python fantrax_tracker_v4.py   # refresh data from Fantrax
    python build_dashboard.py      # regenerate docs/data/*.json
    git add docs/data/ && git commit && git push
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MONTH_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

SEASONS = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]

# Owners in alphabetical real_name order → fixed color index for JS
OWNERS_ALPHA = [
    "Alex Beim",
    "David Turley",
    "Evan Soraci",
    "Jack Dunne",
    "Jason Bartolini",
    "Jose Garcia-Chope",
    "Jordan Papula",
    "Liam Burns",
    "Matthew Zujewski",
    "Owen Hern",
    "Reed Heim",
    "Trent Radding",
]

# Ground-truth season history (from fantrax_tracker_v4.py OWNERS dict)
OWNER_HISTORY: Dict[str, Dict] = {
    "MattZujewski": {
        "real_name": "Matthew Zujewski",
        "teams": {2026: "Top Gunnar", 2025: "Quentin Pasquantino",
                  2024: "My Team is Better Than Reed's", 2023: "The Juice is Loose",
                  2022: "Purple Hayes", 2021: "Jung Gunnars",
                  2020: "The Juice is Loose", 2019: "My Team is Better Than Reed's"},
    },
    "lpburns": {
        "real_name": "Liam Burns",
        "teams": {2026: "Boot & Raleigh", 2025: "Boot & Raleigh",
                  2024: "Everybody Loves Ramon", 2023: "Soto's Johto League Champions",
                  2022: "Sohto League Champions", 2021: "Sohto League Champions",
                  2020: "Soto's Johto League Champions", 2019: "Everybody Loves Ramon"},
    },
    "sfgiant": {
        "real_name": "Jason Bartolini",
        "teams": {2026: "Gho-Strider", 2025: "Gho-Strider",
                  2024: "Waiting for Cespedes", 2023: "Waiting for Cespedes",
                  2022: "The Riley Reid's", 2021: "The J-Rod Squad",
                  2020: "The Riley Reid's", 2019: "Waiting for Cespedes"},
    },
    "Jpapula": {
        "real_name": "Jordan Papula",
        "teams": {2026: "Mojo Dojo Casas House", 2025: "Mojo Dojo Casas House",
                  2024: "Bay of Puigs", 2023: "Bay of Puigs",
                  2022: "The Phamtom Menace", 2021: "Attack of the Crons",
                  2020: "The Phamtom Menace", 2019: "Bay of Puigs"},
    },
    "trentradding": {
        "real_name": "Trent Radding",
        "teams": {2026: "Partially Torked", 2025: "A Few Jung Men",
                  2024: "A Few Jung Men", 2023: "Championship or Bust (2021)",
                  2022: "Fully Torked", 2021: "Turner Burners",
                  2020: "Championship or Bust (2021)", 2019: "Team CarmenCiardiello"},
    },
    "Jgchope": {
        "real_name": "Jose Garcia-Chope",
        "teams": {2026: "Rates & Carrolls", 2025: "Rates & Carrolls",
                  2024: "Shark(are)nado", 2023: "Shark(are)nado",
                  2022: "Shark(are)nado", 2021: "The KamikOzzie's",
                  2020: "Shark(are)nado", 2019: "Shark(are)nado"},
    },
    "rheim": {
        "real_name": "Reed Heim",
        "teams": {2026: "Reed's Trading Post", 2025: "Heimlich Maneuver",
                  2024: "Lil' Tikes", 2023: "Lil' Tikes",
                  2022: "If You Give a Mouse a Mookie", 2021: "Heimlich Maneuver",
                  2020: "If You Give a Mouse a Mookie", 2019: "Lil' Tikes"},
    },
    "owenhern": {
        "real_name": "Owen Hern",
        "teams": {2026: "The Juan-Binary Murderers' Row", 2025: "The New Murderers' Row",
                  2024: "DJ LeMachine", 2023: "DJ LeMachine",
                  2022: "DJ LeMachine", 2021: "DJ LeMachine",
                  2020: "DJ LeMachine", 2019: "DJ LeMachine"},
    },
    "esoraci": {
        "real_name": "Evan Soraci",
        "teams": {2026: "The Roman Empire", 2025: "The Kirby Superstars",
                  2024: "The 430 Million Dollar Man", 2023: "The Wuhan BatEaters",
                  2022: "Power Troutage", 2021: "The Kirby Superstars",
                  2020: "The Wuhan BatEaters", 2019: "The 430 Million Dollar Man"},
    },
    "Beim": {
        "real_name": "Alex Beim",
        "teams": {2026: "The Undisputed ERA", 2025: "Hold Me Closer, Ohtani Dancer",
                  2024: "Acuña Matata", 2023: "The Cole Train",
                  2022: "The Manbolorians", 2021: "Hold Me Closer, Ohtani Dancer",
                  2020: "The Cole Train", 2019: "Acuña Matata"},
    },
    "Jookuh": {
        "real_name": "Jack Dunne",
        "teams": {2026: "Wallace & deGromit", 2025: "The Wire Nation",
                  2024: "Richmond Mazers", 2023: "Richmond Mazers",
                  2022: "Petey Blinders", 2021: "Booze Cruz",
                  2020: "Richmond Mazers", 2019: "Richmond Mazers"},
    },
    "dturls55": {
        "real_name": "David Turley",
        "teams": {2026: "Yoshi's Riland", 2025: "Yoshi's Riland",
                  2024: "Seage(r) Miller Band", 2023: "Lux Luthors",
                  2022: "Ranger Things", 2021: "Ward Of The Rings",
                  2020: "Lux Luthors", 2019: "Seage(r) Miller Band"},
    },
}

# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def find_latest_run(data_root: str) -> Path:
    root = Path(data_root)
    latest = root / "latest"
    if latest.exists() or latest.is_symlink():
        return latest.resolve() / "output"
    runs = sorted(d for d in root.iterdir() if d.is_dir() and d.name.startswith("run_"))
    if not runs:
        sys.exit(f"No run directories found in {data_root}")
    return runs[-1] / "output"


def load_data(data_root: str) -> Dict[str, pd.DataFrame]:
    out_dir = find_latest_run(data_root)
    print(f"  Loading data from: {out_dir}")
    return {
        "transactions": pd.read_csv(out_dir / "transaction_history.csv"),
        "teams":        pd.read_csv(out_dir / "teams.csv"),
        "rosters":      pd.read_csv(out_dir / "current_rosters.csv"),
        "journeys":     pd.read_csv(out_dir / "player_journeys.csv"),
        "owner_mapping":pd.read_csv(out_dir / "owner_team_mapping.csv"),
    }

# ---------------------------------------------------------------------------
# Shared Helpers
# ---------------------------------------------------------------------------

def normalize_quotes(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return text.replace("\u2018", "'").replace("\u2019", "'")


def build_team_to_owner_lookup(owner_mapping_df: pd.DataFrame) -> Dict[str, str]:
    """team_name → real_name. Stores multiple normalized variants per team for robust matching."""
    lookup: Dict[str, str] = {}
    for _, row in owner_mapping_df.iterrows():
        raw      = str(row["team_name"])
        normed   = normalize_quotes(raw)
        real_name = str(row["real_name"])
        for variant in {raw, normed, raw.lower().strip(), normed.lower().strip()}:
            lookup[variant] = real_name
    return lookup


def parse_date_str(d: Any) -> Optional[datetime]:
    if not isinstance(d, str) or not d.strip():
        return None
    for fmt in ("%b %d %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(d.strip(), fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(d.strip())
    except Exception:
        return None


def to_iso(d: Any) -> Optional[str]:
    dt = parse_date_str(d)
    return dt.strftime("%Y-%m-%d") if dt else None


def days_since(iso_str: Optional[str]) -> Optional[int]:
    if not iso_str:
        return None
    try:
        start = date.fromisoformat(iso_str)
        return (date.today() - start).days
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Trade Extraction Helpers (ported from trade_dashboard.py)
# ---------------------------------------------------------------------------

def extract_trade_partners(details: str, all_team_names_sorted: List[str]) -> Set[str]:
    """Return set of team names that participated in this trade event."""
    details_norm = normalize_quotes(details)
    found: Set[str] = set()
    if "trades away" in details_norm:
        for team in all_team_names_sorted:
            if re.search(re.escape(team) + r"\s+trades away", details_norm):
                found.add(team)
    else:
        for team in all_team_names_sorted:
            if re.search(re.escape(team) + r"\s+to\s+", details_norm):
                found.add(team)
    return found


def resolve_partners_to_owners(
    partner_teams: Set[str],
    team_to_owner: Dict[str, str],
) -> Set[str]:
    owners: Set[str] = set()
    for t in partner_teams:
        owner = team_to_owner.get(normalize_quotes(t))
        if owner:
            owners.add(owner)
    return owners


def build_trade_events(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicated trade events with year/month columns."""
    trades = transactions_df[transactions_df["action_type"] == "TRADED"].copy()
    trades["details"] = trades["details"].fillna("").apply(normalize_quotes)
    unique = trades.drop_duplicates(subset=["date", "details"]).copy()

    def _year(d):
        dt = parse_date_str(d)
        return dt.year if dt else None

    def _month(d):
        dt = parse_date_str(d)
        return dt.month if dt else None

    unique["year"] = unique["date"].apply(_year)
    unique["month_num"] = unique["date"].apply(_month)
    unique["month"] = unique["month_num"].apply(
        lambda m: MONTH_ORDER[m - 1] if pd.notna(m) and m else None
    )
    unique["date_iso"] = unique["date"].apply(to_iso)
    return unique.reset_index(drop=True)


def build_trade_pairs_df(
    trade_events_df: pd.DataFrame,
    all_team_names_sorted: List[str],
    team_to_owner: Dict[str, str],
) -> pd.DataFrame:
    pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    pair_events: Dict[Tuple[str, str], List[str]] = defaultdict(list)

    for idx, row in trade_events_df.iterrows():
        teams = extract_trade_partners(row["details"], all_team_names_sorted)
        owners = resolve_partners_to_owners(teams, team_to_owner)
        if len(owners) < 2:
            continue
        event_id = row.get("date_iso", str(idx)) + f"-{idx:03d}"
        for a, b in combinations(sorted(owners), 2):
            pair_counts[(a, b)] += 1
            pair_events[(a, b)].append(event_id)

    records = [
        {"party_a": a, "party_b": b, "count": c, "event_ids": pair_events[(a, b)]}
        for (a, b), c in pair_counts.items()
    ]
    return pd.DataFrame(records) if records else pd.DataFrame(
        columns=["party_a", "party_b", "count", "event_ids"]
    )


def parse_asset_lists(
    details: str,
    all_team_names_sorted: List[str],
) -> Dict[str, Dict[str, List[str]]]:
    """
    Parse 'TeamA trades away P1 P2 TeamB trades away Q1' style details into
    {owner_team: {sent: [...], received: [...]}} keyed by team name.

    The actual Fantrax format has team names directly concatenated with no
    separator — each new segment starts with a known team name.
    We use the known team names (sorted longest-first) as split boundaries.
    """
    details_norm = normalize_quotes(details.strip())
    result: Dict[str, Dict[str, List[str]]] = {}

    if "trades away" not in details_norm:
        return result

    # Build a regex pattern that splits on "<team> trades away" anchors,
    # using team names sorted by length descending to avoid prefix collisions.
    # We keep the delimiters in the output via a capture group.
    team_pattern = "|".join(
        re.escape(normalize_quotes(t)) for t in all_team_names_sorted
    )
    # Split text into segments: each starts with "TeamName trades away ..."
    # Pattern: look for <team-name> immediately followed by " trades away"
    split_re = re.compile(
        rf"(?=(?:{team_pattern})\s+trades\s+away\s)", re.IGNORECASE
    )
    segments = [s.strip() for s in split_re.split(details_norm) if s.strip()]

    for seg in segments:
        # Match: <team> trades away <assets>
        m = re.match(
            rf"^({team_pattern})\s+trades\s+away\s+(.*)",
            seg, re.IGNORECASE | re.DOTALL
        )
        if not m:
            continue
        sender_team = normalize_quotes(m.group(1).strip())
        assets_raw = m.group(2).strip()

        # Exclude items that look like budget lines or draft picks
        # Players are separated by spaces (names) and commas; skip:
        #   "Budget: $X.XX"  and "XXXX Draft Pick, Round N (TeamName)"
        raw_items = [a.strip() for a in re.split(r",\s*", assets_raw) if a.strip()]
        players: List[str] = []
        for item in raw_items:
            item = item.strip()
            if re.match(r"Budget\s*:", item, re.IGNORECASE):
                continue
            if re.search(r"Draft Pick", item, re.IGNORECASE):
                continue
            if item:
                players.append(item)

        if players:
            if sender_team not in result:
                result[sender_team] = {"sent": [], "received": []}
            result[sender_team]["sent"].extend(players)

    return result

# ---------------------------------------------------------------------------
# Player Journey Helpers (ported from player_history_dashboard.py)
# ---------------------------------------------------------------------------

def compute_player_team_counts(journeys_df: pd.DataFrame) -> pd.DataFrame:
    """Count distinct OWNERS (not team names) per player — name changes don't count as new team."""
    grouped = journeys_df.groupby(["player_id", "player_name"]).agg(
        distinct_owners=("owner_real_name", "nunique"),
        distinct_teams=("team_name", "nunique"),   # kept for reference
        total_stints=("team_name", "count"),
    ).reset_index()
    # Sort by distinct owners (true mobility) then stints
    return grouped.sort_values(["distinct_owners", "total_stints"], ascending=False).reset_index(drop=True)


def compute_owner_player_throughput(
    journeys_df: pd.DataFrame,
    team_to_owner: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """Count unique players and stints + acquisition breakdown per owner."""
    df = journeys_df.copy()
    # Re-resolve "Unknown" stints using team-name lookup before computing throughput
    if team_to_owner:
        mask = df["owner_real_name"].isna() | df["owner_real_name"].isin(["", "Unknown"])
        df.loc[mask, "owner_real_name"] = df.loc[mask, "team_name"].apply(
            lambda t: team_to_owner.get(normalize_quotes(str(t))) or
                      team_to_owner.get(normalize_quotes(str(t)).lower()) or "Unknown"
        )
    df = df[df["owner_real_name"].notna() & ~df["owner_real_name"].isin(["", "Unknown"])]

    unique_players = df.groupby("owner_real_name")["player_name"].nunique().reset_index()
    unique_players.columns = ["owner", "unique_players"]

    total_stints = df.groupby("owner_real_name").size().reset_index(name="total_stints")
    total_stints.columns = ["owner", "total_stints"]

    acq_pivot = df.groupby(["owner_real_name", "acquisition_type"]).size().unstack(fill_value=0)
    acq_pivot.index.name = "owner"
    acq_pivot = acq_pivot.reset_index()

    merged = unique_players.merge(total_stints, on="owner").merge(acq_pivot, on="owner", how="left")
    return merged.sort_values("unique_players", ascending=False).reset_index(drop=True)


def compute_player_tenure_stats(journeys_df: pd.DataFrame) -> Dict[str, Any]:
    """Compute tenure stats for completed stints."""
    df = journeys_df.dropna(subset=["end_date"]).copy()
    df["_start"] = df["start_date"].apply(parse_date_str)
    df["_end"]   = df["end_date"].apply(parse_date_str)
    df = df.dropna(subset=["_start", "_end"]).copy()
    df["tenure_days"] = (df["_end"] - df["_start"]).apply(lambda x: x.days)
    df = df[df["tenure_days"] >= 0]

    if df.empty:
        return {"median_days": 0, "mean_days": 0, "histogram": [], "by_acquisition_type": {}}

    def _boxplot(series: pd.Series) -> Dict[str, float]:
        s = series.dropna()
        if s.empty:
            return {}
        return {
            "median": float(s.median()),
            "q1":     float(s.quantile(0.25)),
            "q3":     float(s.quantile(0.75)),
            "min":    float(s.min()),
            "max":    float(s.max()),
        }

    # Histogram (40 buckets)
    max_days = int(df["tenure_days"].max())
    bucket_size = max(1, max_days // 40)
    hist_buckets = []
    for bucket_start in range(0, max_days + bucket_size, bucket_size):
        bucket_end = bucket_start + bucket_size
        count = int(((df["tenure_days"] >= bucket_start) & (df["tenure_days"] < bucket_end)).sum())
        if count > 0 or bucket_start < max_days:
            hist_buckets.append({"bucket_start": bucket_start, "bucket_end": bucket_end, "count": count})

    # By acquisition type
    by_acq: Dict[str, Any] = {}
    for acq_type, group in df.groupby("acquisition_type"):
        by_acq[str(acq_type)] = _boxplot(group["tenure_days"])

    return {
        "median_days": float(df["tenure_days"].median()),
        "mean_days":   float(df["tenure_days"].mean()),
        "histogram":   hist_buckets,
        "by_acquisition_type": by_acq,
    }


def build_player_index(stints: List[Dict]) -> Dict[str, Any]:
    """Build player_id → {name, distinct_owners, distinct_teams, total_stints, owner_changes, current_owner, stint_indices}

    distinct_owners counts unique real owners (ignoring team name changes year-to-year).
    distinct_teams counts unique team names (may be higher due to rebranding).
    owner_changes counts transitions to a DIFFERENT owner — the true "travel" metric (BUG-02).
      Same-owner KEPT stints do not increment this counter.
    """
    index: Dict[str, Any] = {}
    for i, stint in enumerate(stints):
        pid = stint["player_id"]
        if pid not in index:
            index[pid] = {
                "player_name":     stint["player_name"],
                "distinct_owners": set(),   # by real_name — ignores name changes
                "distinct_teams":  set(),   # by team_name — counts renames too
                "total_stints":    0,
                "owner_changes":   0,       # BUG-02: only count cross-owner moves
                "_prev_owner":     None,    # transient — stripped before return
                "current_owner":   None,
                "stint_indices":   [],
            }
        owner = stint["owner_real_name"]
        index[pid]["distinct_owners"].add(owner)
        index[pid]["distinct_teams"].add(stint["team_name"])
        index[pid]["total_stints"] += 1
        index[pid]["stint_indices"].append(i)
        # Count as an owner change only when the owner differs from the previous stint
        # (excludes KEPT stints with the same owner, which inflate total_stints)
        if owner != "Unknown" and owner != index[pid]["_prev_owner"] and index[pid]["_prev_owner"] is not None:
            index[pid]["owner_changes"] += 1
        index[pid]["_prev_owner"] = owner
        if stint["is_current"]:
            index[pid]["current_owner"] = owner

    # Serialize sets → counts; strip transient field
    for pid in index:
        index[pid]["distinct_owners"] = len(index[pid]["distinct_owners"])
        index[pid]["distinct_teams"]  = len(index[pid]["distinct_teams"])
        del index[pid]["_prev_owner"]

    return index


def build_owner_stats(
    journeys_df: pd.DataFrame,
    trade_events_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    all_team_names_sorted: List[str],
    team_to_owner: Dict[str, str],
) -> Dict[str, Dict]:
    """Build per-owner stats block for teams.json."""
    stats: Dict[str, Dict] = {}

    # Unique players per owner
    for owner in OWNERS_ALPHA:
        stats[owner] = {
            "total_trades": 0,
            "unique_players_rostered": 0,
            "most_traded_with": None,
            "most_traded_with_count": 0,
            "median_player_tenure_days": 0,
            "most_common_acquisition": None,
        }

    # Unique players from journeys
    for owner, group in journeys_df[journeys_df["owner_real_name"].notna()].groupby("owner_real_name"):
        if owner in stats:
            stats[owner]["unique_players_rostered"] = int(group["player_name"].nunique())

    # Trade counts and partner analysis
    owner_trade_counts: Dict[str, int] = defaultdict(int)
    pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)

    for _, row in trade_events_df.iterrows():
        teams = extract_trade_partners(row["details"], all_team_names_sorted)
        owners = resolve_partners_to_owners(teams, team_to_owner)
        for o in owners:
            owner_trade_counts[o] += 1
        if len(owners) >= 2:
            for a, b in combinations(sorted(owners), 2):
                pair_counts[(a, b)] += 1

    for owner in OWNERS_ALPHA:
        stats[owner]["total_trades"] = owner_trade_counts.get(owner, 0)

    # Most traded with
    for (a, b), cnt in pair_counts.items():
        for owner, partner in [(a, b), (b, a)]:
            if owner in stats and cnt > stats[owner]["most_traded_with_count"]:
                stats[owner]["most_traded_with"] = partner
                stats[owner]["most_traded_with_count"] = cnt

    # Median tenure and most common acquisition
    tenure_df = compute_player_tenure_stats.__wrapped__ if hasattr(compute_player_tenure_stats, '__wrapped__') else None
    jdf = journeys_df.copy()
    jdf["_start"] = jdf["start_date"].apply(parse_date_str)
    jdf["_end"]   = jdf["end_date"].apply(parse_date_str)
    jdf = jdf.dropna(subset=["_start", "_end"])
    jdf["tenure_days"] = (jdf["_end"] - jdf["_start"]).apply(lambda x: x.days)
    jdf = jdf[jdf["tenure_days"] >= 0]

    for owner, group in jdf[jdf["owner_real_name"].notna()].groupby("owner_real_name"):
        if owner in stats:
            stats[owner]["median_player_tenure_days"] = float(group["tenure_days"].median())

    for owner, group in journeys_df[journeys_df["owner_real_name"].notna()].groupby("owner_real_name"):
        if owner in stats and not group.empty:
            # Exclude KEPT — it's a roster retention flag, not a real acquisition method
            real_acq = group[group["acquisition_type"] != "KEPT"]["acquisition_type"]
            acq_counts = real_acq.value_counts()
            if not acq_counts.empty:
                stats[owner]["most_common_acquisition"] = str(acq_counts.index[0])

    return stats

# ---------------------------------------------------------------------------
# JSON Builder: teams.json
# ---------------------------------------------------------------------------

def build_teams_json(
    teams_df: pd.DataFrame,
    journeys_df: pd.DataFrame,
    trade_events_df: pd.DataFrame,
    rosters_df: pd.DataFrame,
    all_team_names_sorted: List[str],
    team_to_owner: Dict[str, str],
    total_trade_events: int,
) -> Dict:
    owner_stats = build_owner_stats(
        journeys_df, trade_events_df, rosters_df,
        all_team_names_sorted, team_to_owner
    )

    owners_list = []
    for username, data in OWNER_HISTORY.items():
        real_name = data["real_name"]
        history = [
            {"season": yr, "team_name": tn}
            for yr, tn in sorted(data["teams"].items())
        ]
        current_team = data["teams"].get(max(data["teams"].keys()), "")
        o_stats = owner_stats.get(real_name, {})
        owners_list.append({
            "username":    username,
            "real_name":   real_name,
            "current_team": current_team,
            "color_index": OWNERS_ALPHA.index(real_name) if real_name in OWNERS_ALPHA else 0,
            "history":     history,
            "stats":       o_stats,
        })

    # Sort by real_name for consistency
    owners_list.sort(key=lambda x: x["real_name"])

    unique_players = int(journeys_df["player_name"].nunique())

    return {
        "meta": {
            "generated_at":       datetime.utcnow().isoformat() + "Z",
            "league_name":        "Ducks on the Pond Dynasty",
            "total_trade_events": total_trade_events,
            "total_unique_players": unique_players,
            "total_owners":       len(owners_list),
            "seasons":            SEASONS,
        },
        "owners": owners_list,
    }

# ---------------------------------------------------------------------------
# JSON Builder: trades.json
# ---------------------------------------------------------------------------

def build_assets_by_party_from_rows(
    transactions_df: pd.DataFrame,
    team_to_owner: Dict[str, str],
) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    """
    Build a lookup keyed by (date, details) → {owner: {sent: [...], received: [...]}}
    using the per-player CSV rows, where team_name = receiving team and player_name = player.

    This replaces regex parsing of the details string, which cannot reliably split
    space-separated multi-player strings like 'Jarren Duran Jack Leiter'.
    """
    trades = transactions_df[transactions_df["action_type"] == "TRADED"].copy()
    trades["details_norm"] = trades["details"].fillna("").apply(normalize_quotes)
    trades["date_str"]     = trades["date"].fillna("").astype(str)
    trades["player_name"]  = trades["player_name"].fillna("").astype(str)
    trades["team_name_norm"] = trades["team_name"].fillna("").apply(
        lambda t: normalize_quotes(str(t))
    )

    # Each row: player_name was RECEIVED by team_name / owner_real_name.
    # Group by (date, details) to reconstruct each trade event's asset lists.
    result: Dict[str, Dict[str, Dict[str, List[str]]]] = {}

    for (date_str, details_norm), group in trades.groupby(["date_str", "details_norm"]):
        key = (date_str, details_norm)
        assets: Dict[str, Dict[str, List[str]]] = {}

        # Collect all receiving owners in this trade and what they received
        all_receiving_owners: Set[str] = set()
        for _, row in group.iterrows():
            player  = row["player_name"].strip()
            team_nm = row["team_name_norm"].strip()
            if not player:
                continue
            owner = (
                team_to_owner.get(team_nm)
                or team_to_owner.get(team_nm.lower())
            )
            if not owner:
                # Fall back to owner_real_name from the row itself
                owner_csv = str(row.get("owner_real_name", "")).strip()
                owner = owner_csv if owner_csv and owner_csv != "Unknown" else None
            if not owner:
                continue
            all_receiving_owners.add(owner)
            if owner not in assets:
                assets[owner] = {"sent": [], "received": []}
            assets[owner]["received"].append(player)

        # Sent = what the OTHER owners received.
        # For each owner, sent = everything received by the other parties.
        for owner in all_receiving_owners:
            for other_owner in all_receiving_owners:
                if other_owner == owner:
                    continue
                assets[owner]["sent"].extend(assets[other_owner]["received"])

        result[key] = assets

    return result


def build_trades_json(
    trade_events_df: pd.DataFrame,
    trade_pairs_df: pd.DataFrame,
    all_team_names_sorted: List[str],
    team_to_owner: Dict[str, str],
    transactions_df: Optional[pd.DataFrame] = None,
) -> Dict:
    owner_trade_counts: Dict[str, int] = defaultdict(int)
    trades_by_ym: Dict[str, int] = defaultdict(int)
    trades_by_year_owner: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    trade_events_list = []

    # Build per-row asset lookup (BUG-01 fix: use CSV player rows, not regex parsing)
    row_assets_lookup: Dict[Tuple[str, str], Dict[str, Dict[str, List[str]]]] = {}
    if transactions_df is not None:
        row_assets_lookup = build_assets_by_party_from_rows(transactions_df, team_to_owner)

    for idx, row in trade_events_df.iterrows():
        teams  = extract_trade_partners(row["details"], all_team_names_sorted)
        owners = resolve_partners_to_owners(teams, team_to_owner)
        party_count = len(owners)
        trade_type = f"{party_count}-team" if party_count >= 2 else "unknown"

        event_id = (row.get("date_iso") or "unknown") + f"-{idx:03d}"

        for o in owners:
            owner_trade_counts[o] += 1

        year_str  = str(int(row["year"])) if pd.notna(row.get("year")) else None
        month_num = int(row["month_num"]) if pd.notna(row.get("month_num")) else None
        ym_key    = f"{year_str}-{month_num:02d}" if year_str and month_num else None
        if ym_key:
            trades_by_ym[ym_key] += 1
        if year_str:
            for o in owners:
                trades_by_year_owner[year_str][o] += 1

        # BUG-01: Look up assets from per-player CSV rows first (exact, no parsing required).
        # Fall back to regex parsing only if CSV lookup misses (e.g. format "X to Y").
        date_str_key = str(row.get("date", "")).strip()
        details_norm_key = normalize_quotes(str(row.get("details", "")).strip())
        assets_by_owner = row_assets_lookup.get((date_str_key, details_norm_key), {})
        if not assets_by_owner:
            assets = parse_asset_lists(row["details"], all_team_names_sorted)
            for team_name, asset_data in assets.items():
                owner = team_to_owner.get(normalize_quotes(team_name))
                if owner:
                    assets_by_owner[owner] = asset_data

        trade_events_list.append({
            "event_id":        event_id,
            "date":            str(row["date"]) if pd.notna(row.get("date")) else None,
            "date_iso":        row.get("date_iso"),
            "year":            int(row["year"]) if pd.notna(row.get("year")) else None,
            "month":           row.get("month"),
            "month_num":       month_num,
            "details_raw":     str(row["details"]),
            "parties":         sorted(owners),
            "party_count":     party_count,
            "trade_type":      trade_type,
            "assets_by_party": assets_by_owner,
        })

    # Sort trade events by date
    trade_events_list.sort(
        key=lambda x: x["date_iso"] or "0000-00-00", reverse=True
    )

    # Build matrix
    all_owners_in_trades = sorted(set(owner_trade_counts.keys()))
    matrix_cells = []
    if not trade_pairs_df.empty:
        for _, row in trade_pairs_df.iterrows():
            matrix_cells.append({
                "row":   row["party_a"],
                "col":   row["party_b"],
                "count": int(row["count"]),
            })

    # Trade pairs as list of dicts
    pairs_list = []
    if not trade_pairs_df.empty:
        for _, row in trade_pairs_df.iterrows():
            pairs_list.append({
                "party_a":   row["party_a"],
                "party_b":   row["party_b"],
                "count":     int(row["count"]),
                "event_ids": row.get("event_ids", []),
            })
        pairs_list.sort(key=lambda x: x["count"], reverse=True)

    return {
        "meta": {
            "generated_at":       datetime.utcnow().isoformat() + "Z",
            "total_trade_events": len(trade_events_list),
        },
        "trade_events":         trade_events_list,
        "trade_pairs":          pairs_list,
        "owner_trade_counts":   dict(owner_trade_counts),
        "trades_by_year_month": dict(trades_by_ym),
        "trades_by_year_owner": {yr: dict(v) for yr, v in trades_by_year_owner.items()},
        "matrix": {
            "owners_ordered": OWNERS_ALPHA,
            "cells":          matrix_cells,
        },
    }

# ---------------------------------------------------------------------------
# JSON Builder: journeys.json
# ---------------------------------------------------------------------------

def build_journeys_json(
    journeys_df: pd.DataFrame,
    team_to_owner: Dict[str, str],
) -> Dict:
    stints = []

    for _, row in journeys_df.iterrows():
        start_iso = to_iso(row.get("start_date"))
        end_iso   = to_iso(row.get("end_date")) if pd.notna(row.get("end_date")) else None
        is_current = end_iso is None

        tenure_days: Optional[int] = None
        if start_iso and end_iso:
            try:
                s = date.fromisoformat(start_iso)
                e = date.fromisoformat(end_iso)
                tenure_days = (e - s).days
            except Exception:
                pass

        _owner_csv = str(row.get("owner_real_name", "")).strip()
        team_nm    = normalize_quotes(str(row.get("team_name", "")))
        # Re-resolve "Unknown" stints using the team-name lookup (handles smart-quote variants)
        if not _owner_csv or _owner_csv == "Unknown":
            owner = team_to_owner.get(team_nm) or team_to_owner.get(team_nm.lower()) or "Unknown"
        else:
            owner = _owner_csv

        stints.append({
            "player_id":        str(row.get("player_id", "")),
            "player_name":      str(row.get("player_name", "")),
            "team_name":        str(row.get("team_name", "")),
            "owner_real_name":  owner,
            "start_date":       start_iso,
            "end_date":         end_iso,
            "tenure_days":      tenure_days,
            "acquisition_type": str(row.get("acquisition_type", "")),
            "acquisition_salary": str(row.get("acquisition_salary", "")) if pd.notna(row.get("acquisition_salary")) else None,
            "is_current":       is_current,
        })

    # Sort: player_id then start_date
    stints.sort(key=lambda x: (x["player_id"], x["start_date"] or ""))

    player_index = build_player_index(stints)

    # Most traveled players (top 25) — ranked by distinct OWNERS, then owner_changes.
    # distinct_owners: how many unique managers ever owned this player.
    # owner_changes:   how many times the player moved to a DIFFERENT owner (BUG-02 fix).
    #   Excludes same-owner KEPT stints that inflate total_stints without real travel.
    most_traveled = sorted(
        [
            {
                "player_id":       pid,
                "player_name":     data["player_name"],
                "distinct_owners": data["distinct_owners"],  # true mobility metric
                "distinct_teams":  data["distinct_teams"],   # raw team-name count for reference
                "total_stints":    data["total_stints"],
                "owner_changes":   data["owner_changes"],    # BUG-02: cross-owner moves only
                "current_owner":   data["current_owner"],
            }
            for pid, data in player_index.items()
        ],
        key=lambda x: (x["distinct_owners"], x["owner_changes"]),
        reverse=True,
    )[:25]

    # Owner throughput — pass team_to_owner so Unknown stints are resolved
    throughput_df = compute_owner_player_throughput(journeys_df, team_to_owner)
    owner_throughput: Dict[str, Any] = {}
    for _, row in throughput_df.iterrows():
        owner = str(row["owner"])
        acq_breakdown = {}
        for acq in ["KEPT", "CLAIMED", "TRADED", "DRAFTED"]:
            if acq in row.index:
                v = row.get(acq, 0)
                acq_breakdown[acq] = int(v) if pd.notna(v) else 0
        owner_throughput[owner] = {
            "unique_players":       int(row["unique_players"]),
            "total_stints":         int(row["total_stints"]),
            "acquisition_breakdown": acq_breakdown,
        }

    tenure_stats = compute_player_tenure_stats(journeys_df)

    return {
        "meta": {
            "generated_at":         datetime.utcnow().isoformat() + "Z",
            "total_stints":         len(stints),
            "total_unique_players": len(player_index),
        },
        "stints":                stints,
        "player_index":          player_index,
        "most_traveled_players": most_traveled,
        "owner_throughput":      owner_throughput,
        "tenure_stats":          tenure_stats,
    }

# ---------------------------------------------------------------------------
# JSON Builder: rosters.json
# ---------------------------------------------------------------------------

def build_rosters_json(
    rosters_df: pd.DataFrame,
    journeys_df: pd.DataFrame,
) -> Dict:
    # Build a lookup: player_id → owner → all stints (sorted by start_date asc)
    # Used to look up the original acquisition when a player was KEPT.
    owner_stints_by_pid: Dict[str, Dict[str, List]] = defaultdict(lambda: defaultdict(list))
    for _, row in journeys_df.iterrows():
        pid   = str(row.get("player_id", ""))
        owner = str(row.get("owner_real_name", ""))
        if pid and owner:
            owner_stints_by_pid[pid][owner].append({
                "start_date":      to_iso(row.get("start_date")),
                "end_date":        to_iso(row.get("end_date")) if not (pd.isna(row.get("end_date")) or str(row.get("end_date","")).strip()=="") else None,
                "acquisition_type": str(row.get("acquisition_type", "")),
            })

    # Sort each list by start_date asc
    for pid in owner_stints_by_pid:
        for owner in owner_stints_by_pid[pid]:
            owner_stints_by_pid[pid][owner].sort(key=lambda s: s["start_date"] or "")

    # Build current stint lookup: player_id → {start_date, acquisition_type}
    # For KEPT players: walk back to find the original acquisition + start date
    # for the current unbroken run with this owner.
    current_stints: Dict[str, str] = {}
    current_acq: Dict[str, str] = {}
    current_real_acq: Dict[str, str] = {}  # non-KEPT original acquisition type

    for _, row in journeys_df.iterrows():
        if pd.isna(row.get("end_date")) or str(row.get("end_date", "")).strip() == "":
            pid   = str(row.get("player_id", ""))
            owner = str(row.get("owner_real_name", ""))
            iso   = to_iso(row.get("start_date"))
            if pid and iso:
                current_stints[pid] = iso
                current_acq[pid]    = str(row.get("acquisition_type", ""))

                # If acquired via KEPT, find the earliest consecutive stint with this owner
                # that represents the real original acquisition.
                if current_acq[pid] == "KEPT" and owner:
                    stints = owner_stints_by_pid.get(pid, {}).get(owner, [])
                    # Walk back from the most recent (current) stint to find the first
                    # in an unbroken chain (no gap > 14 days between consecutive stints)
                    earliest_start = iso
                    earliest_acq   = "KEPT"
                    for s in reversed(stints):
                        if s["acquisition_type"] != "KEPT":
                            earliest_start = s["start_date"] or iso
                            earliest_acq   = s["acquisition_type"]
                            break
                        elif s["start_date"] and s["start_date"] < earliest_start:
                            earliest_start = s["start_date"]

                    current_stints[pid]    = earliest_start
                    current_real_acq[pid]  = earliest_acq
                else:
                    current_real_acq[pid] = current_acq[pid]

    players_list = []
    by_owner: Dict[str, List] = defaultdict(list)
    status_by_team: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for _, row in rosters_df.iterrows():
        pid          = str(row.get("player_id", ""))
        stint_start  = current_stints.get(pid)
        days_on_team = days_since(stint_start)
        # Use the real (non-KEPT) acquisition type so the roster shows how the
        # player was originally acquired, not just "KEPT" for retained players.
        acq_type     = current_real_acq.get(pid, current_acq.get(pid, ""))
        team_name    = str(row.get("team_name", ""))
        owner        = str(row.get("owner_real_name", ""))
        status       = str(row.get("roster_status", ""))

        player = {
            "player_id":       pid,
            "player_name":     str(row.get("player_name", "")),
            "position":        str(row.get("position", "")),
            "roster_status":   status,
            "team_name":       team_name,
            "owner_real_name": owner,
            "stint_start":     stint_start,
            "days_on_team":    days_on_team,
            "acquisition_type": acq_type,
        }
        players_list.append(player)
        by_owner[owner].append(player)
        status_by_team[team_name][status] += 1

    # Sort each owner's roster: Active first, then by days desc
    status_order = {"ACTIVE": 0, "INJURED_RESERVE": 1, "RESERVE": 2, "MINORS": 3}
    for owner in by_owner:
        by_owner[owner].sort(
            key=lambda p: (
                status_order.get(p["roster_status"], 9),
                -(p["days_on_team"] or 0),
            )
        )

    return {
        "meta": {
            "generated_at":   datetime.utcnow().isoformat() + "Z",
            "total_rostered": len(players_list),
            "season":         2026,
        },
        "players":                players_list,
        "by_owner":               dict(by_owner),
        "status_breakdown_by_team": {k: dict(v) for k, v in status_by_team.items()},
    }

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build dashboard JSON from CSVs")
    p.add_argument("--data-root", default="fantrax_data")
    p.add_argument("--docs-dir",  default="../docs")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print("=" * 60)
    print("  Dashboard JSON Builder")
    print("=" * 60)

    # --- Load ---
    data = load_data(args.data_root)
    txns         = data["transactions"]
    teams_df     = data["teams"]
    rosters_df   = data["rosters"]
    journeys_df  = data["journeys"]
    owner_mapping = data["owner_mapping"]

    # --- Build lookups ---
    team_to_owner = build_team_to_owner_lookup(owner_mapping)
    # Augment with OWNER_HISTORY (covers 2020 teams and any other gaps in the CSV)
    for _odata in OWNER_HISTORY.values():
        _real = _odata["real_name"]
        for _team in _odata["teams"].values():
            for _variant in {_team, normalize_quotes(_team), _team.lower().strip(), normalize_quotes(_team).lower().strip()}:
                team_to_owner.setdefault(_variant, _real)
    all_team_names_sorted = sorted(
        {normalize_quotes(t) for t in txns["team_name"].dropna().unique()},
        key=len, reverse=True,
    )

    # --- Trade events ---
    print("\n[1/4] Building trade data...")
    trade_events = build_trade_events(txns)
    print(f"      Unique trade events: {len(trade_events)}")
    trade_pairs = build_trade_pairs_df(trade_events, all_team_names_sorted, team_to_owner)
    print(f"      Trade pairs: {len(trade_pairs)}")

    # --- Output dir ---
    docs_dir = Path(args.docs_dir)
    data_dir = docs_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # --- teams.json ---
    print("\n[2/4] Building teams.json...")
    teams_data = build_teams_json(
        teams_df, journeys_df, trade_events, rosters_df,
        all_team_names_sorted, team_to_owner, len(trade_events),
    )
    out = data_dir / "teams.json"
    out.write_text(json.dumps(teams_data, indent=2, default=str), encoding="utf-8")
    print(f"      Written: {out} ({out.stat().st_size // 1024}KB)")

    # --- trades.json ---
    print("\n[3/4] Building trades.json...")
    trades_data = build_trades_json(
        trade_events, trade_pairs, all_team_names_sorted, team_to_owner,
        transactions_df=txns,
    )
    out = data_dir / "trades.json"
    out.write_text(json.dumps(trades_data, indent=2, default=str), encoding="utf-8")
    print(f"      Written: {out} ({out.stat().st_size // 1024}KB)")

    # --- journeys.json ---
    print("\n[4a/4] Building journeys.json...")
    journeys_data = build_journeys_json(journeys_df, team_to_owner)
    out = data_dir / "journeys.json"
    out.write_text(json.dumps(journeys_data, indent=2, default=str), encoding="utf-8")
    print(f"      Written: {out} ({out.stat().st_size // 1024}KB)")

    # --- rosters.json ---
    print("\n[4b/4] Building rosters.json...")
    rosters_data = build_rosters_json(rosters_df, journeys_df)
    out = data_dir / "rosters.json"
    out.write_text(json.dumps(rosters_data, indent=2, default=str), encoding="utf-8")
    print(f"      Written: {out} ({out.stat().st_size // 1024}KB)")

    print("\n" + "=" * 60)
    print("  ✓ All JSON files written to", data_dir)
    print("  Next: git add docs/data/ && git commit && git push")
    print("=" * 60)


if __name__ == "__main__":
    main()
