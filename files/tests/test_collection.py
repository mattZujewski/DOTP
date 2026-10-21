"""Offline regressions for history preservation and collection publication."""
import csv
import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collection_state import ProfileCache, atomic_json, publish_run, validate_collection
from history_store import HistoryStore
from fantrax_tracker_v4 import (Config, FantraxAPI, collect_all, export_all, parse_transaction_table,
                                save_run_config, setup_run_dirs, main)
from build_dashboard import find_latest_run


def profile(name="test-player"):
    return {"responses": [{"data": {"miscData": {"urlName": name}, "sectionContent": {
        "TRANSACTIONS_FANTASY": {"tables": [{"rows": [{"cells": [
            {"content": "Feb 1 2026"}, {"content": "Claimed by <b>Top Gunnar</b>"},
            {"content": "Budget: $1.00"}]}]}]}}}}]}


class FakeAPI:
    def __init__(self):
        self.fetched = []
    def get_fantasy_teams(self):
        return [{"id": "t", "name": "Top Gunnar"}]
    def get_player_names(self):
        return {}
    def get_team_rosters_public(self):
        return {"rosters": {"t": {"teamName": "Top Gunnar", "rosterItems": [
            {"id": "p", "position": "OF", "status": "ACTIVE"}]}}}
    def get_player_profile(self, pid, save_as=None):
        self.fetched.append(pid)
        return profile(f"player-{pid}")


