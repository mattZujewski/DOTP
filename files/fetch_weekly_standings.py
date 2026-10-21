"""Collect cumulative end-of-period standings from Fantrax, with validated caching.

Run from the repository root: python3 files/fetch_weekly_standings.py --seasons 2025 2026
Credentials and raw responses stay in ignored local files; only ranks/points are exported.
"""
import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path

import yaml
from collection_state import atomic_json
from fantrax_tracker_v4 import Config, FantraxAPI
from fetch_standings import parse_num

ROOT = Path(__file__).resolve().parents[1]


def parse_week(payload, period, owner_by_id, label):
    data = payload.get('responses', [{}])[0].get('data', {})
    selections = data.get('displayedSelections', {})
    expected = {'period': period, 'timeframeType': 'BY_PERIOD',
                'timeStartType': 'FROM_SEASON_START'}
    if any(selections.get(k) != v for k, v in expected.items()):
        raise ValueError('Fantrax did not honor the cumulative weekly selection')
    table = next((t for t in data.get('tableList', [])
                  if 'Stat Totals' in t.get('caption', '')), None)
    if not table:
        raise ValueError('Weekly standings table is missing')
    labels = [c.get('shortName', '').lower() for c in table['header']['cells']]
    points_column = labels.index('pts')
    points_table = next((t for t in data.get('tableList', [])
                         if 'Standings - Point Totals' in t.get('caption', '')), None)
    points_labels = [c.get('shortName', '').lower() for c in points_table['header']['cells']] if points_table else []
    points_rows = {r['fixedCells'][1]['teamId']: r for r in points_table['rows']} if points_table else {}
    rows = []
    for row in table['rows']:
        fixed = row['fixedCells']
        team_id = fixed[1]['teamId']
        rank = parse_num(fixed[0].get('content', ''))
        points = parse_num(row['cells'][points_column].get('content', ''))
        if team_id not in owner_by_id or rank is None or points is None:
            raise ValueError('Unrecognized team or missing weekly result')
        if not 1 <= rank <= len(owner_by_id) or not 0 <= points <= 120:
            raise ValueError('Weekly rank or points out of range')
        record = {'owner': owner_by_id[team_id], 'rank': rank, 'pts': points}
        stats = {}
        for key in ('r', 'hr', 'rbi', 'sb', 'obp', 'k', 'era', 'whip', 'svh3', 'w+qs'):
            if key in labels:
                cell = row['cells'][labels.index(key)]
                stats[key.replace('+', '')] = parse_num(str(cell.get('toolTip', cell.get('content', ''))))
        if stats:
            record['stats'] = stats
        if points_table:
            point_row = points_rows.get(team_id)
            if not point_row:
                raise ValueError('Missing team in category point totals')
            record['category_points'] = {}
            for key in ('r', 'hr', 'rbi', 'sb', 'obp', 'k', 'era', 'whip', 'svh3', 'w+qs'):
                value = parse_num(str(point_row['cells'][points_labels.index(key)].get('content', '')))
                if value is None or not 0 <= value <= len(owner_by_id):
                    raise ValueError('Missing or invalid category roto points')
                record['category_points'][key.replace('+', '')] = value
            if abs(sum(record['category_points'].values()) - points) > .001:
                raise ValueError('Category points do not reconcile to total roto points')
        rows.append(record)
    if len(rows) != len(owner_by_id) or len({r['owner'] for r in rows}) != len(rows):
        raise ValueError('Incomplete or duplicate weekly team coverage')
    # Fantrax echoes full-season displayedStart/EndDate even for weekly filters.
    # Use its actual period label rather than treating those dates as the week.
    return {'period': period, 'label': label, 'rows': sorted(rows, key=lambda r: r['rank'])}


def collect(seasons, refresh=False, offline=False):
    cfg = yaml.safe_load((ROOT / 'files/config.yaml').read_text())
    final = json.loads((ROOT / 'docs/data/standings.json').read_text())['season_standings']
    destination = ROOT / 'docs/data/weekly_standings.json'
    output = json.loads(destination.read_text()) if destination.exists() else {'seasons': {}}
    for year in seasons:
        league_id = cfg['all_season_league_ids'].get(year) or cfg['all_season_league_ids'][str(year)]
        raw = ROOT / f'files/fantrax_data/weekly_standings/{year}'
        raw.mkdir(parents=True, exist_ok=True)
        api = FantraxAPI(Config(league_id=league_id, jsessionid=cfg.get('jsessionid', ''),
                               extra_cookies=cfg.get('extra_cookies', {}), request_delay=1,
                               api_version=cfg.get('api_version', '187.3.6')), raw, logging.getLogger('weekly'))
        baseline = json.loads((raw / 'season.json').read_text()) if offline else api.internal_request([{'method': 'getStandings', 'data': {}}])
        if not offline:
            atomic_json(raw / 'season.json', baseline)
        data = baseline['responses'][0]['data']
        periods = sorted(data['displayedLists']['periods'], key=lambda p: p['object1'])
        current_period = data['displayedSelections']['period']
        expected_rows = [r for r in final if r['season'] == year]
        owner_by_id = {r['team_id']: r['owner_real_name'] for r in expected_rows}
        weeks = []
        for period in periods:
            number = period['object1']
            if number > current_period:
                continue
            cache = raw / f'week_{number:02}.json'
            if offline or (cache.exists() and not refresh and number < current_period):
                payload = json.loads(cache.read_text())
            else:
                payload = api.internal_request([{'method': 'getStandings', 'data': {
                    'period': number, 'timeframeType': 'BY_PERIOD',
                    'timeStartType': 'FROM_SEASON_START', 'view': 'REGULAR_SEASON'}}])
                atomic_json(cache, payload)
            weeks.append(parse_week(payload, number, owner_by_id, period['object2']))
            print(f'{year}: week {number}, {len(weeks[-1]["rows"])} teams', flush=True)
        if len(weeks) > 1 and all(w['rows'] == weeks[0]['rows'] for w in weeks):
            raise ValueError('Every week is identical; refusing to publish an unverified history')
        latest = {r['owner']: (r['rank'], r['pts']) for r in weeks[-1]['rows']}
        expected = {r['owner_real_name']: (r['rank'], r['pts']) for r in expected_rows}
        if latest != expected:
            raise ValueError('Latest week differs from the season snapshot; refresh season standings first')
        output['seasons'][str(year)] = {'weeks': weeks, 'fetched_at': output['seasons'].get(str(year), {}).get('fetched_at') if offline else datetime.now(timezone.utc).isoformat(),
            'basis': 'Cumulative from season start through each Fantrax scoring period'}
        atomic_json(destination, output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seasons', nargs='+', type=int, default=[2026])
    parser.add_argument('--offline', action='store_true', help='Rebuild the export only from cached responses')
    parser.add_argument('--refresh', action='store_true', help='Refetch cached historical weeks')
    args = parser.parse_args()
    collect(args.seasons, args.refresh, args.offline)
