"""Offline regression checks: no Pi access and no real sports requests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['WERKZEUG_RUN_MAIN'] = 'false'
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as scoreboard

CFB = 'football/college-football'
NFL = 'football/nfl'


def event(event_id='1', state='in', home='TA&M', away='ALA', rank=7, days=0):
    return {'id': event_id, 'date': (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
            'season': {'year': datetime.now(timezone.utc).year},
            'status': {'type': {'state': state, 'shortDetail': 'Q3 10:30' if state == 'in' else state}},
            'competitions': [{'competitors': [
                {'homeAway': 'home', 'score': '24', 'curatedRank': {'current': rank},
                 'records': [{'summary': '5-1'}], 'team': {'id': '245' if home == 'TA&M' else '9999',
                 'abbreviation': home, 'logo': '/static/uploads/logo.png'}},
                {'homeAway': 'away', 'score': '21', 'team': {'id': '333' if away == 'ALA' else '9998',
                 'abbreviation': away, 'logo': '/static/uploads/logo.png'}}]}]}


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in {
            'SETTINGS_FILE': str(Path(self.tmp.name) / 'settings.json'),
            'KIOSK_CONFIG_FILE': str(Path(self.tmp.name) / 'kiosk.json'),
            'UPLOAD_FOLDER': self.tmp.name,
            '_espn_cache': {'raw_events': {}, 'updated_at': None, 'ap_poll': {
                'ranks': {'245': 7}, 'season': datetime.now(timezone.utc).year,
                'date': '2026-10-18T07:00Z', 'updated_at': datetime.now(timezone.utc).isoformat()}},
            '_ap_poll_request': {'retry_at': float('inf'), 'failures': 0},
            '_score_requests': {}, '_cache_errors': {}, '_requested_leagues': {}, '_last_refresh_attempt': 0,
            '_kiosk_last_data': None, '_kiosk_server_unreachable': False,
            '_weather_retry_at': 0, '_weather_city': None, 'WEATHER_CACHE': [None],
        }.items():
            patcher = patch.object(scoreboard, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        scoreboard.save_settings({'football_priority': False, 'leagues': [CFB], 'city': '',
                                  'color_mode': 'manual', 'teams': [CFB + ':TA&M']})
        self.client = scoreboard.app.test_client()
        with self.client.session_transaction() as session:
            session['user'] = 'admin'
        # Any accidental network call is an explicit test failure.
        patcher = patch.object(scoreboard.requests, 'get', side_effect=AssertionError('Unexpected network request'))
        self.network = patcher.start()
        self.addCleanup(patcher.stop)

    def test_live_upcoming_final_rankings_and_favorites(self):
        scoreboard._espn_cache['raw_events'][CFB] = [event('live'), event('upcoming', 'pre', days=2), event('final', 'post')]
        data = self.client.get('/api/data').get_json()
        self.assertEqual(len(data['teams']), 3)
        self.assertEqual([t['color_state'] for t in data['teams']], ['live', 'pre', 'final'])
        self.assertTrue(data['teams'][0]['home_is_fav'])
        self.assertEqual(data['teams'][0]['home_rank'], 7)
        self.assertEqual(data['teams'][1]['home_record'], '5-1')
        self.assertEqual(data['teams'][2]['winner'], 'home')
        self.assertEqual(len(data['ticker_parts'][0]['games']), 2)
        self.assertEqual(data['ticker_parts'][0]['games'][0]['event_id'], 'live')
        self.assertEqual(data['ticker_parts'][0]['games'][0]['league_path'], CFB)

    def test_football_priority_preserves_other_favorites(self):
        scoreboard.save_settings({'football_priority': True, 'leagues': ['basketball/nba'],
                                 'teams': ['basketball/nba:LAL']})
        scoreboard._espn_cache['raw_events'] = {
            CFB: [event('ranked', home='RANKED', away='OTHER', rank=9),
                  event('sec', home='SEC', away='ALA', rank=99), event('aggies')],
            NFL: [event('nfl', home='DAL', away='KC', rank=99)],
            'basketball/nba': [event('nba', home='LAL', away='BOS', rank=99)],
        }
        data = self.client.get('/api/data').get_json()
        self.assertEqual([t['event_id'] for t in data['teams']], ['aggies', 'sec', 'ranked', 'nfl', 'nba'])
        self.assertEqual(scoreboard.get_settings()['teams'], ['basketball/nba:LAL'])

    def test_bad_event_does_not_remove_valid_games(self):
        scoreboard._espn_cache['raw_events'][CFB] = [{'competitions': [{}]}, event()]
        self.assertEqual(len(self.client.get('/api/data').get_json()['teams']), 1)

    def test_racing_and_golf_paths_still_render(self):
        racing = event('race')
        racing['name'] = 'Test Race'
        racing['competitions'][0]['competitors'] = [
            {'order': 1, 'athlete': {'displayName': 'Driver One', 'jersey': '1'}}]
        golf = event('golf')
        golf['name'] = 'Test Golf'
        golf['competitions'][0]['competitors'] = [
            {'order': 1, 'score': '-4', 'athlete': {'displayName': 'Golfer One'},
             'status': {'position': {'displayName': '1'}}}]
        scoreboard.save_settings({'leagues': ['racing/f1', 'golf/pga']})
        scoreboard._espn_cache['raw_events'] = {'racing/f1': [racing], 'golf/pga': [golf]}
        data = self.client.get('/api/data').get_json()
        self.assertEqual(data['races'][0]['drivers'][0]['name'], 'Driver One')
        self.assertEqual(data['golf'][0]['golfers'][0]['name'], 'Golfer One')

    def test_refresh_uses_individual_windows_and_full_fbs_for_priority(self):
        scoreboard.save_settings({'football_priority': True, 'leagues': [CFB, NFL],
                                 'date_windows': {CFB: {'days_back': 0, 'days_ahead': 2},
                                                  NFL: {'days_back': 1, 'days_ahead': 7}}})
        with patch.object(scoreboard, '_fetch_league_raw', return_value=[]) as fetch:
            scoreboard._refresh_espn_cache()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].kwargs, {'days_back': 0, 'days_ahead': 2})
        self.assertEqual(fetch.call_args_list[0].args[1][CFB], '80')
        self.assertEqual(fetch.call_args_list[1].kwargs, {'days_back': 1, 'days_ahead': 7})

    def test_daily_request_ttls_and_event_deduplication(self):
        response_events = [event('same')]
        class FakeSession:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with patch.object(scoreboard.requests, 'Session', return_value=FakeSession()), patch.object(
                scoreboard, '_request_score_events', return_value=response_events) as request:
            events = scoreboard._fetch_league_raw(CFB, {CFB: '80'}, days_back=1, days_ahead=1)
        self.assertEqual(len(events), 1)
        self.assertEqual(request.call_count, 3)
        self.assertEqual([call.kwargs['ttl'] for call in request.call_args_list], [300, 30, 300])
        self.assertTrue(all('limit=1000' in call.args[0] for call in request.call_args_list))

    def test_bad_settings_rejected_without_touching_existing_file(self):
        before = Path(scoreboard.SETTINGS_FILE).read_bytes()
        for payload in [[], None, {'port': 0}, {'port': 5000.1}, {'clock_format': '25h'},
                        {'leagues': None}, {'teams': {}}, {'timezone': 'invalid'},
                        {'palette_team': []}, {'date_windows': {CFB: {'days_ahead': 1000}}},
                        {'schedule': {'startup': []}}, {'update': {'check_hours': 0}},
                        {'show_logo_slide': 'false'}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post('/api/settings', json=payload).status_code, 400)
                self.assertEqual(Path(scoreboard.SETTINGS_FILE).read_bytes(), before)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_concurrent_partial_saves_are_atomic(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(scoreboard.save_settings, [{f'qc_{i}': i} for i in range(20)]))
        data = json.loads(Path(scoreboard.SETTINGS_FILE).read_text())
        self.assertTrue(all(data[f'qc_{i}'] == i for i in range(20)))
        self.assertFalse(list(Path(self.tmp.name).glob('.settings-*')))

    def test_preferences_survive_a_new_python_process(self):
        scoreboard.save_settings({'clock_format': 'hidden', 'timezone': 'Pacific/Honolulu', 'show_logo_slide': False})
        code = ('import app; app.SETTINGS_FILE=' + repr(scoreboard.SETTINGS_FILE) +
                '; s=app.get_settings(); print(s["clock_format"], s["timezone"], s["show_logo_slide"])')
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(scoreboard.__file__).parent,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), 'hidden Pacific/Honolulu False')

    def test_reading_fresh_server_settings_never_switches_mode_or_port(self):
        Path(scoreboard.SETTINGS_FILE).unlink()
        before = scoreboard.get_settings()
        self.assertEqual(before['device_mode'], 'server')
        self.assertEqual(before['port'], 5000)
        self.assertEqual(self.client.get('/api/settings').status_code, 200)
        after = scoreboard.get_settings()
        self.assertEqual(after['device_mode'], 'server')
        self.assertEqual(after['port'], 5000)
        self.assertFalse(Path(scoreboard.KIOSK_CONFIG_FILE).exists())

    def test_failed_atomic_replace_keeps_previous_settings(self):
        before = Path(scoreboard.SETTINGS_FILE).read_bytes()
        with patch.object(scoreboard.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                scoreboard.save_settings({'clock_format': '24h'})
        self.assertEqual(Path(scoreboard.SETTINGS_FILE).read_bytes(), before)

    def test_logo_is_not_replaced_or_deleted_when_hidden(self):
        logo = Path(self.tmp.name) / 'logo.png'
        logo.write_bytes(b'custom College GameDay logo fixture')
        version = scoreboard._logo_version()
        self.assertTrue(version)
        self.client.post('/api/settings', json={'show_logo_slide': False})
        self.assertNotIn('id="logo-slide"', self.client.get('/').get_data(as_text=True).split('<script')[0])
        self.assertEqual(logo.read_bytes(), b'custom College GameDay logo fixture')
        self.assertEqual(version, scoreboard._logo_version())
        self.assertNotIn('via.placeholder.com', self.client.get('/').get_data(as_text=True))

    def test_outage_retains_slate_and_recovery_replaces_it(self):
        old = [event()]
        scoreboard._espn_cache = {'raw_events': {CFB: old}, 'updated_at': 'previous-success'}
        with patch.object(scoreboard, '_fetch_league_raw', side_effect=scoreboard.requests.Timeout('offline')):
            scoreboard._refresh_espn_cache()
        self.assertEqual(scoreboard._espn_cache['raw_events'][CFB], old)
        self.assertEqual(scoreboard._espn_cache['updated_at'], 'previous-success')
        self.assertTrue(self.client.get('/api/cache/status').get_json()['stale'])
        scoreboard._last_refresh_attempt = 0
        with patch.object(scoreboard, '_fetch_league_raw', return_value=[event('recovered')]):
            scoreboard._refresh_espn_cache()
        self.assertEqual(scoreboard._espn_cache['raw_events'][CFB][0]['id'], 'recovered')
        self.assertFalse(self.client.get('/api/cache/status').get_json()['stale'])

    def test_kiosk_requested_league_is_refreshed_without_blocking_api_on_network(self):
        self.assertEqual(scoreboard._get_league_events('basketball/nba', {}), [])
        with patch.object(scoreboard, '_fetch_league_raw', return_value=[]) as fetch:
            scoreboard._refresh_espn_cache()
        self.assertIn('basketball/nba', [call.args[0] for call in fetch.call_args_list])
        self.assertIn('basketball/nba', scoreboard._espn_cache['raw_events'])

    def test_manual_refresh_rate_limit_and_overlap(self):
        with patch.object(scoreboard, '_fetch_league_raw', return_value=[]) as fetch:
            scoreboard._refresh_espn_cache()
            scoreboard._refresh_espn_cache()
            self.assertEqual(fetch.call_count, 1)
            scoreboard._last_refresh_attempt = 0
            with scoreboard._refresh_lock:
                scoreboard._refresh_espn_cache()
            self.assertEqual(fetch.call_count, 1)

    def test_daily_http_cache_and_failure_backoff(self):
        response = Mock()
        response.json.return_value = {'events': [event()]}
        with patch.object(scoreboard.requests, 'get', return_value=response) as get:
            self.assertEqual(len(scoreboard._request_score_events('https://espn.example/day')), 1)
            scoreboard._request_score_events('https://espn.example/day')
            self.assertEqual(get.call_count, 1)
        with patch.object(scoreboard.requests, 'get', side_effect=scoreboard.requests.Timeout('offline')) as get:
            for _ in range(2):
                with self.assertRaises(scoreboard.requests.RequestException):
                    scoreboard._request_score_events('https://espn.example/failed')
            self.assertEqual(get.call_count, 1)

    def test_http_errors_and_malformed_json_are_not_successful_empty_slate(self):
        for response in [Mock(), Mock(), Mock()]:
            response.raise_for_status.side_effect = scoreboard.requests.HTTPError('503')
            with patch.object(scoreboard.requests, 'get', return_value=response):
                with self.assertRaises(scoreboard.requests.RequestException):
                    scoreboard._request_score_events('https://example/' + str(id(response)))
        response = Mock()
        response.json.return_value = {'error': 'invalid body'}
        with patch.object(scoreboard.requests, 'get', return_value=response):
            with self.assertRaises(ValueError):
                scoreboard._request_score_events('https://example/malformed')

    def test_request_cache_is_bounded(self):
        scoreboard._score_requests = {str(i): {'retry_at': 0} for i in range(512)}
        response = Mock()
        response.json.return_value = {'events': []}
        with patch.object(scoreboard.requests, 'get', return_value=response):
            scoreboard._request_score_events('https://example/new')
        self.assertEqual(len(scoreboard._score_requests), 512)

    def test_weather_cached_for_ten_minutes(self):
        response = Mock(status_code=200)
        response.json.return_value = {'current_condition': [{'temp_F': '70'}]}
        with patch.object(scoreboard.requests, 'get', return_value=response) as get:
            self.assertEqual(scoreboard.get_weather('College Station, TX'), '70°F')
            self.assertEqual(scoreboard.get_weather('College Station, TX'), '70°F')
            self.assertEqual(get.call_count, 1)

    def test_kiosk_preserves_last_server_data_on_outage(self):
        scoreboard.save_settings({'device_mode': 'kiosk'})
        scoreboard.save_kiosk_config({'server_url': 'https://server.example'})
        with patch.object(scoreboard.requests, 'post') as post:
            post.return_value = Mock(ok=True)
            post.return_value.json.return_value = {'teams': [{'home_name': 'TA&M'}], 'ticker_parts': []}
            self.assertEqual(self.client.get('/api/data').get_json()['teams'][0]['home_name'], 'TA&M')
            post.side_effect = scoreboard.requests.Timeout('offline')
            self.assertEqual(self.client.get('/api/data').get_json()['teams'][0]['home_name'], 'TA&M')
            self.assertTrue(scoreboard._kiosk_server_unreachable)
            scoreboard.save_settings({'clock_format': 'hidden', 'show_logo_slide': False})
            retained = self.client.get('/api/data').get_json()
            self.assertEqual(retained['clock_format'], 'hidden')
            self.assertFalse(retained['show_logo_slide'])



class StartupTests(unittest.TestCase):
    def test_service_templates_enable_auto_start_and_restart(self):
        root = Path(scoreboard.__file__).parent
        installer = (root / 'install.sh').read_text()
        backend = subprocess.run(['bash', 'install.sh', '--render-backend-unit',
                                  'pi', '/home/pi/scoreboard', '/home/pi'],
                                 cwd=root, text=True, capture_output=True, check=True).stdout
        kiosk = subprocess.run(['bash', 'setup_kiosk_service.sh', '--render-unit',
                                'pi', '/home/pi/scoreboard', '/home/pi'],
                               cwd=root, text=True, capture_output=True, check=True).stdout
        self.assertIn('WorkingDirectory=/home/pi/scoreboard', backend)
        self.assertIn('WantedBy=multi-user.target', backend)
        self.assertIn('systemctl enable scoreboard.service', installer)
        self.assertIn('systemctl enable kiosk.service', installer)
        self.assertIn('Restart=always', backend)
        self.assertIn('RestartSec=10', backend)
        self.assertIn('Restart=always', kiosk)
        self.assertIn('RestartSec=15', kiosk)
        self.assertIn('After=display-manager.service scoreboard.service', kiosk)
        self.assertNotIn('After=graphical.target', kiosk)
        for script in ['install.sh', 'start_kiosk.sh', 'setup_kiosk_service.sh']:
            subprocess.run(['bash', '-n', script], cwd=root, check=True)

    def test_kiosk_launcher_reads_port_and_executes_browser_using_mock_host_commands(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launcher = root / 'start_kiosk.sh'
            shutil.copyfile(Path(scoreboard.__file__).parent / 'start_kiosk.sh', launcher)
            binary = root / 'bin'
            binary.mkdir()
            for name in ['sleep', 'xset', 'curl', 'xrandr']:
                path = binary / name
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o700)
            identity = binary / 'id'
            identity.write_text('#!/bin/sh\necho 1000\n')
            identity.chmod(0o700)
            browser = binary / 'chromium'
            browser.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            browser.chmod(0o700)
            environment = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'])
            for settings, expected in [({},5000), ({'port':5017},5017)]:
                (root / 'settings.json').write_text(json.dumps(settings))
                result = subprocess.run(['bash', str(launcher)], env=environment, text=True,
                                        capture_output=True, check=True)
                self.assertIn(f'http://127.0.0.1:{expected}/?v=', result.stdout)
                self.assertIn('--kiosk', result.stdout)
                self.assertIn('--user-data-dir=', result.stdout)


if __name__ == '__main__':
    unittest.main()
