"""Append-only local history and player discovery for the Fantrax collector.

Import existing snapshots without changing them:
    python history_store.py --data-root fantrax_data --draft-results ../docs/data/draft_results.json

Legacy observations are evidence, not a certified transaction ledger. In particular,
the old shared player cache could mix league contexts. Keep that distinction in SQL
and reports until the records have been reconciled against fresh sources.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def date_iso(value):
    for fmt in ("%b %d %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    return None


class HistoryStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY, source_path TEXT NOT NULL, season INTEGER,
                league_id TEXT, captured_at TEXT, imported_at TEXT NOT NULL,
                quality TEXT NOT NULL, warnings_json TEXT NOT NULL,
                roster_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS players (
                player_id TEXT PRIMARY KEY, player_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS roster_observations (
                snapshot_id TEXT REFERENCES snapshots(id), player_id TEXT REFERENCES players(player_id),
                row_json TEXT NOT NULL, PRIMARY KEY(snapshot_id, player_id)
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY, player_id TEXT REFERENCES players(player_id),
                date_iso TEXT, action_type TEXT NOT NULL, row_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transaction_sources (
                transaction_id TEXT REFERENCES transactions(id),
                snapshot_id TEXT REFERENCES snapshots(id), row_number INTEGER,
                row_json TEXT NOT NULL, PRIMARY KEY(snapshot_id, row_number)
            );
            CREATE INDEX IF NOT EXISTS transaction_player_date ON transactions(player_id, date_iso);
            CREATE TABLE IF NOT EXISTS draft_observations (
                id TEXT PRIMARY KEY, player_id TEXT REFERENCES players(player_id),
                season INTEGER, league_id TEXT, source_path TEXT, row_json TEXT NOT NULL
            );
        """)

    def close(self):
        self.db.close()

    def _player(self, row):
        pid = str(row.get("player_id", "")).strip()
        if not pid or pid.lower().startswith("unknown"):
            return None
        name = str(row.get("player_name") or pid).strip()
        # Preserve the first useful name; every source's original name stays in row_json.
        self.db.execute("""INSERT INTO players VALUES (?, ?) ON CONFLICT(player_id)
            DO UPDATE SET player_name=excluded.player_name
            WHERE players.player_name=players.player_id""", (pid, name))
        return pid

    def import_drafts(self, path):
        data = json.loads(Path(path).read_text())
        with self.db:
            for season in data.get("seasons", []):
                for row in season.get("picks", []):
                    pid = self._player(row)
                    if pid:
                        key = digest([season["year"], season.get("league_id"), row])
                        self.db.execute("INSERT OR IGNORE INTO draft_observations VALUES (?, ?, ?, ?, ?, ?)",
                                        (key, pid, season["year"], season.get("league_id"),
                                         str(Path(path).resolve()), json.dumps(row)))
        return data

    def import_run(self, run, draft_data=None):
        run = Path(run)
        output = run / "output"
        names = ("teams", "current_rosters", "transaction_history", "player_journeys", "owner_team_mapping")
        if not all((output / f"{name}.csv").exists() for name in names):
            return {"run": run.name, "status": "skipped", "reason": "missing output files"}
        tables = {name: read_csv(output / f"{name}.csv") for name in names}
        teams, rosters, txns = (tables[n] for n in names[:3])
        if not teams or not rosters:
            return {"run": run.name, "status": "skipped", "reason": "empty teams or roster"}
        manifest_path = run / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if manifest and manifest.get("status") != "complete":
            return {"run": run.name, "status": "skipped", "reason": "run did not pass validation"}
        config_path = run / "input" / "config.json"
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        season = manifest.get("season") or config.get("season")
        league = manifest.get("league_id") or config.get("league_id")
        warnings = []
        if not manifest:
            warnings.append("Legacy shared-cache scope and profile freshness are unverified.")
        if (output / "errors.csv").exists() and read_csv(output / "errors.csv"):
            warnings.append("Source run recorded collection errors; observations may be incomplete.")
        # Exact team ID sets supply stronger season evidence than renamed team labels.
        team_ids = {r["team_id"] for r in teams}
        matches = [s for s in (draft_data or {}).get("seasons", [])
                   if team_ids == {p["team_id"] for p in s.get("picks", [])}]
        if len(matches) == 1:
            matched = matches[0]
            if (season and int(season) != matched["year"]) or (league and league != matched.get("league_id")):
                raise ValueError(f"Conflicting season identity for {run.name}")
            season, league = matched["year"], matched.get("league_id")
        if not season:
            warnings.append("Season identity could not be established.")
        future = sum(bool(date_iso(r.get("date"))) and bool(season) and
                     int(date_iso(r["date"])[:4]) > int(season) for r in txns)
        if future:
            warnings.append(f"{future} transaction rows occur after the source season; inspect scope.")
        captured = manifest.get("completed_at") or config.get("start_time")
        if not captured:
            # Legacy directory timestamps were UTC, despite other old metadata using local time.
            try:
                captured = datetime.strptime(run.name, "run_%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                warnings.append("Capture time is unknown.")
        snapshot_id = digest([run.name, tables, manifest, season, league])
        with self.db:
            if self.db.execute("SELECT 1 FROM snapshots WHERE id=?", (snapshot_id,)).fetchone():
                return {"run": run.name, "status": "unchanged"}
            self.db.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (snapshot_id, str(run.resolve()), season, league, captured, utc_now(),
                             "validated_collection" if manifest else "legacy_unverified",
                             json.dumps(warnings), len(rosters)))
            for row in rosters:
                pid = self._player(row)
                if pid:
                    self.db.execute("INSERT INTO roster_observations VALUES (?, ?, ?)",
                                    (snapshot_id, pid, json.dumps(row)))
            for number, row in enumerate(txns, start=2):
                pid = self._player(row)
                if not pid:
                    raise ValueError(f"Missing player ID at {run.name} transaction row {number}")
                normalized = {k: str(row.get(k) or "").replace("\u2019", "'").strip()
                              for k in ("player_id", "date", "action_type", "team_name", "salary", "details")}
                normalized["date"] = date_iso(row.get("date")) or normalized["date"]
                if row.get("event_id"):
                    normalized["event_id"] = row["event_id"]
                key = digest(normalized)
                self.db.execute("INSERT OR IGNORE INTO transactions VALUES (?, ?, ?, ?, ?)",
                                (key, pid, date_iso(row.get("date")), row.get("action_type", "UNKNOWN"), json.dumps(row)))
                self.db.execute("INSERT INTO transaction_sources VALUES (?, ?, ?, ?)",
                                (key, snapshot_id, number, json.dumps(row)))
        return {"run": run.name, "status": "imported", "season": season, "warnings": warnings}

    def known_players(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM players ORDER BY player_id")]

    def report(self):
        counts = {table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("snapshots", "players", "transactions", "transaction_sources", "draft_observations")}
        seasons = [dict(r) for r in self.db.execute("""SELECT season, COUNT(*) snapshots,
            SUM(quality='validated_collection') validated_snapshots FROM snapshots GROUP BY season ORDER BY season""")]
        no_history = self.db.execute("""SELECT COUNT(*) FROM players p WHERE NOT EXISTS
            (SELECT 1 FROM transactions t WHERE t.player_id=p.player_id)""").fetchone()[0]
        variants = self.db.execute("""SELECT COUNT(*) FROM (SELECT player_id,date_iso,action_type
            FROM transactions GROUP BY player_id,date_iso,action_type HAVING COUNT(*) > 1)""").fetchone()[0]
        return {"generated_at": utc_now(), "counts": counts, "seasons": seasons,
                "players_without_transactions": no_history, "same_day_action_groups_to_reconcile": variants,
                "warnings": [dict(r) for r in self.db.execute("SELECT source_path, warnings_json FROM snapshots WHERE warnings_json != '[]'")],
                "coverage": "Observed records only; legacy cache scope and same-day variants require reconciliation. Transaction counts are not certified league totals."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path(__file__).parent / "fantrax_data")
    parser.add_argument("--draft-results", type=Path, default=Path(__file__).parent.parent / "docs/data/draft_results.json")
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    store = HistoryStore(args.database or args.data_root / "history.sqlite3")
    try:
        drafts = store.import_drafts(args.draft_results) if args.draft_results.exists() else {}
        outcomes = [store.import_run(run, drafts) for run in sorted(args.data_root.glob("run_*")) if run.is_dir()]
        report = store.report()
        report["import_outcomes"] = outcomes
        report_path = args.data_root / "history_report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k not in ("warnings", "import_outcomes")}, indent=2))
        print(f"Full report: {report_path}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
