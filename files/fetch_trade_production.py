"""Read Fantrax Full Fantasy Team production; export conservative post-trade returns.
Run: python3 files/fetch_trade_production.py --season 2026 [--offline] [--refresh]
Credentials and raw responses stay under ignored local paths.
"""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo
import yaml
from collection_state import atomic_json
from fantrax_tracker_v4 import Config, FantraxAPI
from fetch_standings import parse_num

ROOT = Path(__file__).resolve().parents[1]
COUNTS = ('r', 'hr', 'rbi', 'sb', 'k', 'svh3', 'wqs')
GROUPS = {'hitting': ('r', 'hr', 'rbi', 'sb'), 'pitching': ('k', 'svh3', 'wqs')}


def source_date(ms):
    return datetime.fromtimestamp(ms / 1000, ZoneInfo('America/New_York')).date().isoformat()


def parse_roster(payload, team_id, bounds=None):
    data = payload.get('responses', [{}])[0].get('data', {})
    selection = data.get('displayedSelections', {})
    if selection.get('displayedStatsType') != '3' or selection.get('displayedFantasyTeamId') != team_id:
        raise ValueError('Wrong fantasy production mode or team')
    if bounds and (selection.get('displayedSeasonOrProjection', {}).get('timeframeTypeCode') != 'BY_DATE' or
                   tuple(source_date(selection[k]) for k in ('displayedStartDate', 'displayedEndDate')) != tuple(bounds)):
        raise ValueError('Fantrax did not honor the requested dates')
    players = {}
    for table in data.get('tables', []):
        keys = [c.get('shortName', '').lower().replace('+', '') for c in table['header']['cells']]
        group = 'pitching' if 'ip' in keys else 'hitting'
        for row in table.get('rows', []):
            scorer = row.get('scorer', {})
            pid = scorer.get('scorerId')
            if not pid:
                continue
            stats = {key: parse_num(str(cell.get('content', ''))) for key, cell in zip(keys, row['cells']) if key != 'age'}
            # IP is baseball notation, never decimal innings. Preserve the source string.
            if 'ip' in keys:
                stats['ip'] = row['cells'][keys.index('ip')].get('content')
            player = players.setdefault(pid, {'player_id': pid, 'player_name': scorer.get('name', ''), 'groups': {}})
            if group in player['groups']:
                raise ValueError('Duplicate player/stat group')
            player['groups'][group] = stats
    if not players:
        raise ValueError('No player production returned')
    return data, players


def trade_window(stint, trade_date, season_start, season_end):
    if stint.get('end_date_unknown') or (not stint.get('is_current') and not stint.get('end_date')):
        return None
    start = max(date.fromisoformat(trade_date) + timedelta(days=1), date.fromisoformat(season_start))
    end = date.fromisoformat(season_end)
    if stint.get('end_date'):
        end = min(end, date.fromisoformat(stint['end_date']) - timedelta(days=1))
    return start.isoformat(), end.isoformat()


def grade_sides(events, benchmarks):
    eligible = []
    for event in events.values():
        for side in event['sides']:
            totals = {key: 0 for key in COUNTS}
            complete = bool(side['players'])
            for player in side['players']:
                if player['status'] != 'available':
                    complete = False
                    continue
                for group, stats in player['groups'].items():
                    for key in GROUPS[group]:
                        if stats.get(key) is None:
                            complete = False
                        else:
                            totals[key] += stats[key]
            side['totals'] = totals
            side['available'] = sum(p['status'] == 'available' for p in side['players'])
            side['complete'] = complete
            side['score'] = round(sum(totals[k] / benchmarks[k] for k in COUNTS), 6) if complete else None
            side['grade'] = None
            if complete:
                eligible.append(side)
    for side in eligible:
        # Competition percentile: tied scores receive identical grades; zero gets D.
        percentile = sum(s['score'] < side['score'] for s in eligible) / max(len(eligible) - 1, 1)
        side['percentile'] = round(percentile * 100)
        side['grade'] = ('A' if percentile >= .75 else 'B' if percentile >= .5 else 'C' if percentile >= .25 else 'D') if side['score'] > 0 else 'D'
    return len(eligible)


