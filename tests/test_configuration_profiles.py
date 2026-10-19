"""Integration checks for additive UI settings and independent display filters."""
import unittest
from unittest.mock import patch
from pathlib import Path
import test_scoreboard_qc as fixtures
import app


class ConfigurationTests(unittest.TestCase):
    setUp = fixtures.QualityTests.setUp

    def test_large_legacy_favorite_list_is_not_discarded(self):
        favorites = [f'football/college-football:T{i}' for i in range(350)]
        self.assertEqual(self.client.post('/api/settings', json={'teams': favorites}).status_code, 200)
        self.assertEqual(self.client.get('/api/settings').get_json()['teams'], favorites)

    def test_refresh_partial_saves_keep_other_intervals(self):
        app.save_settings({'score_refresh': {'live_seconds': 45, 'idle_seconds': 1200}})
        app.save_settings({'score_refresh': {'upcoming_seconds': 600}})
        self.assertEqual(app.get_settings()['score_refresh'],
                         {'live_seconds': 45, 'upcoming_seconds': 600, 'idle_seconds': 1200, 'final_seconds': 3600})

    def test_safe_timings_preserve_content_and_pairing(self):
        original = {'clock_format': 'hidden', 'display_mode': 'ticker', 'slide_duration': 35,
                    'football_display': 'weekly',
                    'colors': {'dark_bg': '#003300'}, 'show_logo_slide': False,
                    'timezone': 'Pacific/Honolulu', 'teams': ['football/nfl:HOU'],
                    'leagues': ['football/nfl'], 'specials': [{'title': 'My slide'}],
                    'slide_playlist': [{'type': 'logo', 'key': 'logo'}]}
        app.save_settings(original)
        app.save_kiosk_config({'server_url': 'https://server.example', 'auth_token': 'test-pair-token'})
        logo = Path(app.UPLOAD_FOLDER) / 'logo.png'; logo.write_bytes(b'preserved test artwork')
        self.assertEqual(self.client.post('/api/settings/safe-defaults').status_code, 200)
        settings = app.get_settings()
        self.assertEqual(settings['clock_format'], '12h')
        self.assertEqual(settings['display_mode'], 'hybrid')
        self.assertEqual(settings['slide_duration'], 8)
        for key in ('colors', 'show_logo_slide', 'timezone', 'teams', 'leagues', 'specials', 'slide_playlist', 'football_display'):
            if key == 'colors':
                self.assertEqual(settings[key]['dark_bg'], original[key]['dark_bg'])
            else:
                self.assertEqual(settings[key], original[key])
        self.assertEqual(logo.read_bytes(), b'preserved test artwork')
        self.assertEqual(app.get_kiosk_config()['auth_token'], 'test-pair-token')
        self.assertEqual(app.app.test_client().post('/api/settings/safe-defaults').status_code, 401)

    def test_invalid_new_preferences_keep_previous_file(self):
        before = Path(app.SETTINGS_FILE).read_bytes()
        for payload in ({'score_refresh': {'live_seconds': 1}}, {'score_refresh': {'idle_seconds': None}},
                        {'score_refresh': []}, {'display_mode': 'arcade'},
                        {'transition_duration_ms': -1}, {'logo_slide_duration': 0}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post('/api/settings', json=payload).status_code, 400)
                self.assertEqual(Path(app.SETTINGS_FILE).read_bytes(), before)

    def test_malformed_render_settings_never_break_the_saved_phone_interface(self):
        before = Path(app.SETTINGS_FILE).read_bytes()
        for payload in ({'header_color': {}}, {'slide_transition': 'invalid transition'},
                        {'slide_playlist': [{'type': 'team', 'key': {}}]},
                        {'specials': [{'title': []}]},
                        {'local_schedule': {'rss_feeds': [{'url': {}}]}}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post('/api/settings', json=payload).status_code, 400)
                self.assertEqual(Path(app.SETTINGS_FILE).read_bytes(), before)
        self.assertEqual(self.client.get('/settings').status_code, 200)

    def test_kiosk_owns_all_slide_preferences_and_retained_data_is_stale(self):
        preferences = {'display_mode': 'ticker', 'slide_duration': 20, 'logo_slide_duration': 40,
                       'transition_duration_ms': 200, 'slide_transition': 'fade', 'ticker_speed': 65,
                       'slide_playlist': [{'type': 'logo', 'key': 'logo'}]}
        app.save_settings(preferences)
        data = app._kiosk_display_data({'teams': [], 'ticker_parts': []}, app.get_settings(), 'America/Chicago')
        for key, value in preferences.items():
            self.assertEqual(data[key], value)
        app.save_settings({'device_mode': 'kiosk'})
        app.save_kiosk_config({'server_url': 'https://server.example'})
        app._kiosk_last_data = {'teams': [], 'ticker_parts': [], 'cache_stale': False}
        with patch.object(app.requests, 'post', side_effect=app.requests.Timeout('offline')):
            retained = self.client.get('/api/data').get_json()
        self.assertTrue(retained['cache_stale'])
        self.assertIn('kiosk', retained['cache_errors'])

    def test_profile_requests_filter_without_changing_global_configuration(self):
        app._espn_cache['raw_events'] = {
            fixtures.CFB: [fixtures.event('college')],
            fixtures.NFL: [fixtures.event('nfl', home='HOU', away='KC', rank=99)]}
        saved = Path(app.SETTINGS_FILE).read_bytes()
        college = self.client.post('/api/data', json={'leagues': [fixtures.CFB],
            'teams': [fixtures.CFB+':TA&M'], 'football_priority': False}).get_json()
        nfl = self.client.post('/api/data', json={'leagues': [fixtures.NFL],
            'teams': [fixtures.NFL+':HOU'], 'football_priority': False}).get_json()
        self.assertEqual([item['event_id'] for item in college['teams']], ['college'])
        self.assertEqual([item['event_id'] for item in nfl['teams']], ['nfl'])
        self.assertEqual(Path(app.SETTINGS_FILE).read_bytes(), saved)

    def test_explicit_empty_conferences_are_respected_and_bad_profile_is_rejected(self):
        app.save_settings({'league_conferences': {fixtures.CFB: ['8']}})
        with patch.object(app, '_build_data_response', return_value={}) as build:
            self.assertEqual(self.client.post('/api/data', json={'league_conferences': {}}).status_code, 200)
            self.assertEqual(build.call_args.args[2], {})
        for payload in ([], None, {'timezone': 'wrong'}, {'teams': ['good', {}]}):
            self.assertEqual(self.client.post('/api/data', json=payload).status_code, 400)


if __name__ == '__main__':
    unittest.main()
