"""Exercise settings persistence and both server and paired-kiosk clock payloads."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['WERKZEUG_RUN_MAIN'] = 'false'  # No background network/service loops.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as scoreboard


class ClockSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for attr, filename in [('SETTINGS_FILE', 'settings.json'),
                               ('KIOSK_CONFIG_FILE', 'kiosk.json')]:
            patcher = patch.object(scoreboard, attr, str(Path(self.tmp.name) / filename))
            patcher.start()
            self.addCleanup(patcher.stop)
        palette = patch.object(scoreboard, '_team_colors_for_league', return_value={})
        palette.start(); self.addCleanup(palette.stop)
        self.client = scoreboard.app.test_client()
        with self.client.session_transaction() as session:
            session['user'] = 'admin'

    def test_legacy_default_and_saved_options_preserve_other_settings(self):
        original = {'teams': ['nfl:12'], 'slide_duration': 17,
                    'specials': [{'image': '/static/uploads/logo.png'}]}
        scoreboard.save_settings(original)
        self.assertEqual(scoreboard.get_settings()['clock_format'], '12h')
        for mode in ['12h', '24h', 'hidden']:
            response = self.client.post('/api/settings', json={'clock_format': mode})
            self.assertEqual(response.status_code, 200)
            settings = self.client.get('/api/settings').get_json()
            self.assertEqual(settings['clock_format'], mode)
            for key, value in original.items():
                self.assertEqual(settings[key], value)
            html = self.client.get('/').get_data(as_text=True)
            self.assertIn('let clockFormat = ' + json.dumps(mode), html)
        self.assertIn('id="clock_format"', self.client.get('/settings').get_data(as_text=True))
        with self.client.get('/static/js/clock.js') as response:
            self.assertEqual(response.status_code, 200)

    @patch.object(scoreboard, 'get_weather', return_value='')
    def test_server_payload(self, weather):
        scoreboard.save_settings({'clock_format': '24h', 'leagues': []})
        data = self.client.get('/api/data').get_json()
        self.assertEqual(data['clock_format'], '24h')
        self.assertEqual(data['timezone'], 'America/Chicago')
        for key in ['teams', 'ticker_parts', 'slide_duration', 'specials']:
            self.assertIn(key, data)

    @patch.object(scoreboard.requests, 'post')
    def test_paired_kiosk_keeps_its_own_preference(self, post):
        scoreboard.save_settings({'device_mode': 'kiosk', 'clock_format': 'hidden',
                                  'timezone': 'Pacific/Honolulu', 'city': ''})
        scoreboard.save_kiosk_config({'server_url': 'https://server.example'})
        post.return_value = Mock(ok=True)
        post.return_value.json.return_value = {'clock_format': '24h', 'timezone': 'UTC',
                                              'teams': [{'name': 'retained'}]}
        data = self.client.get('/api/data').get_json()
        self.assertEqual(data['clock_format'], 'hidden')
        self.assertEqual(data['timezone'], 'Pacific/Honolulu')
        self.assertEqual(data['teams'], [{'name': 'retained'}])


if __name__ == '__main__':
    unittest.main()
