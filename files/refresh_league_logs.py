"""Fetch complete paginated executed claim/drop and trade logs for every season.

Read-only Fantrax endpoints. Raw pages and pagination counts are retained locally.
"""
import argparse
import json
import logging
from pathlib import Path
import time
import yaml

from collection_state import atomic_json
from fantrax_tracker_v4 import Config, FantraxAPI


def fetch_archive(config_path, destination):
    cfg = yaml.safe_load(Path(config_path).read_text())
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    report = {"status": "collecting", "seasons": {}, "started_at": __import__("datetime").datetime.now().isoformat()}
    atomic_json(root / "coverage.json", report)
    for year, league_id in sorted(cfg["all_season_league_ids"].items()):
        year = int(year)
        raw = root / str(year)
        raw.mkdir(exist_ok=True)
        config = Config(league_id=league_id, jsessionid=cfg.get("jsessionid", ""),
                        extra_cookies=cfg.get("extra_cookies", {}), request_delay=2,
                        api_version=cfg.get("api_version", "187.3.6"))
        api = FantraxAPI(config, raw, logging.getLogger("logs"))
        teams = api.get_fantasy_teams()
        if len(teams) != 12:
            raise ValueError(f"Expected 12 teams in {year}")
        atomic_json(raw / "teams.json", teams)
        rosters = api.get_team_rosters_public()
        if set(rosters.get("rosters", {})) != {t["id"] for t in teams}:
            raise ValueError(f"Incomplete roster coverage in {year}")
        atomic_json(raw / "rosters.json", rosters)
        report["seasons"][str(year)] = {"league_id": league_id, "views": {}}
        for view in ("CLAIM_DROP", "TRADE"):
            ids = set()
            total = None
            page = 1
            page_count = 1
            rows_count = 0
            while page <= page_count:
                data = api.internal_request([{"method": "getTransactionDetailsHistory", "data": {
                    "leagueId": league_id, "maxResultsPerPage": "250", "executedOnly": True,
                    "includeDeleted": False, "view": view, "pageNumber": str(page)}}])
                atomic_json(raw / f"{view}_{page:03}.json", data)
                response = data.get("responses", [{}])[0].get("data", {})
                pagination = response.get("paginatedResultSet", {})
                if not pagination or pagination.get("pageNumber") != page:
                    raise ValueError(f"Invalid pagination for {year} {view} page {page}")
                if total is None:
                    total = pagination["totalNumResults"]
                    page_count = max(1, pagination["totalNumPages"])
                elif pagination["totalNumResults"] != total or max(1, pagination["totalNumPages"]) != page_count:
                    raise ValueError("Transaction log changed during collection; retry the archive")
                rows = response.get("table", {}).get("rows", [])
                page_ids = {r["txSetId"] for r in rows}
                if ids & page_ids:
                    raise ValueError("Transaction group repeated across pages")
                if any(not r.get("executed") or r.get("deleted") for r in rows):
                    raise ValueError("Unexpected unexecuted/deleted transaction")
                ids.update(page_ids)
                rows_count += len(rows)
                page += 1
            if len(ids) != total:
                raise ValueError(f"Incomplete {year} {view}: {len(ids)} of {total} transactions")
            report["seasons"][str(year)]["views"][view] = {"pages": page_count, "events": total, "rows": rows_count}
            print(f"{year} {view}: {total} transaction groups, {rows_count} assets, {page_count} pages", flush=True)
            atomic_json(root / "coverage.json", report)
        time.sleep(2)
    report["status"] = "complete"
    report["completed_at"] = __import__("datetime").datetime.now().isoformat()
    atomic_json(root / "coverage.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    fetch_archive(args.config, args.out)