def collect(year=2026, offline=False, refresh=False):
    cfg = yaml.safe_load((ROOT / 'files/config.yaml').read_text())
    league_id = cfg['all_season_league_ids'].get(year) or cfg['all_season_league_ids'][str(year)]
    raw = ROOT / f'files/fantrax_data/trade_production/{year}'
    raw.mkdir(parents=True, exist_ok=True)
    api = FantraxAPI(Config(league_id=league_id, extra_cookies=cfg.get('extra_cookies', {}), jsessionid=cfg.get('jsessionid', ''), request_delay=1,
                           api_version=cfg.get('api_version', '187.3.6')), raw, logging.getLogger('production'))
    standings = [r for r in json.loads((ROOT / 'docs/data/standings.json').read_text())['season_standings'] if r['season'] == year]
    team_ids = {r['owner_real_name']: r['team_id'] for r in standings}
    trades = [t for t in json.loads((ROOT / 'docs/data/trades.json').read_text())['trade_events'] if t['year'] == year]
    stints = json.loads((ROOT / 'docs/data/journeys.json').read_text())['stints']
    def request(team_id, start=None, end=None):
        name = f'{team_id}_{start or "season"}_{end or ""}.json'
        path = raw / name
        if path.exists() and (offline or not refresh):
            return json.loads(path.read_text())
        if offline:
            raise ValueError('Missing cached production response: ' + name)
        params = {'teamId': team_id, 'statsType': '3'}
        if start:
            params.update(seasonOrProjection=date_code, timeframeTypeCode='BY_DATE', startDate=start, endDate=end)
        payload = api.internal_request([{'method': 'getTeamRosterInfo', 'data': params}])
        parse_roster(payload, team_id, (start, end) if start else None)
        atomic_json(path, payload)
        return payload
    audit = []
    for standing in standings:
        owner = standing['owner_real_name']
        data, players = parse_roster(request(team_ids[owner]), team_ids[owner])
        selected = data['displayedSelections']['displayedSeasonOrProjection']
        if str(year) not in selected['name'] or selected['timeframeTypeCode'] != 'YEAR_TO_DATE':
            raise ValueError('Wrong source season')
        date_code = selected['code'].replace('YEAR_TO_DATE', 'BY_DATE')
        season_start, season_end = source_date(selected['startDate']), source_date(selected['endDate'])
        totals = {key: sum(p['groups'][g][key] for p in players.values() for g in p['groups'] if key in GROUPS[g] and p['groups'][g].get(key) is not None) for key in COUNTS}
        expected = {k: standing[k] for k in COUNTS}
        audit.append({'owner': owner, 'players': len(players), 'actual': totals, 'expected': expected,
                      'differences': {k: round(totals[k] - expected[k], 4) for k in COUNTS}})
        print(f'{year} season: {owner}: {len(players)} players; differences {audit[-1]["differences"]}', flush=True)
    benchmarks = {k: median(s[k] for s in standings) for k in COUNTS}
    events = {}
    for t in trades:
        event = {'date': t['date_iso'], 'sides': []}
        for owner, assets in t['assets_by_party'].items():
            side = {'owner': owner, 'players': []}
            for name in assets['received']:
                record = {'player_name': name, 'status': 'unavailable', 'reason': 'No unique matching acquisition', 'groups': {}}
                matches = [s for s in stints if s['player_name'] == name and s['owner_real_name'] == owner and s['start_date'] == t['date_iso'] and s['acquisition_type'] == 'TRADED']
                if len(matches) == 1:
                    stint = matches[0]
                    record['player_id'] = stint['player_id']
                    window = trade_window(stint, t['date_iso'], season_start, season_end)
                    record['reason'] = 'Unknown ownership end date'
                    if window:
                        record['start'], record['end'] = window
                        if window[0] > window[1]:
                            record['reason'] = 'No full scoring day in this ownership window'
                        else:
                            try:
                                _, players = parse_roster(request(team_ids[owner], *window), team_ids[owner], window)
                                source = players.get(stint['player_id'])
                                if source:
                                    record.update(status='available', reason=None, groups=source['groups'])
                                else:
                                    record['reason'] = 'Player absent from the Fantrax response; not assumed zero'
                            except (ValueError, KeyError) as exc:
                                record['reason'] = 'Unverified source response'
                side['players'].append(record)
            event['sides'].append(side)
        events[t['event_id']] = event
        print(f'{year} trade {len(events)}/{len(trades)}: {t["date_iso"]}', flush=True)
    rated = grade_sides(events, benchmarks)
    output = {'season': year, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'stats_mode': 'Full Fantasy Team',
              'basis': 'Recorded fantasy-team production during full days after acquisition and before departure, capped at season end. Trade and exit days excluded to avoid ambiguous timing. Reacquisitions are separate windows.',
              'grading': 'A/B/C/D quartiles of received counting-production scores among fully covered player-receiving sides in this season. Score sums each of R, HR, RBI, SB, K, SVH3, W+QS divided by the league median team season total for that category. Zero production is D. No missing values are imputed. Rates are shown per player but not graded. Picks, budget, outgoing cost and future seasons are not valued. Longer ownership windows have more opportunity.',
              'benchmarks': benchmarks, 'audit': audit, 'rated_sides': rated, 'events': events}
    atomic_json(ROOT / f'docs/data/trade_production_{year}.json', output)
    print(f'Exported {len(events)} trades, {rated} rated receiving sides', flush=True)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, default=2026)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    collect(args.season, args.offline, args.refresh)
