"""Offline football visibility, calendar scheduling, and kiosk recovery checks."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

import test_scoreboard_qc as fixtures
import app


CFB = fixtures.CFB
NFL = fixtures.NFL
NBA = 'basketball/nba'
MLB = 'baseball/mlb'


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def slate():
    games = [{'event_id': event_id, 'league_path': league}
             for event_id, league in [('college', CFB), ('nfl', NFL), ('nba', NBA), ('mlb', MLB)]]
    return {'teams': games, 'ticker_parts': [
        {'label': 'College Football', 'games': [games[0]]},
        {'label': 'NFL', 'games': [games[1]]},
        {'label': 'Other sports', 'games': games[2:]},
    ], 'races': [{'name': 'Test race'}], 'golf': [{'name': 'Test golf'}],
        'specials': [{'title': 'College GameDay'}], 'cache_stale': False}


class FootballDisplayTests(unittest.TestCase):
    setUp = fixtures.QualityTests.setUp

    def seed_events(self):
        app.save_settings({'football_priority': True, 'leagues': [NBA, MLB],
                           'teams': [NBA + ':HOU', MLB + ':HOU']})
        app._espn_cache['raw_events'] = {
            CFB: [fixtures.event('college')],
            NFL: [fixtures.event('nfl', home='HOU', away='KC', rank=99)],
            NBA: [fixtures.event('nba', home='HOU', away='BOS', rank=99)],
            MLB: [fixtures.event('mlb', home='HOU', away='NYY', rank=99)],
        }

    def assert_games(self, data, expected):
        self.assertEqual({game['event_id'] for game in data['teams']}, set(expected))
        self.assertEqual({game['event_id'] for part in data['ticker_parts']
                          for game in part['games']}, set(expected))

    def test_existing_configuration_defaults_to_both(self):
        self.assertNotIn('football_display', Path(app.SETTINGS_FILE).read_text())
        self.assertEqual(app.get_settings()['football_display'], 'both')
        self.assertEqual(app._football_display_mode({}, 'America/Chicago'), 'both')
        self.seed_events()
        data = self.client.get('/api/data').get_json()
        self.assertEqual(data['football_display'], 'both')
        self.assertEqual(data['football_display_active'], 'both')
        self.assert_games(data, ['college', 'nfl', 'nba', 'mlb'])

    def test_all_modes_persist_without_changing_favorites_leagues_or_logo(self):
        original = app.get_settings()
        logo = Path(app.UPLOAD_FOLDER) / 'logo.png'
        logo.write_bytes(b'custom College GameDay logo fixture')
        for mode in ('both', 'cfb', 'nfl', 'weekly'):
            with self.subTest(mode=mode):
                response = self.client.post('/api/settings', json={'football_display': mode})
                self.assertEqual(response.status_code, 200)
                saved = self.client.get('/api/settings').get_json()
                self.assertEqual(saved['football_display'], mode)
                for key in ('teams', 'leagues', 'league_conferences', 'timezone', 'show_logo_slide'):
                    self.assertEqual(saved[key], original[key])
                self.assertEqual(logo.read_bytes(), b'custom College GameDay logo fixture')

    def test_weekly_preference_survives_a_fresh_python_process(self):
        app.save_settings({'football_display': 'weekly', 'timezone': 'America/Chicago'})
        code = ('import app; app.SETTINGS_FILE=' + repr(app.SETTINGS_FILE) +
                '; s=app.get_settings(); print(s["football_display"], s["timezone"])')
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(app.__file__).parent,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), 'weekly America/Chicago')

    def test_invalid_selection_is_rejected_without_changing_settings(self):
        before = Path(app.SETTINGS_FILE).read_bytes()
        for mode in ('saturday', '', None, True, [], {}):
            with self.subTest(mode=mode):
                self.assertEqual(self.client.post('/api/settings', json={
                    'football_display': mode}).status_code, 400)
                self.assertEqual(self.client.post('/api/data', json={
                    'football_display': mode}).status_code, 400)
                self.assertEqual(Path(app.SETTINGS_FILE).read_bytes(), before)

    def test_manual_modes_ignore_weekday(self):
        for mode in ('both', 'cfb', 'nfl'):
            for day in range(7):
                with self.subTest(mode=mode, day=day):
                    self.assertEqual(app._football_display_mode({'football_display': mode},
                        'America/Chicago', instant('2026-10-12T18:00:00Z') + timedelta(days=day)), mode)

    def test_weekly_schedule_for_all_seven_days(self):
        for day, expected in enumerate(('both', 'both', 'both', 'both', 'both', 'cfb', 'nfl')):
            with self.subTest(day=day):
                self.assertEqual(app._football_display_mode({'football_display': 'weekly'},
                    'America/Chicago', instant('2026-10-12T18:00:00Z') + timedelta(days=day)), expected)

    def test_weekly_schedule_changes_at_chicago_midnight(self):
        cases = [('2026-10-17T04:59:59Z', 'both'), ('2026-10-17T05:00:00Z', 'cfb'),
                 ('2026-10-18T04:59:59Z', 'cfb'), ('2026-10-18T05:00:00Z', 'nfl'),
                 ('2026-10-19T04:59:59Z', 'nfl'), ('2026-10-19T05:00:00Z', 'both')]
        for timestamp, expected in cases:
            with self.subTest(timestamp=timestamp):
                self.assertEqual(app._football_display_mode({'football_display': 'weekly'},
                    'America/Chicago', instant(timestamp)), expected)

    def test_configured_timezone_controls_day_rather_than_utc_or_server_timezone(self):
        for zone, expected in [('America/Chicago', 'both'), ('UTC', 'cfb'),
                               ('Pacific/Honolulu', 'both'), ('Asia/Tokyo', 'cfb')]:
            with self.subTest(zone=zone):
                self.assertEqual(app._football_display_mode({'football_display': 'weekly'}, zone,
                    instant('2026-10-17T04:30:00Z')), expected)

    def test_dst_skipped_and_repeated_hours_keep_sunday_nfl(self):
        for timestamp in ('2026-03-08T07:59:59Z', '2026-03-08T08:00:00Z',
                          '2026-11-01T06:30:00Z', '2026-11-01T07:30:00Z'):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(app._football_display_mode({'football_display': 'weekly'},
                    'America/Chicago', instant(timestamp)), 'nfl')
        # In winter, local Monday starts at 06:00 UTC rather than 05:00 UTC.
        for timestamp, expected in [('2026-11-02T05:59:59Z', 'nfl'), ('2026-11-02T06:00:00Z', 'both')]:
            self.assertEqual(app._football_display_mode({'football_display': 'weekly'},
                'America/Chicago', instant(timestamp)), expected)

    def test_filter_preserves_source_data_and_other_content(self):
        source = slate()
        untouched = deepcopy(source)
        for mode, expected in [('both', ['college', 'nfl', 'nba', 'mlb']),
                               ('cfb', ['college', 'nba', 'mlb']), ('nfl', ['nfl', 'nba', 'mlb'])]:
            with self.subTest(mode=mode):
                data = app._apply_football_display(source, {'football_display': mode}, 'America/Chicago')
                self.assert_games(data, expected)
                for key in ('races', 'golf', 'specials'):
                    self.assertEqual(data[key], untouched[key])
                self.assertTrue(all(part['games'] for part in data['ticker_parts']))
                self.assertEqual(source, untouched)

    def test_filter_handles_empty_slate_without_adding_games(self):
        for mode in ('both', 'cfb', 'nfl'):
            data = app._apply_football_display({'teams': [], 'ticker_parts': []},
                                               {'football_display': mode}, 'America/Chicago')
            self.assert_games(data, [])

    def test_api_filters_both_cards_and_ticker_after_priority_leagues_are_added(self):
        self.seed_events()
        for mode, expected in [('cfb', ['college', 'nba', 'mlb']), ('nfl', ['nfl', 'nba', 'mlb']),
                               ('both', ['college', 'nfl', 'nba', 'mlb'])]:
            with self.subTest(mode=mode):
                app.save_settings({'football_display': mode})
                data = self.client.get('/api/data').get_json()
                self.assertEqual(data['football_display_active'], mode)
                self.assert_games(data, expected)
        self.assertEqual(set(app._espn_cache['raw_events']), {CFB, NFL, NBA, MLB})

    def test_request_specific_selection_does_not_mutate_saved_configuration(self):
        self.seed_events()
        before = Path(app.SETTINGS_FILE).read_bytes()
        for mode, expected in [('cfb', ['college', 'nba', 'mlb']), ('nfl', ['nfl', 'nba', 'mlb'])]:
            with self.subTest(mode=mode):
                data = self.client.post('/api/data', json={'football_display': mode}).get_json()
                self.assert_games(data, expected)
                self.assertEqual(Path(app.SETTINGS_FILE).read_bytes(), before)
        self.assert_games(self.client.get('/api/data').get_json(), ['college', 'nfl', 'nba', 'mlb'])

    def test_weekly_profile_uses_its_requested_timezone(self):
        self.seed_events()
        current = instant('2026-10-17T04:30:00Z')
        for events in app._espn_cache['raw_events'].values():
            events[0]['date'] = current.isoformat()
        before = Path(app.SETTINGS_FILE).read_bytes()

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return current.astimezone(tz) if tz else current.replace(tzinfo=None)

        with patch.object(app, 'datetime', FrozenDatetime):
            for zone, active, expected in [('America/Chicago', 'both', ['college', 'nfl', 'nba', 'mlb']),
                                            ('UTC', 'cfb', ['college', 'nba', 'mlb'])]:
                with self.subTest(zone=zone):
                    data = self.client.post('/api/data', json={
                        'football_display': 'weekly', 'timezone': zone}).get_json()
                    self.assertEqual(data['football_display_active'], active)
                    self.assertEqual(data['timezone'], zone)
                    self.assert_games(data, expected)
        self.assertEqual(Path(app.SETTINGS_FILE).read_bytes(), before)

    def test_kiosk_requests_and_retains_both_then_can_switch_while_offline(self):
        app.save_settings({'device_mode': 'kiosk', 'football_display': 'cfb'})
        app.save_kiosk_config({'server_url': 'https://server.example'})
        source = slate()
        with patch.object(app.requests, 'post', return_value=Mock(ok=True, json=lambda: source)) as post:
            self.assert_games(self.client.get('/api/data').get_json(), ['college', 'nba', 'mlb'])
        self.assertEqual(post.call_args.kwargs['json']['football_display'], 'both')
        self.assertEqual(app._kiosk_last_data, source)
        with patch.object(app.requests, 'post', side_effect=app.requests.Timeout('offline')):
            for mode, expected in [('nfl', ['nfl', 'nba', 'mlb']), ('both', ['college', 'nfl', 'nba', 'mlb']),
                                   ('cfb', ['college', 'nba', 'mlb'])]:
                with self.subTest(mode=mode):
                    app.save_settings({'football_display': mode})
                    data = self.client.get('/api/data').get_json()
                    self.assert_games(data, expected)
                    self.assertTrue(data['cache_stale'])
                    self.assertIn('kiosk', data['cache_errors'])
                    self.assertEqual(app._kiosk_last_data, source)

    def test_offline_weekly_kiosk_rechecks_local_day_without_refreshing_source(self):
        app.save_settings({'device_mode': 'kiosk', 'football_display': 'weekly'})
        app.save_kiosk_config({'server_url': 'https://server.example'})
        source = slate()
        app._kiosk_last_data = source
        with patch.object(app.requests, 'post', side_effect=app.requests.Timeout('offline')):
            for timestamp, expected in [('2026-10-18T04:59:59Z', ['college', 'nba', 'mlb']),
                                        ('2026-10-18T05:00:00Z', ['nfl', 'nba', 'mlb']),
                                        ('2026-10-19T05:00:00Z', ['college', 'nfl', 'nba', 'mlb'])]:
                with self.subTest(timestamp=timestamp):
                    current = instant(timestamp)

                    class FrozenDatetime(datetime):
                        @classmethod
                        def now(cls, tz=None):
                            return current.astimezone(tz) if tz else current.replace(tzinfo=None)

                    with patch.object(app, 'datetime', FrozenDatetime):
                        data = self.client.get('/api/data').get_json()
                    self.assert_games(data, expected)
                    self.assertEqual(app._kiosk_last_data, source)


if __name__ == '__main__':
    unittest.main()
