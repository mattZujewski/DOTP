"""Build a validated dashboard snapshot from the fresh all-season league log archive.

Uses executed non-deleted claims, drops, trades, and actual draft selections.
Does not merge the legacy shared-cache observations into the refreshed ledger.
"""
import argparse
from collections import defaultdict
from datetime import datetime
import json
import logging
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from collection_state import atomic_json, publish_run
from fantrax_tracker_v4 import (Config, setup_run_dirs, save_run_config, export_all,
                                build_player_journeys, strip_html, get_owner_from_team_name)
from fetch_standings import owner_from_team
from player_directory import player_names


def read(path):
    return json.loads(Path(path).read_text())


def log_time(text):
    for fmt in ("%a %b %d, %Y, %I:%M%p", "%a %b %d, %Y, %I:%M %p"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=ZoneInfo("America/New_York"))
        except ValueError:
            pass
    raise ValueError(f"Unrecognized transaction time: {text}")


def grouped_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        if not row.get("executed") or row.get("deleted"):
            raise ValueError("Unexecuted or deleted transaction in archive")
        groups[row["txSetId"]].append(row)
    for txid, group in groups.items():
        shared = {}
        for row in group:
            for cell in row["cells"]:
                if cell.get("key") in ("date", "team"):
                    if cell["key"] in shared and shared[cell["key"]] != cell:
                        raise ValueError("Conflicting group date/team")
                    shared[cell["key"]] = cell
        if "date" not in shared:
            raise ValueError(f"Missing date for transaction {txid}")
        yield txid, log_time(shared["date"]["content"]), [(row, {**shared, **{c["key"]: c for c in row["cells"]}}) for row in group]


def trade_asset(row, names):
    scorer = row.get("scorer", {})
    if scorer.get("scorerId"):
        return names.get(scorer["scorerId"], scorer.get("name"))
    if row.get("draftPickDisplayParts"):
        pick = row["draftPickDisplayParts"]
        return strip_html(pick["year"]) + ", " + strip_html(pick["roundInfo"])
    if row.get("budgetAmountTradeObj"):
        return "Budget: " + row["budgetAmountTradeObj"]["budget"]
    raise ValueError("Unrecognized trade asset")


def parse_log_rows(rows, year, view, owners, names):
    transactions, trades = [], []
    for txid, timestamp, group in grouped_rows(rows):
        event_id = f"{year}:{txid}"
        common = {"date": timestamp.strftime("%b %d %Y"), "occurred_at": timestamp.isoformat(),
                  "event_id": event_id, "source_season": year}
        details = ""
        if view == "TRADE":
            senders = defaultdict(list)
            assets_by_owner = {}
            asset_types = defaultdict(set)
            pick_assets = []
            for row, cells in group:
                if cells["to"].get("content") == "(Drop)":
                    continue  # Roster-space drops are not assets received by the partner.
                senders[cells["from"]["content"]].append(trade_asset(row, names))
                sender = owners[cells["from"]["teamId"]]["real_name"]
                recipient = owners[cells["to"]["teamId"]]["real_name"]
                for owner in (sender, recipient):
                    assets_by_owner.setdefault(owner, {"sent": [], "received": []})
                if row.get("scorer", {}).get("scorerId"):
                    name = trade_asset(row, names)
                    assets_by_owner[sender]["sent"].append(name)
                    assets_by_owner[recipient]["received"].append(name)
                    asset_types[sender].add("player")
                elif row.get("draftPickDisplayParts"):
                    asset_types[sender].add("pick")
                    pick = row["draftPickDisplayParts"]
                    year_text, round_text = strip_html(pick["year"]), strip_html(pick["roundInfo"])
                    round_match = re.fullmatch(r"Round (\d+)(?: Pick (\d+)| \((.*)\))", round_text)
                    if not round_match:
                        raise ValueError(f"Unknown pick format: {round_text}")
                    pick_assets.append({"pick_year": int(re.search(r"\d{4}", year_text).group()),
                        "pick_round": int(round_match[1]), "pick_in_round": int(round_match[2]) if round_match[2] else None,
                        "original_holder": round_match[3] or "", "sending_owner": sender, "receiving_owner": recipient})
                else:
                    asset_types[sender].add("budget")
            details = " ".join(f"{team} trades away {', '.join(assets)}" for team, assets in senders.items())
            trades.append({**common, "action_type": "TRADED", "details": details,
                           "assets_by_party_json": json.dumps(assets_by_owner),
                           "asset_types_json": json.dumps({o: sorted(t) for o, t in asset_types.items()}),
                           "pick_assets_json": json.dumps(pick_assets)})
        for row, cells in group:
            if view == "CLAIM_DROP" and row.get("transactionCode") == "LINEUP_CHANGE":
                continue  # Same-owner position changes, retained in the raw archive.
            scorer = row.get("scorer", {})
            pid = scorer.get("scorerId")
            if not pid:
                if view == "TRADE":
                    continue  # Pick/budget assets remain in the complete trade event.
                raise ValueError("Claim/drop has no player identity")
            trade_drop = view == "TRADE" and cells["to"].get("content") == "(Drop)"
            target = (cells["from"] if trade_drop else cells["to"]) if view == "TRADE" else cells["team"]
            owner = owners[target["teamId"]]
            action = ("DROPPED" if trade_drop else "TRADED") if view == "TRADE" else {"CLAIM": "CLAIMED", "DROP": "DROPPED"}[row["transactionCode"]]
            bid = cells.get("bid", {}).get("content", "").replace("$", "").replace(",", "")
            salary = float(bid) if bid else None
            transactions.append({**common, "player_id": pid, "player_name": names.get(pid, scorer["name"]),
                                 "team_name": target["content"], "owner_username": owner["username"],
                                 "owner_real_name": owner["real_name"], "action_type": action,
                                 "salary": salary, "details": details,
                                 "action_raw": f"{action} by {target['content']}"})
    return transactions, trades


