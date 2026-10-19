"""Live state must expire independently of retained scores and settings saves."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

import test_scoreboard_qc as qc
from test_scoreboard_qc import event, CFB, scoreboard


class LiveIntegrationTests(unittest.TestCase):
    setUp = qc.QualityTests.setUp

    def live(self):
        game = event()
        game['status'].update(period=3, displayClock='4:20')
        game['competitions'][0]['situation'] = {'possession': '245', 'possessionText': 'TA&M 40',
                                              'down': 2, 'distance': 8}
        return game

    def fetch(self, game):
        self.network.side_effect = None
        self.network.return_value = Mock()
        self.network.return_value.json.return_value = {'events': [game]}
        fetched = scoreboard._request_score_events('https://example.test/scoreboard')
        scoreboard._espn_cache['raw_events'][CFB] = fetched

    def card(self):
        return self.client.get('/api/data').get_json()['teams'][0]

    def test_actual_provider_success_enables_widget_but_cache_hit_does_not_renew_age(self):
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100):
            self.fetch(self.live())
            self.assertEqual(self.card()['live_detail_ttl_seconds'], 90)
        with patch.object(scoreboard.time_module, 'monotonic', return_value=110):
            scoreboard._request_score_events('https://example.test/scoreboard')
            self.assertEqual(self.card()['live_detail_ttl_seconds'], 80)
            self.assertIsNotNone(self.card()['football_tracker'])
        self.assertEqual(self.network.call_count, 1)

    def test_expired_details_hide_without_losing_records_scores_or_periods(self):
        game = self.live()
        game['competitions'][0]['competitors'][0]['linescores'] = [{'value': 7}]
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100):
            self.fetch(game)
        with patch.object(scoreboard.time_module, 'monotonic', return_value=191):
            card = self.card()
        self.assertIsNone(card['football_tracker'])
        self.assertEqual(card['live_detail_ttl_seconds'], 0)
        self.assertEqual((card['home_record'], card['home_score']), ('5-1', '24'))
        self.assertEqual(card['period_scores']['home'][0], 7)

    def test_offline_snapshot_has_no_live_freshness(self):
        scoreboard._espn_cache['raw_events'][CFB] = [self.live()]
        self.assertIsNone(self.card()['football_tracker'])
        self.assertEqual(self.card()['home_score'], '24')

    def test_changed_situation_and_league_failure_invalidate_widget(self):
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100):
            self.fetch(self.live())
            original = deepcopy(scoreboard._espn_cache['raw_events'][CFB][0])
            scoreboard._espn_cache['raw_events'][CFB][0]['competitions'][0]['situation']['distance'] = 4
            self.assertIsNone(self.card()['football_tracker'])
            scoreboard._espn_cache['raw_events'][CFB] = [original]
            scoreboard._cache_errors[CFB] = 'offline'
            self.assertIsNone(self.card()['football_tracker'])

    def test_failed_request_never_renews_live_freshness(self):
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100):
            self.fetch(self.live())
        before = deepcopy(scoreboard._score_event_received_at)
        self.network.side_effect = scoreboard.requests.Timeout('offline')
        with patch.object(scoreboard.time_module, 'monotonic', return_value=140):
            with self.assertRaises(scoreboard.requests.Timeout):
                scoreboard._request_score_events('https://example.test/scoreboard')
        self.assertEqual(scoreboard._score_event_received_at, before)

    def test_successful_new_fetch_renews_and_bounds_freshness(self):
        scoreboard._score_event_received_at.update({str(i): (0, b'old') for i in range(5000)})
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100):
            self.fetch(self.live())
            self.assertEqual(self.card()['live_detail_ttl_seconds'], 90)
        with patch.object(scoreboard.time_module, 'monotonic', return_value=131):
            self.fetch(self.live())
            self.assertEqual(self.card()['live_detail_ttl_seconds'], 90)
        self.assertLessEqual(len(scoreboard._score_event_received_at), 4096)

    def test_kiosk_subtracts_transit_and_outage_never_reuses_live_widget(self):
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100):
            self.fetch(self.live())
            data = self.client.get('/api/data').get_json()
        scoreboard.save_settings({'device_mode': 'kiosk', 'show_title_bar': False, 'show_time_bar': True})
        scoreboard.save_kiosk_config({'server_url': 'https://server.example'})
        with patch.object(scoreboard.requests, 'post', return_value=Mock(ok=True, json=lambda: data)), \
                patch.object(scoreboard.time_module, 'monotonic', side_effect=[200, 203]):
            forwarded = self.client.get('/api/data').get_json()
        self.assertEqual(forwarded['teams'][0]['live_detail_ttl_seconds'], 87)
        self.assertFalse(forwarded['show_title_bar'])
        self.assertTrue(forwarded['show_time_bar'])
        with patch.object(scoreboard.requests, 'post', side_effect=scoreboard.requests.Timeout('offline')):
            retained = self.client.get('/api/data').get_json()
        self.assertEqual(retained['teams'][0]['home_score'], '24')
        self.assertIsNone(retained['teams'][0]['football_tracker'])
        self.assertEqual(retained['teams'][0]['live_detail_ttl_seconds'], 0)

    def test_bar_preferences_validate_persist_and_preserve_existing_preferences(self):
        before = scoreboard.get_settings()
        for title, time in [(False, True), (True, False), (False, False), (True, True)]:
            result = self.client.post('/api/settings', json={'show_title_bar': title, 'show_time_bar': time})
            self.assertEqual(result.status_code, 200)
            saved = scoreboard.get_settings()
            self.assertEqual((saved['show_title_bar'], saved['show_time_bar']), (title, time))
            for key in ('teams', 'leagues', 'colors', 'clock_format', 'header_visibility'):
                self.assertEqual(saved[key], before[key])
        persisted = Path(scoreboard.SETTINGS_FILE).read_bytes()
        for field in ('show_title_bar', 'show_time_bar'):
            for invalid in ('false', 0, None, []):
                self.assertEqual(self.client.post('/api/settings', json={field:invalid}).status_code, 400)
        self.assertEqual(Path(scoreboard.SETTINGS_FILE).read_bytes(), persisted)
        scoreboard.save_settings({'show_title_bar': False, 'show_time_bar': False})
        self.assertEqual(self.client.post('/api/settings/safe-defaults').status_code, 200)
        self.assertFalse(scoreboard.get_settings()['show_title_bar'])
        self.assertFalse(scoreboard.get_settings()['show_time_bar'])
        code = ('import app,json; app.SETTINGS_FILE=' + repr(scoreboard.SETTINGS_FILE) +
                ';s=app.get_settings();print(json.dumps([s["show_title_bar"],s["show_time_bar"]]))')
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(scoreboard.__file__).parent,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [False, False])

    def test_existing_settings_default_bars_on_without_migration(self):
        data = json.loads(Path(scoreboard.SETTINGS_FILE).read_text())
        data.pop('show_time_bar', None)
        data.pop('show_title_bar', None)
        Path(scoreboard.SETTINGS_FILE).write_text(json.dumps(data))
        self.assertTrue(scoreboard.get_settings()['show_time_bar'])
        self.assertTrue(scoreboard.get_settings()['show_title_bar'])


if __name__ == '__main__':
    unittest.main()
