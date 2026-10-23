#!/usr/bin/env python3
"""Offline cloud benchmark, not a Raspberry Pi or browser performance test.

Run with the application's Python environment:
    python scripts/benchmark_live.py --output docs/benchmarks-live-widgets.json

Runtime modules, metadata, generated session key and settings are isolated in a
temporary directory. HTTP access is forbidden and background workers disabled.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gc
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LEAGUES = ('football/nfl', 'football/college-football', 'basketball/nba', 'baseball/mlb')


def fixture(path, index, start):
    """Synthetic current ESPN-shaped data, including explicit known runner state."""
    identifier = 800000000 + index
    home_id, away_id = str(100000 + index * 2), str(100001 + index * 2)
    home_abbr, away_abbr = 'H' + str(index), 'A' + str(index)
    baseball = path == 'baseball/mlb'
    basketball = path == 'basketball/nba'
    home_periods = [0, 1, 0, 1] if baseball else [25, 23, 20] if basketball else [7, 7, 0]
    away_periods = [0, 1, 0, 0, 1] if baseball else [20, 22, 18] if basketball else [0, 7, 7]
    status = {'period': 5 if baseball else 3, 'displayClock': '0:00' if baseball else '4:20',
              'type': {'state': 'in', 'name': 'STATUS_IN_PROGRESS', 'completed': False,
                       'description': 'In Progress',
                       'detail': 'Top 5th' if baseball else '4:20 - 3rd',
                       'shortDetail': 'Top 5th' if baseball else '4:20 - 3rd'}}
    competitors = []
    for side, team_id, abbreviation, periods in (
            ('home', home_id, home_abbr, home_periods), ('away', away_id, away_abbr, away_periods)):
        competitor = {'homeAway': side, 'team': {'id': team_id, 'abbreviation': abbreviation,
                      'displayName': 'Synthetic ' + abbreviation, 'logo': '/synthetic/' + abbreviation + '.png'},
                      'score': str(sum(periods)), 'records': [{'name': 'overall', 'summary': '8-2'}],
                      'linescores': [{'value': value} for value in periods]}
        if baseball:
            competitor['statistics'] = [{'name': 'hits', 'displayValue': '5'},
                                        {'name': 'errors', 'displayValue': '0'}]
        competitors.append(competitor)
    situation = ({'onFirst': False, 'onSecond': True, 'onThird': False, 'outs': 1} if baseball else
                 {'possession': home_id, 'possessionText': away_abbr + ' 34',
                  'down': 3, 'distance': 7, 'downDistanceText': '3rd & 7 at ' + away_abbr + ' 34'})
    return {'id': str(identifier), 'date': start, 'season': {'year': 2026},
            'status': status, 'competitions': [{'status': deepcopy(status),
                'competitors': competitors, 'situation': situation}]}


def benchmark():
    os.environ['WERKZEUG_RUN_MAIN'] = 'false'
    with tempfile.TemporaryDirectory(prefix='scoreboard-live-benchmark-') as directory:
        runtime = Path(directory)
        for name in ('app.py', 'score_details.py', 'version.txt'):
            shutil.copy2(ROOT / name, runtime / name)
        (runtime / 'static/data').mkdir(parents=True)
        shutil.copy2(ROOT / 'static/data/football-teams-2026.json',
                     runtime / 'static/data/football-teams-2026.json')
        sys.path.insert(0, str(runtime))
        specification = importlib.util.spec_from_file_location('_scoreboard_live_benchmark', runtime / 'app.py')
        scoreboard = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = scoreboard
        with patch('requests.get', side_effect=AssertionError('Benchmark attempted real HTTP')) as network:
            specification.loader.exec_module(scoreboard)
            start = datetime.now(timezone.utc).isoformat()
            raw_events = {path: [fixture(path, league_index * 24 + index, start)
                                for index in range(24)] for league_index, path in enumerate(LEAGUES)}
            settings = scoreboard.get_settings()
            settings.update(city='', color_mode='manual', football_priority=False, cfb_coverage='favorites', scorecard_include_completed=True,
                            football_display='both', leagues=list(LEAGUES),
                            teams=[path + ':' + competitor['team']['abbreviation']
                                   for path, events in raw_events.items() for event in events
                                   for competitor in event['competitions'][0]['competitors']])
            (runtime / 'settings.json').write_text(json.dumps(settings), encoding='utf-8')
            scoreboard._espn_cache = {'raw_events': raw_events, 'updated_at': start}
            scoreboard._cache_errors = {}
            scoreboard._score_event_received_at = {
                event['id']: (time.monotonic(), scoreboard._live_event_signature(event))
                for events in raw_events.values() for event in events}

            def build():
                return scoreboard._build_data_response(settings['leagues'], settings['teams'], {},
                                                       settings['timezone'], settings)

            def render():
                return json.dumps(build(), separators=(',', ':'), ensure_ascii=False).encode('utf-8')

            sample = build()
            cards = sample['teams']
            counts = {'favorite_cards': len(cards),
                      'period_tables': sum(card['period_scores'] is not None for card in cards),
                      'football_trackers': sum(card['football_tracker'] is not None for card in cards),
                      'baseball_trackers': sum(card['baseball_tracker'] is not None for card in cards)}
            assert counts == {'favorite_cards': 96, 'period_tables': 96,
                              'football_trackers': 48, 'baseball_trackers': 24}, counts
            first = scoreboard._score_details.get(LEAGUES[0], raw_events[LEAGUES[0]][0],
                raw_events[LEAGUES[0]][0]['competitions'][0]['competitors'][0],
                raw_events[LEAGUES[0]][0]['competitions'][0]['competitors'][1])
            second = scoreboard._score_details.get(LEAGUES[0], raw_events[LEAGUES[0]][0],
                raw_events[LEAGUES[0]][0]['competitions'][0]['competitors'][0],
                raw_events[LEAGUES[0]][0]['competitions'][0]['competitors'][1])
            assert first is not second and first['football_tracker'] is not second['football_tracker']
            del sample, cards, first, second
            for _ in range(20):
                render()
            gc.collect()
            rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            timings = []
            payload_bytes = 0
            for _ in range(300):
                before = time.perf_counter_ns()
                body = render()
                timings.append((time.perf_counter_ns() - before) / 1_000_000)
                payload_bytes = len(body)
            del body
            gc.collect()
            tracemalloc.start()
            heap_before = tracemalloc.take_snapshot()
            for _ in range(50):
                render()
            gc.collect()
            heap_after = tracemalloc.take_snapshot()
            retained = sum(item.size_diff for item in heap_after.compare_to(heap_before, 'filename'))
            _, heap_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Expiry must not silently benchmark the cheaper no-widget path.
            assert all(scoreboard._live_detail_ttl(path, event) > 0
                       for path, events in raw_events.items() for event in events)
            assert network.call_count == 0
    ordered = sorted(timings)
    return {
        'environment': {'python': platform.python_version(), 'architecture': platform.machine(),
                        'platform': platform.system(), 'hardware': 'cloud development host; not Raspberry Pi'},
        'method': {'command': 'python scripts/benchmark_live.py --output docs/benchmarks-live-widgets.json',
                   'script': 'scripts/benchmark_live.py', 'measurement':
                   '_build_data_response plus compact UTF-8 JSON serialization; perf_counter_ns timings',
                   'isolation': 'Temporary runtime copy and settings; HTTP forbidden; workers disabled',
                   'freshness': 'Synthetic successful-fetch monotonic stamps and actual event signatures; expiry asserted',
                   'p95': 'Nearest-rank percentile, sorted sample at ceil(0.95 * 300) - 1',
                   'heap': 'tracemalloc retained allocation delta over 50 extra renders after gc; RSS is process high-water'},
        'scenario': {'synthetic_games': 96, 'leagues': 4, **counts,
                     'external_requests': 0, 'measured_iterations': 300,
                     'warmup_iterations': 20, 'retention_iterations': 50, 'payload_bytes': payload_bytes},
        'results': {'median_render_json_ms': round(statistics.median(timings), 3),
                    'p95_render_json_ms': round(ordered[math.ceil(.95 * len(ordered)) - 1], 3),
                    'max_render_json_ms': round(max(timings), 3),
                    'rss_high_water_before_kib': rss_before, 'rss_high_water_after_kib': rss_after,
                    'retained_python_heap_delta_after_50_renders_bytes': retained,
                    'traced_heap_peak_bytes': heap_peak},
        'limits': ['Synthetic cached data; excludes network latency, Chromium, image loading and SD writes.',
                   'Different host load/fixtures/JSON serialization can affect comparison with previous benchmarks.',
                   'Short benchmark is not proof against leaks or a 24/7 soak test.',
                   'No Raspberry Pi CPU/RAM/temperature measurements were made.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    result = json.dumps(benchmark(), indent=2) + '\n'
    if arguments.output:
        arguments.output.write_text(result, encoding='utf-8')
    else:
        print(result, end='')
