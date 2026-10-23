"""Isolated offline browser fixture. No installer, systemd or real device commands."""
import os
os.environ['WERKZEUG_RUN_MAIN'] = 'false'
from pathlib import Path
import sys
import tempfile
import struct
import zlib
from flask import send_from_directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_scoreboard_qc import event, CFB, NFL
import app


def png(red, green, blue):
    """Small passive raster fixtures; never substitute for the user's logo."""
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    rows = b''.join(b'\x00' + bytes([red, green, blue, 255]) * 32 for _ in range(32))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 32, 32, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


with tempfile.TemporaryDirectory(prefix='scoreboard-browser-qc-') as directory:
    root = Path(directory)
    app.SETTINGS_FILE = str(root / 'settings.json')
    app.KIOSK_CONFIG_FILE = str(root / 'kiosk.json')
    app.KIOSKS_FILE = str(root / 'paired.json')
    app.SCORE_CACHE_FILE = str(root / 'score_cache.json')
    app.UPLOAD_FOLDER = str(root / 'uploads')
    app.SPECIALS_FOLDER = str(root / 'uploads/specials')
    app.RSS_LOGOS_FOLDER = str(root / 'uploads/rss_logos')
    Path(app.SPECIALS_FOLDER).mkdir(parents=True)
    Path(app.RSS_LOGOS_FOLDER).mkdir(parents=True)
    for name, color in [('logo.png', (0, 45, 32)), ('aggies.png', (80, 0, 0)),
                         ('alabama.png', (158, 27, 50)), ('texans.png', (3, 32, 47)), ('chiefs.png', (227, 24, 55))]:
        (Path(app.UPLOAD_FOLDER) / name).write_bytes(png(*color))
    original_static = app.app.view_functions['static']
    def fixture_static(filename):
        if filename.startswith('uploads/'):
            return send_from_directory(app.UPLOAD_FOLDER, filename[len('uploads/'):])
        return original_static(filename=filename)
    app.app.view_functions['static'] = fixture_static
    app.get_weather = lambda city: '72°F'
    college = [event(), event('next', 'pre', days=2)]
    professional = [event('nfl', home='HOU', away='KC', rank=99)]
    for live in [college[0], professional[0]]:
        home, away = live['competitions'][0]['competitors']
        home['linescores'] = [{'period': index, 'value': score} for index, score in enumerate([7, 10, 7], 1)]
        away['linescores'] = [{'period': index, 'value': score} for index, score in enumerate([7, 7, 7], 1)]
        away['records'] = [{'name': 'overall', 'summary': '4-2'}]
    for game in college:
        game['competitions'][0]['competitors'][0]['team']['logo'] = '/static/uploads/aggies.png'
        game['competitions'][0]['competitors'][1]['team']['logo'] = '/static/uploads/alabama.png'
    professional[0]['competitions'][0]['competitors'][0]['team']['logo'] = '/static/uploads/texans.png'
    professional[0]['competitions'][0]['competitors'][1]['team']['logo'] = '/static/uploads/chiefs.png'
    app._espn_cache['raw_events'] = {CFB: college, NFL: professional}
    app._espn_cache['ap_poll'] = {'ranks': {'245': 7}, 'season': college[0]['season']['year'],
                                'date': '2026-10-18T07:00Z', 'updated_at': college[0]['date']}
    app._team_colors_for_league = lambda path: {}
    app.save_settings({'port': 5002, 'leagues': [CFB, NFL], 'teams': [CFB + ':TA&M', NFL + ':HOU'],
                       'display_name': 'AGGIE GAMEDAY', 'color_mode': 'manual', 'slide_duration': 2, 'logo_slide_duration': 2,
                       'city': '', 'football_priority': True, 'cfb_coverage': 'favorites', 'scorecard_include_completed': True,
                       'specials': [{'uid': 'test1', 'type': 'text', 'title': 'First', 'enabled': True},
                                    {'uid': 'test2', 'type': 'text', 'title': 'Second', 'enabled': True}]})
    app.app.view_functions['wifi_status_api'] = lambda: app.jsonify({'connected': False})
    app.requests.get = lambda *args, **kwargs: (_ for _ in ()).throw(app.requests.ConnectionError('Offline QC fixture'))
    app.app.run(host='127.0.0.1', port=5002, debug=False)
