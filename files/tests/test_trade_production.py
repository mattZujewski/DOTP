import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fetch_trade_production import parse_roster, trade_window, grade_sides, COUNTS, ROOT

class ProductionTests(unittest.TestCase):
    def fixture(self):
        return {'responses':[{'data':{'displayedSelections':{'displayedStatsType':'3','displayedFantasyTeamId':'t','displayedSeasonOrProjection':{'timeframeTypeCode':'BY_DATE'},'displayedStartDate':1786248000000,'displayedEndDate':1790481600000},'tables':[{'header':{'cells':[{'shortName':k} for k in ['IP','K','SVH3','W+QS','GP']]},'rows':[{'scorer':{'scorerId':'p','name':'Player'},'statusId':'7','cells':[{'content':v} for v in ['7.1','7','1.5','—','2']]}]}]}}]}
    def test_departed_player_and_missing_value_preserved(self):
        _, p=parse_roster(self.fixture(),'t',('2026-08-09','2026-09-27'))
        self.assertEqual(p['p']['groups']['pitching']['ip'],'7.1')
        self.assertEqual(p['p']['groups']['pitching']['svh3'],1.5)
        self.assertIsNone(p['p']['groups']['pitching']['wqs'])
    def test_reject_wrong_source_mode_team_or_dates(self):
        for key,value in [('displayedStatsType','1'),('displayedFantasyTeamId','other'),('displayedEndDate',1786248000000)]:
            p=self.fixture();p['responses'][0]['data']['displayedSelections'][key]=value
            with self.assertRaises(ValueError):parse_roster(p,'t',('2026-08-09','2026-09-27'))
    def test_reacquisition_boundary_and_season_cap(self):
        self.assertEqual(trade_window({'is_current':False,'end_date':'2026-08-20'},'2026-08-08','2026-03-25','2026-09-27'),('2026-08-09','2026-08-19'))
        self.assertEqual(trade_window({'is_current':True},'2026-01-01','2026-03-25','2026-09-27'),('2026-03-25','2026-09-27'))
        self.assertIsNone(trade_window({'end_date_unknown':True},'2026-08-08','2026-03-25','2026-09-27'))
    def test_missing_is_not_zero_and_ties_share_grade(self):
        def side(value):return {'players':[{'status':'available','groups':{'hitting':{'r':value,'hr':value,'rbi':value,'sb':value}}}]}
        sides=[side(0),side(10),side(10),side(30),side(None),{'players':[]},{'players':[{'status':'unavailable'}]}]
        count=grade_sides({'a':{'sides':sides}},{k:100 for k in COUNTS})
        self.assertEqual(count,4);self.assertEqual(sides[0]['grade'],'D')
        self.assertEqual(sides[1]['grade'],sides[2]['grade']);self.assertEqual(sides[3]['grade'],'A')
        for s in sides[4:]:self.assertIsNone(s['grade']);self.assertIsNone(s['score'])
    def test_export_references_actual_source_records(self):
        path=ROOT/'docs/data/trade_production_2026.json'
        if not path.exists():self.skipTest('Collection not yet completed')
        d=json.loads(path.read_text());trades={t['event_id']:t for t in json.loads((ROOT/'docs/data/trades.json').read_text())['trade_events']}
        self.assertEqual(len(d['events']),92)
        self.assertEqual(len(d['audit']),12)
        matt=next(a for a in d['audit'] if a['owner']=='Matthew Zujewski')
        self.assertEqual(matt['actual']['hr'],249);self.assertEqual(matt['actual']['k'],1349)
        self.assertTrue(all(v==0 for v in matt['differences'].values()))
        teams={r['owner_real_name']:r['team_id'] for r in json.loads((ROOT/'docs/data/standings.json').read_text())['season_standings'] if r['season']==2026}
        for tid,e in d['events'].items():
            for s in e['sides']:
                self.assertEqual([p['player_name'] for p in s['players']],trades[tid]['assets_by_party'][s['owner']]['received'])
                for p in s['players']:
                    if p['status']!='available':continue
                    raw=ROOT/f'files/fantrax_data/trade_production/2026/{teams[s["owner"]]}_{p["start"]}_{p["end"]}.json'
                    if not raw.exists():continue # Raw responses are intentionally not versioned.
                    _,players=parse_roster(json.loads(raw.read_text()),teams[s['owner']],(p['start'],p['end']))
                    self.assertEqual(p['groups'],players[p['player_id']]['groups'])
                    self.assertGreater(p['start'],e['date'])
        self.assertEqual(d['rated_sides'],sum(bool(s['grade']) for e in d['events'].values() for s in e['sides']))

if __name__=='__main__':unittest.main()
