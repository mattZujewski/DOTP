"""Reject misleading weekly exports and check the published history."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fetch_weekly_standings import parse_week

ROOT = Path(__file__).resolve().parents[2]

class WeeklyStandingsTests(unittest.TestCase):
    def payload(self):
        return {'responses': [{'data': {
            'displayedSelections': {'period': 1, 'timeframeType': 'BY_PERIOD', 'timeStartType': 'FROM_SEASON_START'},
            'tableList': [{'caption': 'Standings - Stat Totals',
                'header': {'cells': [{'shortName': 'Pts'}]},
                'rows': [{'fixedCells': [{'content': '1'}, {'teamId': 'a'}], 'cells': [{'content': '80.5'}]},
                         {'fixedCells': [{'content': '2'}, {'teamId': 'b'}], 'cells': [{'content': '75'}]}]}]
        }}]}

    def test_parses_points_and_stable_team_ids(self):
        week = parse_week(self.payload(), 1, {'a': 'Owner A', 'b': 'Owner B'}, '1 (Mar 25 - Mar 29)')
        self.assertEqual(week['rows'][0], {'owner': 'Owner A', 'rank': 1, 'pts': 80.5})
        self.assertEqual(week['label'], '1 (Mar 25 - Mar 29)')

    def test_rejects_ignored_period_or_non_cumulative_filter(self):
        for key, value in [('period', 27), ('timeframeType', 'YEAR_TO_DATE'), ('timeStartType', 'PERIOD_ONLY')]:
            with self.subTest(key=key):
                payload = self.payload()
                payload['responses'][0]['data']['displayedSelections'][key] = value
                with self.assertRaises(ValueError):
                    parse_week(payload, 1, {'a': 'Owner A', 'b': 'Owner B'}, 'Week one')

    def test_category_precision_and_missing_values(self):
        payload = self.payload()
        table = payload['responses'][0]['data']['tableList'][0]
        table['header']['cells'] += [{'shortName': 'ERA'}, {'shortName': 'HR'}]
        for row in table['rows']:
            row['cells'] += [{'content': '3.50', 'toolTip': '3.5042'}, {'content': '-'}]
        week = parse_week(payload, 1, {'a': 'Owner A', 'b': 'Owner B'}, 'Week one')
        self.assertEqual(week['rows'][0]['stats']['era'], 3.5042)
        self.assertIsNone(week['rows'][0]['stats']['hr'])

    def test_source_category_points_keep_ties_and_reconcile(self):
        payload = self.payload()
        keys = ['R', 'HR', 'RBI', 'SB', 'OBP', 'K', 'ERA', 'WHIP', 'SVH3', 'W+QS']
        table = {'caption': 'Standings - Point Totals',
                 'header': {'cells': [{'shortName': k} for k in ['Pts'] + keys]},
                 'rows': [
                     {'fixedCells': [{'content': '1'}, {'teamId': 'a'}],
                      'cells': [{'content': str(v)} for v in [15.5, 2, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5]]},
                     {'fixedCells': [{'content': '2'}, {'teamId': 'b'}],
                      'cells': [{'content': str(v)} for v in [14.5, 1, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5]]}]}
        payload['responses'][0]['data']['tableList'][0]['rows'][0]['cells'][0]['content'] = '15.5'
        payload['responses'][0]['data']['tableList'][0]['rows'][1]['cells'][0]['content'] = '14.5'
        payload['responses'][0]['data']['tableList'].append(table)
        result = parse_week(payload, 1, {'a': 'Owner A', 'b': 'Owner B'}, 'Week one')
        self.assertEqual(result['rows'][0]['category_points']['hr'], 1.5)
        self.assertEqual(sum(result['rows'][0]['category_points'].values()), 15.5)
        table['rows'][0]['cells'][1]['content'] = '1'
        with self.assertRaisesRegex(ValueError, 'reconcile'):
            parse_week(payload, 1, {'a': 'Owner A', 'b': 'Owner B'}, 'Week one')

    def test_rejects_duplicate_or_unknown_teams(self):
        for team_id in ('a', 'unknown'):
            payload = self.payload()
            payload['responses'][0]['data']['tableList'][0]['rows'][1]['fixedCells'][1]['teamId'] = team_id
            with self.assertRaises(ValueError):
                parse_week(payload, 1, {'a': 'Owner A', 'b': 'Owner B'}, 'Week one')

    def test_export_is_complete_varied_and_matches_season_results(self):
        exported = json.loads((ROOT / 'docs/data/weekly_standings.json').read_text())['seasons']
        final = json.loads((ROOT / 'docs/data/standings.json').read_text())['season_standings']
        for year, season in exported.items():
            weeks = season['weeks']
            self.assertEqual([w['period'] for w in weeks], list(range(1, len(weeks)+1)))
            for week in weeks:
                self.assertEqual(len(week['rows']), 12)
                self.assertEqual(len({r['owner'] for r in week['rows']}), 12)
            for week in weeks:
                for row in week['rows']:
                    self.assertEqual(len(row['category_points']), 10)
                    self.assertAlmostEqual(sum(row['category_points'].values()), row['pts'])
            self.assertNotEqual(weeks[0]['rows'], weeks[-1]['rows'])
            self.assertEqual({r['owner']: (r['rank'], r['pts']) for r in weeks[-1]['rows']},
                             {r['owner_real_name']: (r['rank'], r['pts']) for r in final if r['season'] == int(year)})

if __name__ == '__main__':
    unittest.main()
