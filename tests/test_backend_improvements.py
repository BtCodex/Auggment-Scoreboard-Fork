"""Deterministic provider/cache regressions; no network or Raspberry Pi access."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['WERKZEUG_RUN_MAIN'] = 'false'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as scoreboard

CFB = 'football/college-football'
NFL = 'football/nfl'


def game(event_id='1', state='in', detail='Q3 10:30', home='TA&M', away='ALA'):
    return {'id': event_id, 'date': datetime.now(timezone.utc).isoformat(),
            'status': {'type': {'state': state, 'shortDetail': detail}},
            'competitions': [{'competitors': [
                {'homeAway': 'home', 'score': '24', 'team': {'id': '245', 'abbreviation': home, 'logo': '/home.png'}},
                {'homeAway': 'away', 'score': '21', 'team': {'id': '333', 'abbreviation': away, 'logo': '/away.png'}}]}]}


class BackendImprovementTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        for name, value in {'SETTINGS_FILE': str(self.directory / 'settings.json'),
                            'KIOSK_CONFIG_FILE': str(self.directory / 'kiosk.json'),
                            'SCORE_CACHE_FILE': str(self.directory / 'score_cache.json'),
                            '_score_requests': {}, '_score_event_received_at': {}, '_cache_errors': {}, '_requested_leagues': {},
                            '_last_refresh_attempt': 0, '_last_snapshot_write': 0,
                            '_ap_poll_request': {'retry_at': float('inf'), 'failures': 0},
                            '_score_details': scoreboard.ScoreDetailsCache(),
                            '_espn_cache': {'raw_events': {}, 'updated_at': None}}.items():
            patcher = patch.object(scoreboard, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, replacement in [('get_weather', ''), ('resolve_palette', ({}, '#000000')),
                                  ('_build_local_schedule_items', [])]:
            patcher = patch.object(scoreboard, name, return_value=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        network = patch.object(scoreboard.requests, 'get', side_effect=AssertionError('Unexpected real network request'))
        network.start()
        self.addCleanup(network.stop)
        scoreboard.save_settings({'city': '', 'football_priority': False, 'cfb_coverage': 'favorites', 'scorecard_include_completed': True, 'leagues': [CFB],
                                  'teams': [CFB + ':TA&M', CFB + ':ALA'], 'color_mode': 'manual'})

    def data(self, events):
        scoreboard._espn_cache['raw_events'][CFB] = events
        settings = scoreboard.get_settings()
        return scoreboard._build_data_response(settings['leagues'], settings['teams'], {},
                                                settings['timezone'], settings)

    def test_explicit_states_never_turn_canceled_games_into_finals(self):
        cases = [('pre', 'Scheduled', 'scheduled', 'pre'), ('in', 'Q2 1:23', 'live', 'live'),
                 ('in', 'Halftime', 'halftime', 'live'), ('in', '2OT', 'overtime', 'live'),
                 ('post', 'Final/OT', 'final', 'final'), ('post', 'Canceled', 'canceled', 'pre'),
                 ('pre', 'Postponed', 'postponed', 'pre'), ('in', 'Weather Delay', 'delayed', 'pre'),
                 ('unexpected', '', 'unknown', 'pre')]
        for state, detail, normalized, color in cases:
            with self.subTest(state=state, detail=detail):
                item = game(state=state, detail=detail)
                data = self.data([item])
                self.assertEqual(scoreboard._event_status(item)[0], normalized)
                if normalized in ('canceled', 'postponed', 'delayed', 'unknown'):
                    self.assertEqual(data['teams'], [])
                    ticker_game = data['ticker_parts'][0]['games'][0]
                    self.assertEqual(ticker_game['color_state'], color)
                    self.assertIsNone(ticker_game['winner'])
                    continue
                card = data['teams'][0]
                self.assertEqual(card['game_state'], normalized)
                self.assertEqual(card['color_state'], color)
                if normalized in ('canceled', 'postponed', 'delayed', 'unknown'):
                    self.assertIsNone(card['winner'])

    def test_missing_scores_are_unavailable_not_invented_zeroes(self):
        event = game()
        home, away = event['competitions'][0]['competitors']
        home.pop('score')
        away['score'] = None
        card = self.data([event])['teams'][0]
        self.assertEqual((card['home_score'], card['away_score']), ('—', '—'))
        self.assertIsNone(card['winner'])
        home['score'], away['score'] = '0', {'displayValue': '0'}
        card = self.data([event])['teams'][0]
        self.assertEqual((card['home_score'], card['away_score']), ('0', '0'))

    def test_duplicate_favorites_events_and_repeated_matchups(self):
        first = game('morning')
        second = game('evening')
        data = self.data([first, deepcopy(first), second])
        self.assertEqual(len(data['teams']), 2)
        self.assertEqual(len(data['ticker_parts'][0]['games']), 2)
        self.assertTrue(data['teams'][0]['home_is_fav'])
        self.assertTrue(data['teams'][0]['away_is_fav'])
        self.assertEqual(data['ticker_parts'][0]['games'][0]['home_logo'], '/home.png')

    def test_missing_team_or_status_does_not_drop_neighbor_game(self):
        malformed = game('bad')
        malformed['competitions'][0]['competitors'] = [None, {'team': 'invalid'}]
        unknown = game('unknown')
        unknown.pop('status')
        data = self.data([malformed, unknown, game('good')])
        self.assertEqual([card['event_id'] for card in data['teams']], ['good'])
        # Unknown status cannot be asserted live/upcoming, but must not drop a valid neighbor.

    def test_ranked_other_sport_never_overtakes_football(self):
        basketball = 'basketball/mens-college-basketball'
        scoreboard.save_settings({'football_priority': True, 'leagues': [CFB, NFL, basketball],
                                  'teams': [basketball + ':TA&M']})
        hoops = game('hoops')
        hoops['competitions'][0]['competitors'][0]['curatedRank'] = {'current': 1}
        hoops['competitions'][0]['competitors'][0]['team']['conferenceId'] = '8'
        scoreboard._espn_cache['raw_events'] = {CFB: [game('aggies')], NFL: [game('nfl')], basketball: [hoops]}
        data = self.data([game('aggies')])
        self.assertEqual([card['event_id'] for card in data['teams']], ['aggies', 'nfl', 'hoops'])

    def test_default_refresh_intervals_and_custom_preferences(self):
        self.assertEqual(scoreboard._events_refresh_interval([game()]), 30)
        scheduled = game(state='pre')
        scheduled['date'] = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        self.assertEqual(scoreboard._events_refresh_interval([scheduled]), 300)
        self.assertEqual(scoreboard._events_refresh_interval([game(state='post', detail='Final')]), 3600)
        self.assertEqual(scoreboard._events_refresh_interval([]), 900)
        scoreboard.save_settings({'score_refresh': {'live_seconds': 60, 'upcoming_seconds': 120,
                                                     'idle_seconds': 600, 'final_seconds': 7200}})
        self.assertEqual(scoreboard._events_refresh_interval([game()]), 60)
        self.assertEqual(scoreboard._events_refresh_interval([scheduled]), 120)

    def test_scheduled_game_poll_reaches_kickoff_boundary(self):
        scheduled = game(state='pre')
        scheduled['date'] = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()
        self.assertGreater(scoreboard._events_refresh_interval([scheduled]), 85)
        self.assertLessEqual(scoreboard._events_refresh_interval([scheduled]), 90)
        scheduled['date'] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.assertEqual(scoreboard._events_refresh_interval([scheduled]), 30)

    def test_cache_expiry_and_setting_change_without_restart(self):
        response = Mock()
        response.json.return_value = {'events': [game()]}
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100), patch.object(
                scoreboard.requests, 'get', return_value=response) as fetch:
            scoreboard._request_score_events('https://example/live')
            scoreboard._request_score_events('https://example/live')
            self.assertEqual(fetch.call_count, 1)
        scoreboard.save_settings({'score_refresh': {'live_seconds': 60}})
        with patch.object(scoreboard.time_module, 'monotonic', return_value=131), patch.object(
                scoreboard.requests, 'get', return_value=response) as fetch:
            scoreboard._request_score_events('https://example/live')
            self.assertEqual(fetch.call_count, 0)
        with patch.object(scoreboard.time_module, 'monotonic', return_value=161), patch.object(
                scoreboard.requests, 'get', return_value=response) as fetch:
            scoreboard._request_score_events('https://example/live')
            self.assertEqual(fetch.call_count, 1)

    def test_failure_exponential_backoff_retains_cached_data_and_recovers(self):
        response = Mock()
        response.json.return_value = {'events': [game()]}
        url = 'https://example/backoff'
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100), patch.object(
                scoreboard.requests, 'get', return_value=response):
            scoreboard._request_score_events(url)
        for attempt, retry in [(131, 161), (162, 222), (223, 343)]:
            with patch.object(scoreboard.time_module, 'monotonic', return_value=attempt), patch.object(
                    scoreboard.requests, 'get', side_effect=scoreboard.requests.Timeout('offline')) as fetch:
                with self.assertRaises(scoreboard.requests.RequestException):
                    scoreboard._request_score_events(url)
                with self.assertRaises(scoreboard.requests.RequestException):
                    scoreboard._request_score_events(url)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(scoreboard._score_requests[url]['retry_at'], retry)
                self.assertEqual(scoreboard._score_requests[url]['events'][0]['id'], '1')
        with patch.object(scoreboard.time_module, 'monotonic', return_value=344), patch.object(
                scoreboard.requests, 'get', return_value=response):
            scoreboard._request_score_events(url)
        self.assertEqual(scoreboard._score_requests[url]['failures'], 0)
        self.assertNotIn('error', scoreboard._score_requests[url])

    def test_provider_retry_after_is_respected(self):
        response = Mock(status_code=429, headers={'Retry-After': '120'})
        error = scoreboard.requests.HTTPError('rate limited', response=response)
        response.raise_for_status.side_effect = error
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100), patch.object(
                scoreboard.requests, 'get', return_value=response):
            with self.assertRaises(scoreboard.requests.HTTPError):
                scoreboard._request_score_events('https://example/limited')
        self.assertEqual(scoreboard._score_requests['https://example/limited']['retry_at'], 220)

    def test_malformed_nonempty_response_cannot_erase_cached_slate(self):
        response = Mock()
        response.json.return_value = {'events': [None, {'error': 'broken'}]}
        with patch.object(scoreboard.requests, 'get', return_value=response):
            with self.assertRaisesRegex(ValueError, 'no valid events'):
                scoreboard._request_score_events('https://example/malformed')

    def test_partial_day_failure_still_updates_live_scores(self):
        old, new = game('live'), game('live')
        new['competitions'][0]['competitors'][0]['score'] = '31'
        retained = game('future', state='pre')
        scoreboard._espn_cache['raw_events'][CFB] = [old, retained]
        partial = scoreboard._LeagueEvents([new], ['future day unavailable'])
        with patch.object(scoreboard, '_fetch_league_raw', return_value=partial):
            scoreboard._refresh_espn_cache()
        events = scoreboard._espn_cache['raw_events'][CFB]
        self.assertEqual(events[0]['competitions'][0]['competitors'][0]['score'], '31')
        self.assertEqual(events[1]['id'], 'future')
        self.assertIn(CFB, scoreboard._cache_errors)

    def test_same_day_window_does_not_fetch_tomorrow(self):
        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(scoreboard.requests, 'Session', return_value=Session()), patch.object(
                scoreboard, '_request_score_events', return_value=[]) as request:
            scoreboard._fetch_league_raw(CFB, {}, days_back=0, days_ahead=0)
        self.assertEqual(request.call_count, 1)

    def test_requested_kiosk_window_expands_shared_fetch_then_expires(self):
        scoreboard.save_settings({'date_windows': {CFB: {'days_back': 0, 'days_ahead': 2}}})
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100):
            scoreboard._get_league_events(CFB, {}, (2, 10))
        with patch.object(scoreboard.time_module, 'monotonic', return_value=200), patch.object(
                scoreboard, '_fetch_league_raw', return_value=[]) as fetch:
            scoreboard._refresh_espn_cache()
            self.assertEqual(fetch.call_args.kwargs, {'days_back': 2, 'days_ahead': 10})
        scoreboard._last_refresh_attempt = 0
        with patch.object(scoreboard.time_module, 'monotonic', return_value=1101), patch.object(
                scoreboard, '_fetch_league_raw', return_value=[]) as fetch:
            scoreboard._refresh_espn_cache()
            self.assertEqual(fetch.call_args.kwargs, {'days_back': 0, 'days_ahead': 2})
        self.assertNotIn(CFB, scoreboard._requested_leagues)

    def test_partial_errors_prune_old_events_and_bound_malformed_data(self):
        ancient = game('ancient', state='post', detail='Final')
        ancient['date'] = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        scoreboard._espn_cache['raw_events'][CFB] = [ancient, game('current')]
        with patch.object(scoreboard, '_fetch_league_raw', return_value=scoreboard._LeagueEvents([], ['offline'])):
            scoreboard._refresh_espn_cache()
        self.assertEqual([event['id'] for event in scoreboard._espn_cache['raw_events'][CFB]], ['current'])
        malformed = [{'id': str(index), 'date': '', 'status': {}} for index in range(2100)]
        self.assertEqual(len(scoreboard._bounded_slate(malformed, 1, 7, 'America/Chicago')), 2000)

    def test_pga_tournament_stays_visible_on_weekend(self):
        scoreboard.save_settings({'leagues': ['golf/pga'], 'date_windows': {'golf/pga': {'days_back': 1, 'days_ahead': 7}}})
        golf = game('tournament')
        golf['date'] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        golf['name'] = 'Multi-day tournament'
        golf['competitions'][0]['competitors'] = [{'score': '-6', 'athlete': {'displayName': 'Player One'},
                                                  'status': {'position': {'displayName': 'T1', 'id': '1'}}}]
        scoreboard._espn_cache['raw_events']['golf/pga'] = [golf]
        self.assertEqual(self.data([])['golf'][0]['tournament_name'], 'Multi-day tournament')
        golf['status']['type'] = {'state': 'post', 'shortDetail': 'Final'}
        golf['endDate'] = datetime.now(timezone.utc).isoformat()
        self.assertEqual(self.data([])['golf'][0]['color_state'], 'final')
        self.assertEqual(scoreboard._bounded_slate([golf], 1, 7, 'America/Chicago'), [golf])

    def test_snapshot_round_trip_is_marked_stale_and_writes_are_throttled(self):
        scoreboard._espn_cache.update(raw_events={CFB: [game()]}, updated_at='2026-10-16T12:00:00+00:00')
        self.assertTrue(scoreboard._save_score_snapshot())
        self.assertFalse(scoreboard._save_score_snapshot())
        scoreboard._espn_cache = {'raw_events': {}, 'updated_at': None}
        self.assertTrue(scoreboard._load_score_snapshot())
        self.assertEqual(scoreboard._espn_cache['raw_events'][CFB][0]['id'], '1')
        self.assertIn('awaiting provider refresh', scoreboard._cache_errors[CFB])

    def test_corrupt_snapshot_and_failed_write_preserve_prior_state(self):
        Path(scoreboard.SCORE_CACHE_FILE).write_text('{invalid')
        self.assertFalse(scoreboard._load_score_snapshot())
        scoreboard._espn_cache.update(raw_events={CFB: [game()]}, updated_at='2026-10-16T12:00:00+00:00')
        self.assertTrue(scoreboard._save_score_snapshot())
        previous = Path(scoreboard.SCORE_CACHE_FILE).read_bytes()
        with patch.object(scoreboard.os, 'replace', side_effect=OSError('disk full')):
            self.assertFalse(scoreboard._save_score_snapshot(force=True))
        self.assertEqual(Path(scoreboard.SCORE_CACHE_FILE).read_bytes(), previous)
        self.assertFalse(list(self.directory.glob('.scores-*')))

    def test_snapshot_rejects_unknown_leagues_and_invalid_slate_types(self):
        Path(scoreboard.SCORE_CACHE_FILE).write_text(json.dumps({
            'raw_events': {'arbitrary/unsupported': [game()], CFB: 'wrong', NFL: [game()]},
            'updated_at': '2026-10-16T12:00:00+00:00'}))
        self.assertTrue(scoreboard._load_score_snapshot())
        self.assertEqual(list(scoreboard._espn_cache['raw_events']), [NFL])

    def test_schedule_clock_noon_midnight_and_dst_boundaries(self):
        for hour, minute, expected in [(0, 0, '12:00 AM'), (0, 1, '12:01 AM'), (11, 59, '11:59 AM'),
                                       (12, 0, '12:00 PM'), (12, 1, '12:01 PM'), (23, 59, '11:59 PM')]:
            stamp = datetime(2026, 1, 1, hour, minute, tzinfo=timezone.utc).isoformat()
            self.assertEqual(scoreboard.format_local_datetime(stamp, 'UTC')['time'], expected)
        for stamp, expected in [('2026-03-08T07:59:00Z', '1:59 AM'), ('2026-03-08T08:00:00Z', '3:00 AM'),
                                ('2026-11-01T06:30:00Z', '1:30 AM'), ('2026-11-01T07:30:00Z', '1:30 AM')]:
            self.assertEqual(scoreboard.format_local_datetime(stamp, 'America/Chicago')['time'], expected)
        self.assertEqual(scoreboard.format_local_datetime('2026-01-01T18:00:00', 'America/Chicago')['time'], '12:00 PM')


if __name__ == '__main__':
    unittest.main()