class CollectionTests(unittest.TestCase):
    def test_remember_me_cookie_without_jsessionid(self):
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp) / "config.json"
            config_path.write_text(json.dumps({"league_id": "league26", "api_version": "test-version",
                                               "extra_cookies": {"FX_RM": "test-remember-me"}}))
            def check_teams(api):
                self.assertEqual(api._cookies(), {"FX_RM": "test-remember-me"})
                self.assertEqual(api.config.api_version, "test-version")
                return [{"id": "t"}]
            with patch.dict("os.environ", {"FANTRAX_JSESSIONID": ""}), \
                 patch.object(sys, "argv", ["tracker", "--config", str(config_path), "--check-auth"]), \
                 patch.object(FantraxAPI, "get_fantasy_teams", check_teams):
                self.assertEqual(main(), 0)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.drafts = self.root / "drafts.json"
        atomic_json(self.drafts, {"seasons": [{"year": 2020, "league_id": "league20", "picks": [
            {"player_id": "former", "player_name": "Former Player", "team_id": "oldteam", "round": 1}]}]})
        self.config = Config(league_id="league26", jsessionid="test-only", data_root=str(self.root),
                             season=2026, all_season_league_ids={2020: "league20", 2026: "league26"},
                             request_delay=0, draft_results=str(self.drafts))
        self.log = logging.getLogger("tests")

    def collect(self, config=None, api=None):
        config = config or self.config
        dirs = setup_run_dirs(self.root)
        save_run_config(dirs, config)
        data = collect_all(api or FakeAPI(), dirs, config, self.log)
        export_all(data, dirs, self.log)
        return dirs, data

    def publish(self):
        dirs, data = self.collect()
        validate_collection(data, self.config)
        publish_run(dirs, self.config, data)
        return dirs, data

    def test_former_players_collected_but_not_added_to_roster(self):
        api = FakeAPI()
        dirs, data = self.collect(api=api)
        self.assertEqual(set(api.fetched), {"p", "former"})
        self.assertEqual([p["player_id"] for p in data["players"]], ["p"])
        self.assertEqual({t["player_id"] for t in data["transactions"]}, {"p", "former"})
        validate_collection(data, self.config)
        publish_run(dirs, self.config, data)
        self.assertEqual((self.root / "latest").resolve(), dirs.root)
        self.assertEqual(json.loads((dirs.input_dir / "config.json").read_text())["season"], 2026)
        self.assertNotIn("test-only", (dirs.input_dir / "config.json").read_text())

    def test_failed_run_cannot_replace_last_good_snapshot(self):
        previous, _ = self.publish()
        broken = FakeAPI()
        broken.get_player_profile = lambda *a, **kw: {"responses": []}
        self.config.refresh = True
        dirs, data = self.collect(api=broken)
        with self.assertRaisesRegex(ValueError, "profiles failed"):
            validate_collection(data, self.config)
        self.assertEqual((self.root / "latest").resolve(), previous.root)
        self.assertEqual(find_latest_run(str(self.root)), previous.output_dir)
        store = HistoryStore(self.root / "history.sqlite3")
        try:
            self.assertEqual(store.import_run(dirs.root)["status"], "skipped")
        finally:
            store.close()

    def test_historical_refresh_does_not_replace_current_roster(self):
        current, _ = self.publish()
        old = Config(**{**vars(self.config), "league_id": "league20", "season": 2020})
        dirs, data = self.collect(old)
        validate_collection(data, old)
        publish_run(dirs, old, data)
        self.assertEqual((self.root / "latest").resolve(), current.root)
        self.assertEqual((self.root / "latest_by_league/league20").resolve(), dirs.root)

    def test_historical_only_collection_cannot_masquerade_as_current(self):
        old = Config(**{**vars(self.config), "league_id": "league20", "season": 2020})
        dirs, data = self.collect(old)
        publish_run(dirs, old, data)
        self.assertFalse((self.root / "latest").exists())
        with self.assertRaises(SystemExit):
            find_latest_run(str(self.root))

    def test_date_only_source_row_is_rejected_instead_of_discarded(self):
        data = profile()
        rows = data["responses"][0]["data"]["sectionContent"]["TRANSACTIONS_FANTASY"]["tables"][0]["rows"]
        rows.append({"cells": [{"content": "Feb 1 2021"}]})
        with self.assertRaisesRegex(ValueError, "Malformed transaction row"):
            ProfileCache(self.root / "cache", "league26", 2026).write("p", data)

    def test_history_import_is_idempotent_and_preserves_evidence(self):
        dirs, _ = self.publish()
        store = HistoryStore(self.root / "history.sqlite3")
        try:
            before = store.report()["counts"]
            self.assertEqual(store.import_run(dirs.root)["status"], "unchanged")
            self.assertEqual(before, store.report()["counts"])
            another, _ = self.publish()
            report = store.report()["counts"]
            self.assertEqual(report["transactions"], before["transactions"])
            self.assertEqual(report["transaction_sources"], before["transaction_sources"] * 2)
            self.assertEqual(report["snapshots"], 2)
        finally:
            store.close()

    def test_database_failure_keeps_last_good_pointer(self):
        current, _ = self.publish()
        dirs, data = self.collect()
        with patch.object(HistoryStore, "import_run", side_effect=RuntimeError("disk unavailable")):
            with self.assertRaises(RuntimeError):
                publish_run(dirs, self.config, data)
        self.assertEqual((self.root / "latest").resolve(), current.root)
        self.assertEqual(json.loads((dirs.root / "manifest.json").read_text())["status"], "storage_failed")

    def test_database_open_failure_does_not_leave_a_success_manifest(self):
        current, _ = self.publish()
        dirs, data = self.collect()
        with patch.object(HistoryStore, "__init__", side_effect=RuntimeError("cannot open database")):
            with self.assertRaises(RuntimeError):
                publish_run(dirs, self.config, data)
        self.assertEqual((self.root / "latest").resolve(), current.root)
        self.assertEqual(json.loads((dirs.root / "manifest.json").read_text())["status"], "storage_failed")

    def test_large_roster_decrease_requires_explicit_override(self):
        _, data = self.publish()
        manifest = self.root / "latest_by_league/league26/manifest.json"
        saved = json.loads(manifest.read_text()); saved["roster_count"] = 12
        atomic_json(manifest, saved)
        with self.assertRaisesRegex(ValueError, "Roster shrank"):
            validate_collection(data, self.config)
        self.config.allow_roster_shrink = True
        validate_collection(data, self.config)

    def test_missing_roster_team_is_rejected(self):
        api = FakeAPI(); api.get_team_rosters_public = lambda: {"rosters": {}}
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.collect(api=api)

    def test_invalid_transaction_date_is_not_silently_dropped(self):
        data = profile()
        data["responses"][0]["data"]["sectionContent"]["TRANSACTIONS_FANTASY"]["tables"][0]["rows"][0]["cells"][0]["content"] = "bad date"
        with self.assertRaises(ValueError):
            parse_transaction_table(data)

    def test_cache_scope_expiration_and_corruption(self):
        cache = ProfileCache(self.root / "cache", "league26", 2026)
        cache.write("p", profile())
        self.assertIsNotNone(cache.read("p"))
        self.assertIsNone(ProfileCache(self.root / "cache", "league20", 2020).read("p"))
        self.assertIsNone(ProfileCache(self.root / "cache", "league26", 2025).read("p"))
        self.assertIsNone(ProfileCache(self.root / "cache", "league26", 2026, 0).read("p"))
        item = json.loads(cache.path("p").read_text())
        item["fetched_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        atomic_json(cache.path("p"), item)
        self.assertIsNone(cache.read("p"))
        cache.path("p").write_text("{broken")
        self.assertIsNone(cache.read("p"))
        with self.assertRaises(ValueError):
            cache.write("p", {"responses": []})

    def test_legacy_cache_is_never_reused(self):
        atomic_json(self.root / "cache/player_p.json", profile())
        self.assertIsNone(ProfileCache(self.root / "cache", "league26", 2026).read("p"))

    def test_legacy_run_import_marks_scope_and_infers_season_from_team_ids(self):
        dirs, data = self.collect()
        (dirs.root / "manifest.json").unlink()
        (dirs.input_dir / "config.json").unlink()
        drafts = {"seasons": [{"year": 2020, "league_id": "league20", "picks": [{"team_id": "t"}]}]}
        store = HistoryStore(self.root / "history.sqlite3")
        try:
            result = store.import_run(dirs.root, drafts)
            self.assertEqual(result["season"], 2020)
            self.assertTrue(any("after the source season" in w for w in result["warnings"]))
            self.assertEqual(store.report()["seasons"][0]["validated_snapshots"], 0)
        finally:
            store.close()

    def test_run_directories_never_overwrite_each_other(self):
        self.assertNotEqual(setup_run_dirs(self.root).root, setup_run_dirs(self.root).root)

    def test_retry_only_transient_responses(self):
        from unittest.mock import Mock
        api = FantraxAPI(self.config, self.root, self.log)
        transient = Mock(status_code=503, headers={})
        good = Mock(status_code=200)
        session = Mock(); session.request.side_effect = [transient, good]
        with patch.object(api, "_session_for_thread", return_value=session), patch("fantrax_tracker_v4.time.sleep"):
            self.assertIs(api._request("GET", "https://example.invalid"), good)
        self.assertEqual(session.request.call_count, 2)

    def test_profile_throttle_inside_http_success_is_retried(self):
        api = FantraxAPI(self.config, self.root, self.log)
        warning = {"responses": [{"pageError": {"code": "WARNING",
                    "text": "You're viewing player profiles too quickly. Please slow down."}}]}
        good = profile()
        with patch.object(api, "internal_request", side_effect=[warning, good]) as request, \
             patch("fantrax_tracker_v4.time.sleep") as sleep:
            self.assertIs(api.get_player_profile("p"), good)
            sleep.assert_any_call(60)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(api._profile_delay, 2)

    def test_current_team_renames_resolve_in_all_collectors(self):
        from fantrax_tracker_v4 import get_owner_from_team_name
        from fetch_standings import owner_from_team
        from fetch_draft_results import TEAM_TO_OWNER, normalize_team_name
        for name in ("Otto’s Army", "Otto's Army"):
            self.assertEqual(get_owner_from_team_name(name)["real_name"], "Liam Burns")
            self.assertEqual(owner_from_team(name)["real_name"], "Liam Burns")
            self.assertEqual(TEAM_TO_OWNER[normalize_team_name(name).lower()], "Liam Burns")

    def test_standings_follow_column_labels_when_reordered(self):
        from fetch_standings import fetch_season_standings, STAT_COLS
        from unittest.mock import Mock
        values = dict(zip(STAT_COLS, [90, 1900, 5500, 1400, 800, 250, 810, 90, .340,
                                     1300, 1500, 3.7, 1.2, 110, 190]))
        labels = list(reversed(STAT_COLS))
        table = {"caption": "Standings - Stat Totals", "header": {"cells": [
            {"shortName": "W+QS" if key == "wqs" else key.upper()} for key in labels]},
            "rows": [{"fixedCells": [{"content": "1"}, {"content": "Miller Time", "teamId": "t"}],
                      "cells": [{"content": str(values[key])} for key in labels]}]}
        response = Mock()
        response.json.return_value = {"responses": [{"data": {"tableList": [table]}}]}
        with patch("fetch_standings.requests.post", return_value=response):
            rows = fetch_season_standings("league26", 2026, "", "fake", delay=0)
        for key, value in values.items():
            self.assertEqual(rows[0][key], value)


if __name__ == "__main__":
    unittest.main()
