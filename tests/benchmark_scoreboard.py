"""Offline backend benchmark. Results measure this machine, not Raspberry Pi hardware."""
import argparse
from copy import deepcopy
import gc
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
import tempfile
import time
import tracemalloc
os.environ['WERKZEUG_RUN_MAIN'] = 'false'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from test_scoreboard_qc import event


def run(iterations):
    with tempfile.TemporaryDirectory(prefix='scoreboard-bench-') as directory:
        app.SETTINGS_FILE = str(Path(directory)/'settings.json')
        app.KIOSK_CONFIG_FILE = str(Path(directory)/'kiosk.json')
        app.get_weather = lambda city: '--'
        app._team_colors_for_league = lambda path: {}
        app.requests.get = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Benchmark is offline'))
        paths = ['football/college-football', 'football/nfl', 'basketball/nba', 'baseball/mlb']
        app._espn_cache['raw_events'] = {path: [event(f'{path}-{i}', home='TA&M' if path.endswith('college-football') else 'HOU',
                                                            away=f'AWAY{i}', rank=7 if path.endswith('college-football') else 99)
                                                    for i in range(24)] for path in paths}
        for path, events in app._espn_cache['raw_events'].items():
            for game in events:
                home, away = game['competitions'][0]['competitors']
                for competitor, scores in ((home, [7, 10, 7, 0]), (away, [7, 7, 7, 0])):
                    if path == 'baseball/mlb':
                        scores = [scores[0], scores[1], scores[2]] + [0] * 6
                        competitor['statistics'] = [{'name': 'hits', 'displayValue': '30'}, {'name': 'errors', 'displayValue': '0'}]
                    competitor['linescores'] = [{'period': index, 'value': score} for index, score in enumerate(scores, 1)]
                    competitor['records'] = [{'name': 'overall', 'summary': '101-61' if path == 'baseball/mlb' else '5-1'}]
        settings = app.get_settings()
        settings.update(football_priority=False, color_mode='manual', city='', leagues=paths,
                        teams=[f'{path}:TA&M' if path.endswith('college-football') else f'{path}:HOU' for path in paths])
        def render():
            data = app._build_data_response(paths, settings['teams'], {}, 'America/Chicago', settings)
            assert len(data['teams']) == 96
            assert all(card['period_scores'] for card in data['teams'])
            return json.dumps(data)
        for _ in range(20): render()
        gc.collect()
        rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        durations = []
        for _ in range(iterations):
            start = time.perf_counter(); output = render(); durations.append((time.perf_counter()-start)*1000)
        gc.collect()
        rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        tracemalloc.start()
        for _ in range(10): render()
        gc.collect(); heap_before = tracemalloc.get_traced_memory()[0]
        for _ in range(50): render()
        gc.collect(); heap_after, heap_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        ordered = sorted(durations)
        return {'environment': {'python': platform.python_version(), 'architecture': platform.machine(),
                                'platform': platform.system(), 'hardware': 'cloud development host; not Raspberry Pi'},
                'scenario': {'synthetic_games':96,'leagues':4,'favorite_cards':96,'external_requests':0,
                             'period_tables':96,
                             'measured_iterations':iterations,'warmup_iterations':20,'payload_bytes':len(output.encode())},
                'results': {'median_render_json_ms':round(statistics.median(durations),3),
                            'p95_render_json_ms':round(ordered[int(.95*(len(ordered)-1))],3),
                            'max_render_json_ms':round(max(durations),3),
                            'rss_high_water_before_kib':rss_before,'rss_high_water_after_kib':rss_after,
                            'retained_python_heap_delta_after_50_renders_bytes':heap_after-heap_before,
                            'traced_heap_peak_bytes':heap_peak},
                'limits':['Synthetic cached data; does not include network latency, Chromium or SD writes.',
                          'Short benchmark is not a leak proof or a 24/7 soak test.',
                          'No Pi CPU/RAM/temperature measurements were made.']}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--iterations',type=int,default=300); parser.add_argument('--output')
    arguments=parser.parse_args()
    if arguments.iterations < 1: parser.error('iterations must be positive')
    result=run(arguments.iterations)
    rendered=json.dumps(result,indent=2)
    if arguments.output: Path(arguments.output).write_text(rendered+'\n')
    print(rendered)
