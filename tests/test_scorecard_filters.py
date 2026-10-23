"""Main scorecard filtering never changes the ticker or loses kiosk source games."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

import test_scoreboard_qc as fixtures

app = fixtures.scoreboard
NFL = fixtures.NFL


class ScorecardFilterTests(unittest.TestCase):
    def setUp(self):
        fixtures.QualityTests.setUp(self)
        app.save_settings({'leagues': [NFL], 'teams': [NFL + ':HOU'],
                           'football_priority': False, 'cfb_coverage': 'favorites',
                           'scorecard_filter': 'both', 'scorecard_include_completed': False,
                           'date_windows': {NFL: {'days_back': 1, 'days_ahead': 2}}})
        start = datetime.now(timezone.utc)
        self.games = []
        for index, (event_id, state, detail) in enumerate([
                ('finished', 'post', 'Final'), ('first_live', 'in', 'Q2 4:20'),
                ('halftime', 'in', 'Halftime'), ('next', 'pre', 'Scheduled'),
                ('overtime', 'in', 'Overtime'), ('canceled', 'post', 'Canceled'),
                ('postponed', 'pre', 'Postponed'), ('delayed', 'in', 'Delayed'),
                ('unknown', 'unknown', 'Waiting for status')]):
            game = fixtures.event(event_id, state, home='HOU', away='KC', rank=99)
            game['date'] = (start + timedelta(minutes=index)).isoformat()
            game['status']['type']['shortDetail'] = detail
            self.games.append(game)
        app._espn_cache['raw_events'] = {NFL: self.games}

    def data(self):
        response = self.client.get('/api/data')
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def ids(self, data):
        return [card['event_id'] for card in data['teams']]

    def test_default_is_both_without_completed_when_legacy_settings_have_no_keys(self):
        path = Path(app.SETTINGS_FILE)
        raw = json.loads(path.read_text())
        raw.pop('scorecard_filter', None)
        raw.pop('scorecard_include_completed', None)
        path.write_text(json.dumps(raw))
        saved = app.get_settings()
        self.assertEqual(saved['scorecard_filter'], 'both')
        self.assertIs(saved['scorecard_include_completed'], False)
        self.assertEqual(self.ids(self.data()), ['first_live', 'halftime', 'next', 'overtime'])

    def test_all_modes_and_completed_switch_preserve_kickoff_order_and_ticker(self):
        baseline = self.data()['ticker_parts']
        expected = {'live': ['first_live', 'halftime', 'overtime'],
                    'upcoming': ['next'],
                    'both': ['first_live', 'halftime', 'next', 'overtime']}
        timestamps = {game['id']: game['date'] for game in self.games}
        for mode, ids in expected.items():
            for completed in (False, True):
                with self.subTest(mode=mode, include_completed=completed):
                    app.save_settings({'scorecard_filter': mode, 'scorecard_include_completed': completed})
                    data = self.data()
                    self.assertEqual(self.ids(data), (['finished'] if completed else []) + ids)
                    self.assertEqual(data['ticker_parts'], baseline)
                    self.assertEqual(data['scorecard_filter'], mode)
                    self.assertIs(data['scorecard_include_completed'], completed)
                    for card in data['teams']:
                        self.assertEqual(card['kickoff_iso'], timestamps[card['event_id']])
                        self.assertTrue(card['home_is_fav'])

    def test_unknown_canceled_postponed_and_delayed_are_not_invented_as_finished(self):
        app.save_settings({'scorecard_include_completed': True})
        data = self.data()
        self.assertEqual(self.ids(data), ['finished', 'first_live', 'halftime', 'next', 'overtime'])
        self.assertTrue({'canceled', 'postponed', 'delayed', 'unknown'}.isdisjoint(self.ids(data)))

    def test_source_status_changes_apply_on_next_read_without_changing_preferences_or_kickoff(self):
        app.save_settings({'scorecard_filter': 'live'})
        kickoff = self.games[3]['date']
        before_ticker = deepcopy(self.data()['ticker_parts'])
        self.assertNotIn('next', self.ids(self.data()))
        self.games[3]['status']['type'].update(state='in', shortDetail='Q1 14:25')
        live = self.data()
        self.assertIn('next', self.ids(live))
        self.assertEqual(next(card['kickoff_iso'] for card in live['teams'] if card['event_id'] == 'next'), kickoff)
        self.games[3]['status']['type'].update(state='post', shortDetail='Final')
        final = self.data()
        self.assertNotIn('next', self.ids(final))
        self.assertEqual(app.get_settings()['scorecard_filter'], 'live')
        app.save_settings({'scorecard_include_completed': True})
        shown = self.data()
        self.assertIn('next', self.ids(shown))
        self.assertEqual(next(card['kickoff_iso'] for card in shown['teams'] if card['event_id'] == 'next'), kickoff)
        # Status may change the ticker naturally; the main-card filter does not
        # remove that game from the ticker's provider slate.
        self.assertTrue(any(game.get('event_id') == 'next' for part in shown['ticker_parts'] for game in part['games']))
        self.assertNotEqual(before_ticker, shown['ticker_parts'])

    def test_empty_matching_slate_has_clear_message_and_retains_existing_ticker(self):
        app._espn_cache['raw_events'][NFL] = [self.games[3]]
        app.save_settings({'scorecard_filter': 'upcoming'})
        original = self.data()
        self.assertEqual(self.ids(original), ['next'])
        app.save_settings({'scorecard_filter': 'live'})
        empty = self.data()
        self.assertEqual(empty['teams'], [])
        self.assertIsInstance(empty['scorecard_empty_message'], str)
        self.assertIn('live', empty['scorecard_empty_message'].lower())
        self.assertEqual(empty['ticker_parts'], original['ticker_parts'])
        self.assertTrue(empty['ticker_parts'])

    def test_saved_filter_survives_new_process_and_keeps_other_preferences(self):
        original = app.get_settings()
        logo = Path(app.UPLOAD_FOLDER) / 'logo.png'
        logo.write_bytes(b'preserved custom GameDay image')
        self.assertEqual(self.client.post('/api/settings', json={
            'scorecard_filter': 'upcoming', 'scorecard_include_completed': True}).status_code, 200)
        settings = app.get_settings()
        for key in ('teams', 'leagues', 'colors', 'clock_format', 'timezone', 'show_logo_slide', 'slide_playlist'):
            self.assertEqual(settings.get(key), original.get(key))
        self.assertEqual(logo.read_bytes(), b'preserved custom GameDay image')
        code = ('import app,json; app.SETTINGS_FILE=' + repr(app.SETTINGS_FILE) +
                ';s=app.get_settings();print(json.dumps([s["scorecard_filter"],s["scorecard_include_completed"]]))')
        completed = subprocess.run([sys.executable, '-c', code], cwd=Path(app.__file__).parent,
                                   capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(completed.stdout), ['upcoming', True])

    def test_invalid_filter_saves_are_atomic(self):
        before = Path(app.SETTINGS_FILE).read_bytes()
        for field, invalids in [('scorecard_filter', ['final', 'LIVE', '', None, 1, []]),
                                ('scorecard_include_completed', ['false', 0, 1, None, []])]:
            for invalid in invalids:
                with self.subTest(field=field, value=invalid):
                    response = self.client.post('/api/settings', json={field: invalid, 'teams': ['must not save']})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(Path(app.SETTINGS_FILE).read_bytes(), before)

    def test_kiosk_retains_unfiltered_games_then_changes_filter_offline(self):
        app.save_settings({'scorecard_filter': 'both', 'scorecard_include_completed': True})
        source = self.data()
        source_ids = self.ids(source)
        self.assertIn('finished', source_ids)
        self.assertIn('next', source_ids)
        original_ticker = deepcopy(source['ticker_parts'])
        app.save_settings({'device_mode': 'kiosk', 'scorecard_filter': 'live',
                           'scorecard_include_completed': False})
        app.save_kiosk_config({'server_url': 'https://scoreboard-server.example'})
        with patch.object(app.requests, 'post', return_value=Mock(ok=True, json=lambda: deepcopy(source))) as post:
            live = self.data()
        self.assertEqual(post.call_args.kwargs['json']['scorecard_filter'], 'both')
        self.assertIs(post.call_args.kwargs['json']['scorecard_include_completed'], True)
        self.assertEqual(self.ids(live), ['first_live', 'halftime', 'overtime'])
        self.assertEqual(self.ids(app._kiosk_last_data), source_ids)
        self.assertEqual(live['ticker_parts'], original_ticker)
        with patch.object(app.requests, 'post', side_effect=app.requests.Timeout('offline')):
            for mode, completed, expected in [
                    ('upcoming', False, ['next']),
                    ('live', True, ['finished', 'first_live', 'halftime', 'overtime']),
                    ('both', True, source_ids),
                    ('both', False, ['first_live', 'halftime', 'next', 'overtime'])]:
                with self.subTest(mode=mode, completed=completed):
                    app.save_settings({'scorecard_filter': mode, 'scorecard_include_completed': completed})
                    retained = self.data()
                    self.assertEqual(self.ids(retained), expected)
                    self.assertEqual(retained['ticker_parts'], original_ticker)
                    self.assertTrue(retained['cache_stale'])
                    self.assertIn('kiosk', retained['cache_errors'])
                    self.assertEqual(self.ids(app._kiosk_last_data), source_ids)

    def test_filter_does_not_mutate_source_payload_or_other_display_categories(self):
        data = {'teams': [{'event_id': 'pre', 'game_state': 'scheduled'},
                          {'event_id': 'live', 'game_state': 'live'},
                          {'event_id': 'final', 'game_state': 'final'}],
                'ticker_parts': [{'label': 'Scores', 'games': [{'event_id': 'final'}]}],
                'races': [{'name': 'Race'}], 'golf': [{'name': 'Tournament'}],
                'specials': [{'title': 'News'}]}
        before = deepcopy(data)
        filtered = app._apply_scorecard_filter(data, {'scorecard_filter': 'upcoming',
                                                     'scorecard_include_completed': False})
        self.assertEqual(self.ids(filtered), ['pre'])
        self.assertEqual(data, before)
        for key in ('ticker_parts', 'races', 'golf', 'specials'):
            self.assertEqual(filtered[key], data[key])


if __name__ == '__main__':
    unittest.main()
