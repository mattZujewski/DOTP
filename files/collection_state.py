"""Validated, season-scoped caches and atomic pointers to successful collections."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_profile(data):
    """Reject login/error pages and truncated responses before they enter the cache."""
    if not isinstance(data, dict) or not isinstance(data.get("responses"), list):
        raise ValueError("Player profile response has no responses list")
    for response in data["responses"]:
        section = response.get("data", {}).get("sectionContent", {}).get("TRANSACTIONS_FANTASY")
        if isinstance(section, dict) and isinstance(section.get("tables"), list) and section["tables"]:
            for table in section["tables"]:
                if not isinstance(table.get("rows"), list):
                    raise ValueError("Transaction table has no rows list")
                for row in table["rows"]:
                    if not row.get("highlight") and (not isinstance(row.get("cells"), list) or len(row["cells"]) < 2):
                        raise ValueError("Malformed transaction row")
            return
    raise ValueError("Player profile has no fantasy transaction table")


class ProfileCache:
    def __init__(self, root, league_id, season, max_age_hours=24):
        if max_age_hours < 0:
            raise ValueError("Cache age must be nonnegative")
        # League IDs come from configuration: avoid treating them as paths.
        if not league_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in league_id):
            raise ValueError("Invalid league ID")
        self.league_id, self.season = league_id, season
        self.root = Path(root) / league_id / str(season if season is not None else "unknown")
        self.max_age_hours = max_age_hours

    def path(self, player_id):
        if not player_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in player_id):
            raise ValueError("Invalid player ID")
        return self.root / f"player_{player_id}.json"

    def read(self, player_id):
        try:
            item = json.loads(self.path(player_id).read_text())
            if item.get("schema_version") != 1 or item.get("league_id") != self.league_id or item.get("season") != self.season or item.get("player_id") != player_id:
                return None
            fetched_at = datetime.fromisoformat(item["fetched_at"])
            age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
            if not 0 <= age < self.max_age_hours * 3600:
                return None
            validate_profile(item["payload"])
            return item
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def write(self, player_id, payload):
        validate_profile(payload)
        item = {"schema_version": 1, "league_id": self.league_id, "season": self.season,
                "player_id": player_id, "fetched_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        atomic_json(self.path(player_id), item)
        return item


def atomic_pointer(path, target):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A failed link replacement leaves the previous successful pointer intact.
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    os.unlink(name)
    try:
        os.symlink(os.path.relpath(target, path.parent), name)
        os.replace(name, path)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def publish_run(dirs, config, collected):
    """Import first; advertise only successful, durable output. Historical runs never replace current."""
    from history_store import HistoryStore, utc_now

    validate_collection(collected, config)
    current_season = max(config.all_season_league_ids, default=config.season or 0)
    manifest = {"schema_version": 1, "status": "complete", "season": config.season,
                "current_season": current_season,
                "league_id": config.league_id, "completed_at": utc_now(),
                "roster_count": len(collected["players"]),
                "profile_count": collected["profile_count"],
                "profile_sources": collected["profile_sources"],
                "coverage": "Known-player inventory; not proof of exhaustive historical coverage."}
    if collected.get("collection_mode") == "league_logs":
        manifest.update({"collection_mode": "league_logs", "log_coverage": collected["log_coverage"],
                         "trade_event_count": collected["trade_event_count"],
                         "coverage": "All pages of executed, non-deleted claim/drop and trade logs for configured seasons, plus actual draft selections. Position changes are not ownership events."})
    atomic_json(dirs.root / "manifest.json", manifest)
    store = None
    try:
        store = HistoryStore(Path(config.data_root) / "history.sqlite3")
        store.import_run(dirs.root)
    except Exception:
        manifest["status"] = "storage_failed"
        atomic_json(dirs.root / "manifest.json", manifest)
        raise
    finally:
        if store is not None:
            store.close()
    atomic_pointer(Path(config.data_root) / "latest_by_league" / config.league_id, dirs.root)
    if config.season == current_season or (not config.all_season_league_ids and config.season is None):
        atomic_pointer(Path(config.data_root) / "latest", dirs.root)


def validate_collection(collected, config):
    if not collected["teams"] or not collected["players"]:
        raise ValueError("Collection has no teams or rostered players")
    if collected["errors"]:
        raise ValueError(f"{len(collected['errors'])} player profiles failed; previous snapshot retained")
    if collected.get("collection_mode") == "league_logs":
        coverage = collected.get("log_coverage", {})
        seasons = coverage.get("seasons", {})
        if coverage.get("status") != "complete" or {int(s) for s in seasons} != set(config.all_season_league_ids):
            raise ValueError("Incomplete league log coverage")
        for year, league in config.all_season_league_ids.items():
            if seasons[str(year)].get("league_id") != league or set(seasons[str(year)].get("views", {})) != {"CLAIM_DROP", "TRADE"}:
                raise ValueError("Missing league or transaction view")
        expected_trades = sum(s["views"]["TRADE"]["events"] for s in seasons.values())
        if collected.get("trade_event_count") != expected_trades:
            raise ValueError("Incomplete trade event coverage")
    if len(collected.get("profile_sources", {})) != collected.get("profile_count"):
        raise ValueError("Not all requested profiles have a recorded result")
    ids = [p["player_id"] for p in collected["players"]]
    if len(ids) != len(set(ids)):
        raise ValueError("A player appears more than once on the roster")
    previous = Path(config.data_root) / "latest_by_league" / config.league_id / "manifest.json"
    count = None
    if previous.exists():
        count = json.loads(previous.read_text())["roster_count"]
    else:
        # The first upgraded run can use a legacy snapshot imported with a verified
        # season identity as a sanity-check baseline, without certifying its history.
        database = Path(config.data_root) / "history.sqlite3"
        if database.exists():
            from history_store import HistoryStore
            store = HistoryStore(database)
            try:
                row = store.db.execute("SELECT roster_count FROM snapshots WHERE league_id=? ORDER BY captured_at DESC LIMIT 1", (config.league_id,)).fetchone()
                if row:
                    count = row[0]
            finally:
                store.close()
    if count is not None and len(ids) < count * 0.8 and not config.allow_roster_shrink:
        raise ValueError("Roster shrank by more than 20%; inspect output before using --allow-roster-shrink")
    if any(t["action_type"] == "UNKNOWN" for t in collected["transactions"]):
        raise ValueError("Unrecognized transaction action; inspect saved responses before publishing")
