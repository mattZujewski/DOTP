import unittest
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_log_snapshot import parse_log_rows
from build_dashboard import build_trade_events, build_journeys_json
from fetch_standings import build_standings_json, STAT_COLS
from player_directory import player_names
from structured_trades import build_pick_results, classify_assets


def cell(key, content, **other):
    return {"key": key, "content": content, **other}


class BulkRefreshTests(unittest.TestCase):
    def setUp(self):
        self.owners = {"a": {"username": "a", "real_name": "Owner A"},
                       "b": {"username": "b", "real_name": "Owner B"}}
        self.common = {"executed": True, "deleted": False, "txSetId": "event1"}
        self.date = cell("date", "Mon Sep 21, 2026, 4:00AM", rowspan=2)

    def test_claim_and_drop_inherit_group_team_and_date(self):
        rows = [{**self.common, "transactionCode": "CLAIM", "scorer": {"scorerId": "p", "name": "Player P"},
                 "cells": [cell("team", "Team A", teamId="a", rowspan=2), self.date, cell("bid", "1.50")]},
                {**self.common, "transactionCode": "DROP", "scorer": {"scorerId": "q", "name": "Player Q"},
                 "cells": [cell("bid", "")]}]
        tx, events = parse_log_rows(rows, 2026, "CLAIM_DROP", self.owners, {})
        self.assertEqual([r["action_type"] for r in tx], ["CLAIMED", "DROPPED"])
        self.assertEqual(tx[1]["team_name"], "Team A")
        self.assertEqual(tx[0]["occurred_at"], tx[1]["occurred_at"])
        self.assertEqual(tx[0]["salary"], 1.5)
        self.assertEqual(events, [])

    def test_pick_and_budget_trade_kept_without_fake_players(self):
        cells = [cell("from", "Team A", teamId="a"), cell("to", "Team B", teamId="b")]
        rows = [{**self.common, "scorer": {}, "cells": cells + [self.date],
                 "draftPickDisplayParts": {"year": "<b>2027</b> Draft Pick", "roundInfo": "Round <b>2</b> (Team A)"}},
                {**self.common, "scorer": {}, "cells": [cell("from", "Team B", teamId="b"), cell("to", "Team A", teamId="a")],
                 "budgetAmountTradeObj": {"budget": "$2.00"}}]
        tx, events = parse_log_rows(rows, 2026, "TRADE", self.owners, {})
        self.assertEqual(tx, [])
        self.assertEqual(len(events), 1)
        self.assertIn("2027 Draft Pick, Round 2 (Team A)", events[0]["details"])
        self.assertIn("Team B trades away Budget: $2.00", events[0]["details"])

    def test_distinct_trade_ids_are_not_merged_by_date_and_details(self):
        frame = pd.DataFrame([{"event_id": key, "date": "Sep 21 2026", "details": "Same terms", "action_type": "TRADED"}
                              for key in ("one", "two", "one")])
        self.assertEqual(len(build_trade_events(frame)), 2)

    def test_innings_total_carries_outs(self):
        rows = [{**dict.fromkeys(STAT_COLS, 1), "season": year, "rank": 1, "owner_real_name": "Owner A",
                 "owner_username": "a", "ip": 10.2} for year in (2025, 2026)]
        self.assertEqual(build_standings_json(rows)["alltime_standings"][0]["ip"], 21.1)

    def test_canonical_player_names_preserve_suffix_and_punctuation(self):
        names = player_names({"p": {"fantraxId": "p", "name": "Witt Jr., Bobby"},
                              "q": {"fantraxId": "q", "name": "Puk, A.J."}})
        self.assertEqual(names, {"p": "Bobby Witt Jr.", "q": "A.J. Puk"})

    def test_missing_closing_event_does_not_override_live_roster(self):
        journeys = pd.DataFrame([{"player_id": "p", "player_name": "Player P", "team_name": "Team A",
                                  "owner_real_name": "Owner A", "start_date": "Jan 01 2020",
                                  "end_date": None, "acquisition_type": "DRAFTED", "acquisition_salary": None}])
        roster = pd.DataFrame(columns=["player_id", "owner_real_name"])
        result = build_journeys_json(journeys, {}, roster)
        self.assertIsNone(result["player_index"]["p"]["current_owner"])
        self.assertTrue(result["stints"][0]["end_date_unknown"])
        self.assertIsNone(result["stints"][0]["end_date"])

    def test_trade_roster_space_drop_is_not_a_received_asset(self):
        rows = [{**self.common, "scorer": {"scorerId": "p", "name": "Player P"},
                 "cells": [cell("from", "Team A", teamId="a"), cell("to", "Team B", teamId="b"), self.date]},
                {**self.common, "scorer": {"scorerId": "q", "name": "Player Q"},
                 "cells": [cell("from", "Team B", teamId="b"), cell("to", "(Drop)")]}]
        tx, events = parse_log_rows(rows, 2026, "TRADE", self.owners, {})
        self.assertEqual(tx[1]["action_type"], "DROPPED")
        self.assertEqual(tx[1]["owner_real_name"], "Owner B")
        self.assertNotIn("Player Q", events[0]["details"])

    def test_draft_match_requires_exact_slot_not_unique_recipient(self):
        pick = {"draft_year": 2026, "round": 2, "pick_in_round": 3, "overall_pick": 15,
                "owner_name": "Owner B", "team_name": "Team B", "player_id": "p", "player_name": "Player P"}
        asset = {"pick_year": 2026, "pick_round": 2, "pick_in_round": None,
                 "original_holder": "Team A", "sending_owner": "Owner A", "receiving_owner": "Owner B"}
        trade = {"event_id": "one", "parties": ["Owner A", "Owner B"], "date_iso": "2025-06-01",
                 "trade_type_label": "Pick-for-FAAB", "pick_assets": [asset]}
        drafts = {"seasons": [{"year": 2026, "picks": [pick]}]}
        self.assertEqual(build_pick_results([trade], drafts, {})["pick_results"][0]["result_status"], "ambiguous")
        asset["pick_in_round"] = 3
        result = build_pick_results([trade], drafts, {})["pick_results"][0]
        self.assertEqual(result["result_status"], "matched")
        self.assertEqual(result["drafted_player"]["player_id"], "p")
        self.assertFalse(result["drafted_player"]["still_rostered"])

    def test_pure_pick_trade_is_not_classified_as_player_trade(self):
        label, subtype = classify_assets({"A": ["pick"], "B": ["pick"]},
                                         {"A": {"sent": [], "received": []}, "B": {"sent": [], "received": []}})
        self.assertEqual(label, "Pick-for-Pick")
        self.assertEqual(subtype, "")


if __name__ == "__main__":
    unittest.main()
