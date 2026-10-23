"""Complete weekly scorecard selection and retained provider state, offline only."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import test_scoreboard_qc as qc
from test_cfb_week import payload, at

scoreboard = qc.scoreboard
CFB = qc.CFB


def game(identifier, home_id='251', away_id='145', hour=17, state='pre', week=9):
    result = qc.event(str(identifier), state, home='TEX', away='MISS', rank=99)
    result.update(date=f'2026-10-24T{hour:02d}:00:00Z', week={'number': week}, season={'year': 2026, 'type': 2})
    home, away = result['competitions'][0]['competitors']
    home['team']['id'], away['team']['id'] = home_id, away_id
    return result


class CompleteCoverageTests(unittest.TestCase):
    def setUp(self):
        qc.QualityTests.setUp(self)
        for name, value in {'SCORE_CACHE_FILE': str(Path(self.tmp.name) / 'score_cache.json'),
                            '_last_snapshot_write': 0, '_last_snapshot_fingerprint': None}.items():
            patcher = patch.object(scoreboard, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(scoreboard, 'datetime', wraps=datetime)
        self.clock = patcher.start()
        self.clock.now.return_value = at('2026-10-24T16:00:00Z')
        self.addCleanup(patcher.stop)
        scoreboard.save_settings({'cfb_coverage': 'all_power5', 'scorecard_include_completed': True,
                                  'football_priority': True, 'teams': [], 'cfb_refresh_seconds': 180})
        scoreboard._espn_cache['cfb_week'] = scoreboard.cfb_week.select_week(payload(), at('2026-10-24T16:00Z'))

    def data(self, games):
        scoreboard._espn_cache['raw_events'][CFB] = games
        return self.client.get('/api/data').get_json()

    def provider(self, games, source=None):
        source = deepcopy(source or payload())
        source['events'] = games
        self.network.side_effect = None
        self.network.return_value = Mock()
        self.network.return_value.json.return_value = source
        return source

    def test_all_major_games_do_not_require_favorites_rankings_or_conference_selection(self):
        scoreboard.save_settings({'football_priority': False,
                                  'league_conferences': {CFB: ['1']}, 'conference_filters_version': 2,
                                  'date_windows': {CFB: {'days_back': 0, 'days_ahead': 0}}})
        games = [game('texas'), game('aggies', '245', '333'), game('nd', '87', '998'),
                 game('major-vs-fcs', '57', '999'), game('g5-only', '2026', '2027')]
        data = self.data(games)
        self.assertEqual({card['event_id'] for card in data['teams']}, {'texas', 'aggies', 'nd', 'major-vs-fcs'})
        self.assertTrue(all(not card['home_is_fav'] and not card['away_is_fav'] for card in data['teams']))
        self.assertEqual(data['cfb_week']['eligible_game_count'], 4)

    def test_more_than_20_games_sorted_by_kickoff_and_stable_event_id_ties(self):
        games = [game(str(index), hour=17 + index % 6, state=('post' if index % 3 == 0 else 'in'))
                 for index in range(45)]
        games.reverse()
        duplicate = deepcopy(games[4])
        duplicate['competitions'][0]['competitors'][0]['score'] = '99'
        data = self.data(games + [duplicate])
        self.assertEqual(len(data['teams']), 45)
        expected = sorted(games, key=scoreboard.cfb_week.sort_key)
        self.assertEqual([card['event_id'] for card in data['teams']], [event['id'] for event in expected])
        self.assertEqual(len({card['event_id'] for card in data['teams']}), 45)

    def test_rankings_favorites_status_or_score_changes_do_not_change_game_order(self):
        games = [game('late', '245', '333', hour=23), game('early', hour=17), game('middle', hour=20)]
        before = self.data(games)['teams']
        scoreboard.save_settings({'teams': [CFB + ':TA&M'], 'football_priority': True})
        games[0]['status']['type'].update(state='in', shortDetail='Q3 1:20')
        games[1]['status']['type'].update(state='post', shortDetail='Final')
        after = self.data(games)['teams']
        self.assertEqual([card['event_id'] for card in before], ['early', 'middle', 'late'])
        self.assertEqual([card['event_id'] for card in before], [card['event_id'] for card in after])

    def test_exact_week_excludes_next_week_previous_year_and_other_season_types(self):
        previous_season = game('old-year')
        previous_season['season']['year'] = 2025
        postseason = game('postseason')
        postseason['season']['type'] = 3
        data = self.data([game('current'), game('next', week=10), previous_season, postseason])
        self.assertEqual([card['event_id'] for card in data['teams']], ['current'])

    def test_missing_official_metadata_does_not_fall_back_to_favorite_featured_slate(self):
        scoreboard._espn_cache.pop('cfb_week')
        data = self.data([game('featured', '245', '333')])
        self.assertEqual(data['teams'], [])
        self.assertIn('verified ESPN football week', data['cfb_week']['warning'])
        self.assertTrue(data['cache_stale'])

    def test_fetch_uses_explicit_full_fbs_week_not_bootstrap_featured_or_favorite_games(self):
        bootstrap = self.provider([game('featured')])
        complete = deepcopy(bootstrap)
        complete['events'] = [game(str(index)) for index in range(45)] + [game('1')]
        self.network.return_value.json.side_effect = [bootstrap, complete]
        fetched = scoreboard._fetch_league_raw(CFB, {CFB: ['1']}, days_back=0, days_ahead=0)
        self.assertEqual(len(fetched), 45)
        self.assertEqual(fetched.cfb_week['week'], 9)
        self.assertEqual(self.network.call_count, 2)
        self.assertIn('groups=80&limit=1000', self.network.call_args.args[0])
        self.assertIn('dates=2026&seasontype=2&week=9', self.network.call_args.args[0])

    def test_current_calendar_week_can_trigger_explicit_new_week_query(self):
        self.clock.now.return_value = at('2026-10-26T07:00:00Z')
        old = self.provider([game('old')])
        new = deepcopy(old)
        new['week']['number'] = 10
        new['events'] = [game('next', week=10)]
        self.network.return_value.json.side_effect = [old, new]
        fetched = scoreboard._fetch_league_raw(CFB, {})
        self.assertEqual([event['id'] for event in fetched], ['next'])
        self.assertIn('dates=2026&seasontype=2&week=10', self.network.call_args.args[0])

    def test_provider_ignoring_explicit_week_is_a_failure_not_a_mixed_slate(self):
        self.clock.now.return_value = at('2026-10-26T07:00:00Z')
        self.provider([game('old')])
        with self.assertRaisesRegex(ValueError, 'confirm the requested'):
            scoreboard._fetch_league_raw(CFB, {})

    def test_refresh_interval_is_180_by_default_and_settings_do_not_rewrite_other_sports(self):
        before = scoreboard.get_settings()['score_refresh']
        self.provider([game('current', state='in')])
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100):
            scoreboard._fetch_league_raw(CFB, {})
        with patch.object(scoreboard.time_module, 'monotonic', return_value=279):
            scoreboard._fetch_league_raw(CFB, {})
        self.assertEqual(self.network.call_count, 2)
        with patch.object(scoreboard.time_module, 'monotonic', return_value=280):
            scoreboard._fetch_league_raw(CFB, {})
        self.assertEqual(self.network.call_count, 4)
        scoreboard.save_settings({'cfb_refresh_seconds': 60})
        self.assertEqual(scoreboard.get_settings()['score_refresh'], before)

    def test_outage_preserves_week_and_all_completed_early_games_without_window_pruning(self):
        original = [game('early', state='post'), game('later', hour=23)]
        official = deepcopy(scoreboard._espn_cache['cfb_week'])
        fetched = scoreboard._LeagueEvents(original, cfb_week=official)
        scoreboard.save_settings({'leagues': [CFB], 'football_priority': False,
                                  'date_windows': {CFB: {'days_back': 0, 'days_ahead': 0}}})
        with patch.object(scoreboard, '_fetch_league_raw', return_value=fetched):
            self.assertTrue(scoreboard._refresh_espn_cache())
        scoreboard._last_refresh_attempt = 0
        with patch.object(scoreboard, '_fetch_league_raw', side_effect=scoreboard.requests.Timeout('offline')):
            scoreboard._refresh_espn_cache()
        self.assertEqual(scoreboard._espn_cache['raw_events'][CFB], original)
        self.assertEqual(scoreboard._espn_cache['cfb_week'], official)
        data = self.client.get('/api/data').get_json()
        self.assertEqual(len(data['teams']), 2)
        self.assertTrue(data['cache_stale'])
        self.assertIn('Showing saved', data['cfb_week']['warning'])

    def test_snapshot_roundtrip_retains_verified_week_and_marks_scores_stale(self):
        self.data([game('current')])
        scoreboard._espn_cache['updated_at'] = '2026-10-24T16:00:00+00:00'
        self.assertTrue(scoreboard._save_score_snapshot(force=True))
        scoreboard._espn_cache.clear()
        scoreboard._espn_cache.update(raw_events={}, updated_at=None)
        self.assertTrue(scoreboard._load_score_snapshot())
        data = self.client.get('/api/data').get_json()
        self.assertEqual([card['event_id'] for card in data['teams']], ['current'])
        self.assertEqual(data['cfb_week']['week'], 9)
        self.assertTrue(data['cache_stale'])

    def test_week_metadata_change_is_persisted_even_when_event_list_is_empty(self):
        scoreboard._espn_cache['updated_at'] = '2026-10-24T16:00:00+00:00'
        scoreboard._espn_cache['raw_events'][CFB] = []
        with patch.object(scoreboard.time_module, 'monotonic', return_value=100):
            self.assertTrue(scoreboard._save_score_snapshot(force=True))
        scoreboard._espn_cache['cfb_week']['week'] = 10
        with patch.object(scoreboard.time_module, 'monotonic', return_value=500):
            self.assertTrue(scoreboard._save_score_snapshot())
        self.assertEqual(json.loads(Path(scoreboard.SCORE_CACHE_FILE).read_text())['cfb_week']['week'], 10)

    def test_new_preferences_validate_and_survive_partial_saves(self):
        before = scoreboard.get_settings()
        self.assertEqual(self.client.post('/api/settings', json={'cfb_coverage': 'favorites', 'cfb_refresh_seconds': 300}).status_code, 200)
        saved = scoreboard.get_settings()
        self.assertEqual((saved['cfb_coverage'], saved['cfb_refresh_seconds']), ('favorites', 300))
        for key in ('teams', 'colors', 'leagues', 'score_refresh'):
            self.assertEqual(saved[key], before[key])
        for invalid in ({'cfb_coverage': 'all'}, {'cfb_refresh_seconds': True},
                        {'cfb_refresh_seconds': 180.5}, {'cfb_refresh_seconds': 29}, {'cfb_refresh_seconds': 901}):
            self.assertEqual(self.client.post('/api/settings', json=invalid).status_code, 400)

    def test_bad_event_neighbor_does_not_hide_valid_weekly_games(self):
        games = [game('good'), {**game('bad1'), 'competitions': None},
                 {**game('bad2'), 'competitions': [{'competitors': None}]}]
        self.assertEqual([card['event_id'] for card in self.data(games)['teams']], ['good'])

    def test_favorites_polling_cannot_renew_an_expired_complete_week_demand(self):
        scoreboard.save_settings({'cfb_coverage': 'favorites'})
        with patch.object(scoreboard.time_module, 'monotonic', return_value=1000):
            scoreboard._get_league_events(CFB, {}, complete_week=True, refresh_seconds=30)
            self.assertTrue(scoreboard._complete_cfb_requested())
        with patch.object(scoreboard.time_module, 'monotonic', return_value=2000):
            scoreboard._get_league_events(CFB, {}, complete_week=False)
            self.assertFalse(scoreboard._complete_cfb_requested())
            self.assertFalse(scoreboard._requested_leagues[CFB]['complete_week'])
            self.assertEqual(scoreboard._requested_leagues[CFB]['refreshes'], {})

    def test_offline_kiosk_coverage_change_is_saved_but_actual_cached_mode_is_honest(self):
        source = self.data([game('favorite', '245', '333'), game('other')])
        source_before = deepcopy(source)
        scoreboard.save_settings({'device_mode': 'kiosk', 'cfb_coverage': 'all_power5',
                                  'football_priority': False, 'teams': [CFB + ':TA&M']})
        scoreboard.save_kiosk_config({'server_url': 'https://scoreboard.example'})
        with patch.object(scoreboard.requests, 'post', return_value=Mock(ok=True, json=lambda: deepcopy(source))):
            initial = self.client.get('/api/data').get_json()
        self.assertEqual(initial['cfb_coverage'], 'all_power5')
        scoreboard.save_settings({'cfb_coverage': 'favorites'})
        with patch.object(scoreboard.requests, 'post', side_effect=scoreboard.requests.Timeout('offline')):
            retained = self.client.get('/api/data').get_json()
        self.assertEqual(retained['cfb_coverage'], 'all_power5')
        self.assertEqual(retained['cfb_coverage_pending'], 'favorites')
        self.assertEqual(scoreboard.get_settings()['cfb_coverage'], 'favorites')
        self.assertEqual({card['event_id'] for card in retained['teams']}, {'favorite', 'other'})
        self.assertIn('awaiting server reconnection', retained['cfb_week']['warning'])
        self.assertEqual(scoreboard._kiosk_last_data['cfb_coverage'], 'all_power5')
        self.assertEqual(source, source_before)
        reconnected = deepcopy(source)
        reconnected.update(cfb_coverage='favorites', teams=[card for card in source['teams'] if card['event_id'] == 'favorite'])
        with patch.object(scoreboard.requests, 'post', return_value=Mock(ok=True, json=lambda: reconnected)) as post:
            recovered = self.client.get('/api/data').get_json()
        self.assertEqual(post.call_args.kwargs['json']['cfb_coverage'], 'favorites')
        self.assertEqual(recovered['cfb_coverage'], 'favorites')
        self.assertNotIn('cfb_coverage_pending', recovered)
        self.assertEqual([card['event_id'] for card in recovered['teams']], ['favorite'])


if __name__ == '__main__':
    unittest.main()