def build_snapshot(refresh_root, config_path):
    refresh = Path(refresh_root)
    archive = refresh / "league_logs"
    coverage = read(archive / "coverage.json")
    cfg = yaml.safe_load(Path(config_path).read_text())
    seasons = {int(k): v for k, v in cfg["all_season_league_ids"].items()}
    if coverage["status"] != "complete" or {int(k) for k in coverage["seasons"]} != set(seasons):
        raise ValueError("Incomplete all-season archive")
    drafts = read(refresh / "data/draft_results.json")
    names = player_names(read(refresh / "raw_drafts/player_directory.json"))
    for s in drafts["seasons"]:
        for p in s["picks"]:
            if p["player_id"]:
                names.setdefault(p["player_id"], p["player_name"])
    config = Config(league_id=cfg["league_id"], season=max(seasons), all_season_league_ids=seasons,
                    data_root=cfg.get("data_root", "fantrax_data"), draft_results=str(refresh / "data/draft_results.json"))
    dirs = setup_run_dirs(Path(config.data_root))
    save_run_config(dirs, config)
    atomic_json(dirs.root / "log_coverage.json", coverage)
    all_tx, all_trades, owner_records = [], [], []
    teams_out, roster_out = [], []
    for year, league_id in sorted(seasons.items()):
        season_dir = archive / str(year)
        if coverage["seasons"][str(year)]["league_id"] != league_id:
            raise ValueError("Archive league mismatch")
        teams = read(season_dir / "teams.json")
        owners = {}
        for team in teams:
            owner = owner_from_team(team["name"])
            if owner["real_name"] == "Unknown":
                raise ValueError(f"Unresolved owner: {year} {team['name']}")
            owners[team["id"]] = owner
            owner_records.append({"username": owner["username"], "real_name": owner["real_name"],
                                  "season": year, "team_name": team["name"]})
        for view in ("CLAIM_DROP", "TRADE"):
            source = coverage["seasons"][str(year)]["views"][view]
            rows = []
            for page in range(1, source["pages"] + 1):
                rows.extend(read(season_dir / f"{view}_{page:03}.json")["responses"][0]["data"]["table"]["rows"])
            if len(rows) != source["rows"] or len({r["txSetId"] for r in rows}) != source["events"]:
                raise ValueError("Archive row/event counts changed")
            tx, trades = parse_log_rows(rows, year, view, owners, names)
            all_tx.extend(tx); all_trades.extend(trades)
        draft = next(s for s in drafts["seasons"] if s["year"] == year)
        for pick in draft["picks"]:
            if not pick["player_id"]:
                continue
            if not pick.get("picked_at_ms"):
                raise ValueError("Selected draft pick has no actual timestamp")
            timestamp = datetime.fromtimestamp(pick["picked_at_ms"] / 1000, ZoneInfo("America/New_York"))
            owner = owners[pick["team_id"]]
            all_tx.append({"date": timestamp.strftime("%b %d %Y"), "occurred_at": timestamp.isoformat(),
                           "event_id": f"{year}:draft:{pick['overall_pick']}", "source_season": year,
                           "player_id": pick["player_id"], "player_name": names[pick["player_id"]],
                           "team_name": pick["team_name"], "owner_username": owner["username"],
                           "owner_real_name": owner["real_name"], "action_type": "DRAFTED", "salary": None,
                           "details": f"Round {pick['round']}, Pick {pick['overall_pick']}",
                           "action_raw": f"Drafted by {pick['team_name']}"})
        if year == config.season:
            teams_out = [{"team_id": t["id"], "team_name": t["name"], "short_name": t.get("shortName", ""),
                          "owner_username": owners[t["id"]]["username"], "owner_real_name": owners[t["id"]]["real_name"]} for t in teams]
            for tid, roster in read(season_dir / "rosters.json")["rosters"].items():
                team = next(t for t in teams_out if t["team_id"] == tid)
                for p in roster.get("rosterItems", []):
                    roster_out.append({**team, "player_id": p["id"], "player_name": names[p["id"]],
                                       "position": p.get("position", ""), "roster_status": p.get("status", "")})
    all_tx.sort(key=lambda t: (t["occurred_at"], t["event_id"]))
    player_tx = defaultdict(list)
    for t in all_tx:
        player_tx[t["player_id"]].append(t)
    journeys = []
    for pid, tx in player_tx.items():
        journeys.extend(build_player_journeys(pid, tx[-1]["player_name"], tx))
    open_stints = {j["player_id"]: j for j in journeys if j["end_date"] is None}
    for p in roster_out:
        if open_stints.get(p["player_id"], {}).get("owner_real_name") != p["owner_real_name"]:
            raise ValueError(f"Current roster disagrees with reconstructed history for {p['player_id']}")
    roster_ids = {p["player_id"] for p in roster_out}
    unresolved_closures = [j for pid, j in open_stints.items() if pid not in roster_ids]
    atomic_json(dirs.root / "history_gaps.json", {"missing_closing_transaction": unresolved_closures,
                "note": "These players are not on today's roster. Their exit dates remain unknown; no date is invented."})
    collected = {"teams": teams_out, "players": roster_out, "transactions": all_tx, "journeys": journeys,
                 "errors": [], "collection_mode": "league_logs", "log_coverage": coverage,
                 "trade_event_count": len(all_trades),
                 "profile_count": 0, "profile_sources": {}}
    export_all(collected, dirs, logging.getLogger("export"))
    # Keep stable IDs/times, and pure pick/budget trades that have no player row.
    pd.DataFrame(all_tx).to_csv(dirs.output_dir / "transaction_history.csv", index=False)
    pd.DataFrame(all_trades).sort_values(["occurred_at", "event_id"]).to_csv(dirs.output_dir / "trade_events.csv", index=False)
    mapping = pd.read_csv(dirs.output_dir / "owner_team_mapping.csv")
    pd.DataFrame(owner_records).to_csv(dirs.output_dir / "season_teams.csv", index=False)
    pd.concat([mapping, pd.DataFrame(owner_records)]).drop_duplicates().to_csv(dirs.output_dir / "owner_team_mapping.csv", index=False)
    atomic_json(dirs.root / "source_archive.json", {"path": str(archive.resolve()), "drafts": str((refresh / "data/draft_results.json").resolve())})
    publish_run(dirs, config, collected)
    print(json.dumps({"run": str(dirs.root), "teams": len(teams_out), "rostered_players": len(roster_out),
                      "transactions": len(all_tx), "trade_events": len(all_trades), "players_with_history": len(player_tx),
                      "ownership_stints": len(journeys)}, indent=2))
    return dirs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-root", required=True)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    build_snapshot(args.refresh_root, args.config)
