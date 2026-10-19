"""End-to-end offline regressions for the additive scorecard development update.

All settings, images, and cache snapshots are private temporary fixtures. Provider
calls are explicitly mocked; these tests never contact a Raspberry Pi or ESPN.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

import test_scoreboard_qc as fixtures
import app


CFB, NFL = fixtures.CFB, fixtures.NFL


def game(event_id='1', home_id='245', away_id='333', home='TA&M', away='ALA',
         state='in', detail='Q2 4:20', period=2, lines=None):
    value = fixtures.event(event_id, state, home=home, away=away)
    value['status'] = {'period': period, 'type': {'state': state, 'shortDetail': detail}}
    for competitor, team_id in zip(value['competitions'][0]['competitors'], (home_id, away_id)):
        competitor['team']['id'] = team_id
        competitor['records'] = [{'type': 'home', 'summary': '3-0'},
                                 {'type': 'total', 'summary': '6-2'}]
        if lines is not None:
            competitor['linescores'] = [{'value': item} for item in lines]
    return value


def provider_response(teams):
    response = Mock()
    response.json.return_value = {'sports': [{'leagues': [{'teams': [
        {'team': value} for value in teams]}]}]}
    return response


class UpdateIntegrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.QualityTests.setUp(self)
        for name, value in {
            'SCORE_CACHE_FILE': str(Path(self.tmp.name) / 'score_cache.json'),
            '_last_snapshot_write': 0,
            '_last_snapshot_fingerprint': None,
        }.items():
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def data(self, payload=None):
        response = (self.client.get('/api/data') if payload is None else
                    self.client.post('/api/data', json=payload))
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def picker(self, path):
        response = self.client.get('/api/teams/' + path)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_header_defaults_to_automatic_without_altering_clock(self):
        Path(app.SETTINGS_FILE).unlink()
        defaults = app.get_settings()
        self.assertEqual(defaults['header_visibility'], 'auto')
        self.assertEqual(defaults['clock_format'], '12h')
        self.assertEqual(defaults['timezone'], 'America/Chicago')

    def test_header_settings_apply_to_api_in_all_modes_and_keep_clock_independent(self):
        for mode in ('scoreboard', 'hybrid', 'ticker'):
            for header in ('always', 'hidden', 'auto'):
                with self.subTest(mode=mode, header=header):
                    preferences = {'display_mode': mode, 'header_visibility': header,
                                   'clock_format': 'hidden'}
                    self.assertEqual(self.client.post('/api/settings', json=preferences).status_code, 200)
                    data = self.data()
                    self.assertEqual(data['header_visibility'], header)
                    self.assertEqual(data['display_mode'], mode)
                    self.assertEqual(data['clock_format'], 'hidden')

    def test_invalid_header_and_migration_version_are_atomic(self):
        previous = Path(app.SETTINGS_FILE).read_bytes()
        for payload in ({'header_visibility': 'sometimes'}, {'header_visibility': True},
                        {'header_visibility': None}, {'header_visibility': []},
                        {'conference_filters_version': True}, {'conference_filters_version': 3}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post('/api/settings', json=payload).status_code, 400)
                self.assertEqual(Path(app.SETTINGS_FILE).read_bytes(), previous)

    def test_header_preference_survives_a_fresh_python_process(self):
        self.client.post('/api/settings', json={'header_visibility': 'always', 'clock_format': '24h'})
        code = ('import app,json; app.SETTINGS_FILE=' + repr(app.SETTINGS_FILE) +
                '; s=app.get_settings(); print(json.dumps([s["header_visibility"],s["clock_format"]]))')
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(app.__file__).parent,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), ['always', '24h'])

    def test_kiosk_owns_header_and_clock_even_when_server_is_unreachable(self):
        app.save_settings({'device_mode': 'kiosk', 'header_visibility': 'hidden',
                           'clock_format': '12h'})
        app.save_kiosk_config({'server_url': 'https://server.example'})
        original = {'teams': [], 'ticker_parts': [], 'header_visibility': 'always',
                    'clock_format': '24h'}
        app._kiosk_last_data = deepcopy(original)
        with patch.object(app.requests, 'post', side_effect=app.requests.Timeout('offline')):
            retained = self.data()
        self.assertEqual(retained['header_visibility'], 'hidden')
        self.assertEqual(retained['clock_format'], '12h')
        self.assertTrue(retained['cache_stale'])
        self.assertEqual(app._kiosk_last_data, original)

    def test_legacy_conferences_migrate_and_persist_without_content_loss(self):
        favorites = [CFB + ':TA&M', CFB + ':SMU', NFL + ':HOU', 'baseball/mlb:HOU', 'basketball/nba:HOU']
        logo = Path(app.UPLOAD_FOLDER) / 'logo.png'
        logo.write_bytes(b'College GameDay custom image remains untouched')
        legacy = {'league_conferences': {CFB: ['9', '21'], 'basketball/nba': ['legacy']},
                  'teams': favorites, 'colors': {'dark_bg': '#003300'}, 'show_logo_slide': True}
        Path(app.SETTINGS_FILE).write_text(json.dumps(legacy))
        loaded = app.get_settings()
        self.assertEqual(loaded['league_conferences'][CFB], ['8', '9'])
        self.assertEqual(loaded['conference_filters_version'], 2)
        self.assertEqual(self.client.post('/api/settings', json={'header_visibility': 'always'}).status_code, 200)
        saved = json.loads(Path(app.SETTINGS_FILE).read_text())
        self.assertEqual(saved['league_conferences'], {CFB: ['8', '9'], 'basketball/nba': ['legacy']})
        self.assertEqual(saved['conference_filters_version'], 2)
        self.assertEqual(saved['teams'], favorites)
        self.assertEqual(saved['colors']['dark_bg'], '#003300')
        self.assertEqual(logo.read_bytes(), b'College GameDay custom image remains untouched')

    def test_legacy_comma_conferences_are_migrated_once_and_v2_pac12_stays_pac12(self):
        Path(app.SETTINGS_FILE).write_text(json.dumps({'league_conferences': {CFB: '9,21,1'}}))
        self.assertEqual(app.get_settings()['league_conferences'][CFB], '8,9,1')
        for _ in range(2):
            response = self.client.post('/api/settings', json={
                'league_conferences': {CFB: ['9']}, 'conference_filters_version': 2})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(app.get_settings()['league_conferences'][CFB], ['9'])
        self.assertEqual(json.loads(Path(app.SETTINGS_FILE).read_text())['conference_filters_version'], 2)

    def test_legacy_profile_requests_translate_ids_without_modifying_saved_configuration(self):
        previous = Path(app.SETTINGS_FILE).read_bytes()
        for value, expected, version in [(['9'], ['8'], None), (['21'], ['9'], None),
                                         (['9'], ['9'], 2)]:
            payload = {'league_conferences': {CFB: value}}
            if version is not None:
                payload['conference_filters_version'] = version
            with self.subTest(payload=payload), patch.object(app, '_build_data_response', return_value={}) as build:
                self.assertEqual(self.client.post('/api/data', json=payload).status_code, 200)
                self.assertEqual(build.call_args.args[2], {CFB: expected})
        self.assertEqual(Path(app.SETTINGS_FILE).read_bytes(), previous)

    def test_cached_2026_conference_filters_do_not_erase_other_conferences_or_nfl(self):
        slate = [game('1'), game('2', '36', '265', 'ORST', 'WSU'),
                 game('3', '2567', '152', 'SMU', 'NCSU')]
        app._espn_cache['raw_events'] = {CFB: slate, NFL: [game('4', home='HOU', away='KC')]}
        original = deepcopy(app._espn_cache['raw_events'])
        self.assertEqual([item['id'] for item in app._get_league_events(CFB, {CFB: ['8']})], ['1'])
        self.assertEqual([item['id'] for item in app._get_league_events(CFB, {CFB: ['9']})], ['2'])
        self.assertEqual([item['id'] for item in app._get_league_events(CFB, {CFB: ['1']})], ['3'])
        self.assertEqual(app._get_league_events(CFB, {}), slate)
        self.assertEqual(app._get_league_events(NFL, {CFB: ['9']}), original[NFL])
        self.assertEqual(app._espn_cache['raw_events'], original)
        self.network.assert_not_called()

    def test_priority_cannot_reintroduce_teams_filtered_by_conference(self):
        app._espn_cache['raw_events'] = {CFB: [game('1'), game('2', '36', '265', 'ORST', 'WSU')],
                                         NFL: [game('3', home='HOU', away='KC')]}
        data = self.data({'leagues': [CFB, NFL], 'teams': [CFB + ':ORST', NFL + ':HOU'],
                         'football_priority': True, 'conference_filters_version': 2,
                         'league_conferences': {CFB: ['9']}})
        self.assertEqual({item['event_id'] for item in data['teams']}, {'2', '3'})
        self.assertEqual({item['event_id'] for part in data['ticker_parts'] for item in part['games']}, {'2', '3'})

    def test_kiosk_sends_current_conference_version_to_avoid_double_migration(self):
        app.save_settings({'device_mode': 'kiosk', 'league_conferences': {CFB: ['9']},
                           'conference_filters_version': 2, 'header_visibility': 'always'})
        app.save_kiosk_config({'server_url': 'https://server.example'})
        response = Mock(ok=True)
        response.json.return_value = {'teams': [], 'ticker_parts': [], 'header_visibility': 'hidden'}
        with patch.object(app.requests, 'post', return_value=response) as post:
            self.assertEqual(self.data()['header_visibility'], 'always')
        self.assertEqual(post.call_args.kwargs['json']['league_conferences'][CFB], ['9'])
        self.assertEqual(post.call_args.kwargs['json']['conference_filters_version'], 2)

    def test_offline_team_picker_contains_75_conference_schools_notre_dame_and_all_32_nfl(self):
        with patch.object(app.requests, 'get', side_effect=app.requests.Timeout('offline')):
            college, pro = self.picker(CFB), self.picker(NFL)
        self.assertEqual(len(college), 76)
        self.assertEqual(sum(bool(team['target']) for team in college), 75)
        self.assertEqual({team['abbr'] for team in college if team['id'] == '87'}, {'ND'})
        self.assertEqual(len(pro), 32)
        self.assertEqual(len({team['id'] for team in pro}), 32)
        for team in college + pro:
            self.assertTrue(team['id'].isdigit())
            self.assertIsInstance(team['name'], str)
            self.assertTrue(team['name'])
            self.assertTrue(team['abbr'])
            self.assertTrue(team['logo'].startswith('https://a.espncdn.com/'))

    def test_partial_provider_teams_merge_with_catalog_and_extra_teams_are_retained(self):
        extra = {'id': '99999', 'abbreviation': 'EXTRA', 'displayName': 'Additional College',
                 'logos': [{'href': 'https://example.test/extra.png'}]}
        existing = {'id': '245', 'abbreviation': 'TA&M', 'displayName': 'Texas A&M Aggies',
                    'logos': [{'href': 'https://example.test/aggies.png'}]}
        with patch.object(app.requests, 'get', return_value=provider_response([existing, extra])) as get:
            teams = self.picker(CFB)
            again = self.picker(CFB)
        self.assertEqual(len(teams), 77)
        self.assertEqual(again, teams)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(next(team for team in teams if team['id'] == '245')['logo'],
                         'https://example.test/aggies.png')
        self.assertTrue(any(team['id'] == '99999' for team in teams))
        self.assertTrue(any(team['abbr'] == 'SMU' for team in teams))

    def test_failed_team_refresh_retains_provider_extras_and_uses_backoff(self):
        extra = {'id': '99999', 'abbreviation': 'EXTRA', 'displayName': 'Additional College'}
        with patch.object(app.time_module, 'monotonic', return_value=100), patch.object(
                app.requests, 'get', return_value=provider_response([extra])):
            first = self.picker(CFB)
        with patch.object(app.time_module, 'monotonic', return_value=3701), patch.object(
                app.requests, 'get', side_effect=app.requests.Timeout('offline')) as get:
            self.assertEqual(self.picker(CFB), first)
            self.assertEqual(self.picker(CFB), first)
            self.assertEqual(get.call_count, 1)
        with patch.object(app.time_module, 'monotonic', return_value=3762), patch.object(
                app.requests, 'get', return_value=provider_response([extra])) as get:
            self.assertEqual(self.picker(CFB), first)
            get.assert_called_once()

    def test_malformed_team_provider_payloads_never_break_selection(self):
        payloads = [None, [], {'sports': None}, {'sports': [None]},
                    {'sports': [{'leagues': [None]}]},
                    {'sports': [{'leagues': [{'teams': None}]}]},
                    {'sports': [{'leagues': [{'teams': [{'team': {'id': '245',
                        'abbreviation': 'TA&M', 'displayName': 245, 'logos': None}}]}]}]},
                    {'sports': [{'leagues': [{'teams': [{'team': {'id': '245',
                        'abbreviation': 'TA&M', 'displayName': 'Texas A&M', 'logos': ['invalid']}}]}]}]}]
        for payload in payloads:
            with self.subTest(payload=payload):
                app._team_picker_cache.clear()
                response = Mock()
                response.json.return_value = payload
                with patch.object(app.requests, 'get', return_value=response):
                    teams = self.picker(CFB)
                self.assertEqual(len(teams), 76)
                self.assertTrue(all(isinstance(team['name'], str) for team in teams))

    def test_legacy_alias_favorites_still_select_matching_provider_games(self):
        cases = [('152', 'NCSU', 'NCST'), ('201', 'OU', 'OKLA'), ('77', 'NU', 'NW')]
        for team_id, canonical, legacy in cases:
            for saved, provider in ((legacy, canonical), (canonical, legacy)):
                with self.subTest(team_id=team_id, saved=saved, provider=provider):
                    favorite = CFB + ':' + saved
                    app.save_settings({'teams': [favorite], 'football_priority': False})
                    app._espn_cache['raw_events'] = {CFB: [game(home_id=team_id, home=provider,
                                                                away_id='87', away='ND')]}
                    cards = self.data()['teams']
                    self.assertEqual(len(cards), 1)
                    self.assertTrue(cards[0]['home_is_fav'])
                    self.assertEqual(app.get_settings()['teams'], [favorite])

    def test_team_picker_uses_saved_legacy_key_so_existing_selections_remain_checked(self):
        app.save_settings({'teams': [CFB + ':NCST', CFB + ':OKLA', CFB + ':NW']})
        with patch.object(app.requests, 'get', side_effect=app.requests.Timeout('offline')):
            rows = {team['id']: team for team in self.picker(CFB)}
        for team_id, abbr in [('152', 'NCST'), ('201', 'OKLA'), ('77', 'NW')]:
            self.assertEqual(rows[team_id]['abbr'], abbr)
        self.assertEqual(app.get_settings()['teams'], [CFB + ':NCST', CFB + ':OKLA', CFB + ':NW'])

    def test_scorecard_records_and_periods_survive_all_game_states_without_requests(self):
        cases = [('pre', 'Scheduled', 0, None, 'scheduled'),
                 ('in', 'Q2 4:20', 2, [7, 3], 'live'),
                 ('in', 'Halftime', 2, [7, 3], 'halftime'),
                 ('in', '2OT', 6, [7, 3, 0, 7, 3, 7], 'overtime'),
                 ('post', 'Final', 4, [7, 3, 0, 7], 'final'),
                 ('post', 'Canceled', 0, None, 'canceled')]
        for state, detail, period, lines, expected in cases:
            with self.subTest(state=state, detail=detail):
                app._espn_cache['raw_events'] = {CFB: [game(state=state, detail=detail,
                                                         period=period, lines=lines)]}
                card = self.data()['teams'][0]
                self.assertEqual(card['game_state'], expected)
                self.assertEqual(card['home_record'], '6-2')
                self.assertEqual(card['away_record'], '6-2')
                if lines is None:
                    self.assertIsNone(card['period_scores'])
                else:
                    self.assertEqual(card['period_scores']['home'][:len(lines)], lines)
        self.network.assert_not_called()

    def test_sport_period_formats_and_baseball_status_reach_api(self):
        cases = [(NFL, 'HOU', [7, 0, 7, 3, 3], ['Q1', 'Q2', 'Q3', 'Q4', 'OT']),
                 ('basketball/nba', 'HOU', [20, 25, 27, 30, 8], ['Q1', 'Q2', 'Q3', 'Q4', 'OT']),
                 ('basketball/mens-college-basketball', 'TA&M', [31, 29, 8], ['H1', 'H2', 'OT']),
                 ('baseball/mlb', 'HOU', [0] * 9 + [1], [str(n) for n in range(1, 11)])]
        for path, abbr, lines, labels in cases:
            with self.subTest(path=path):
                item = game(home=abbr, lines=lines, period=len(lines),
                            detail='Top 10th' if path == 'baseball/mlb' else 'Overtime')
                if path == 'baseball/mlb':
                    item['competitions'][0]['competitors'][0]['statistics'] = [
                        {'name': 'hits', 'displayValue': '9'}, {'name': 'errors', 'displayValue': '0'}]
                app._espn_cache['raw_events'] = {path: [item]}
                card = self.data({'leagues': [path], 'teams': [path + ':' + abbr],
                                  'football_priority': False})['teams'][0]
                self.assertEqual(card['period_scores']['labels'], labels)
                self.assertEqual(card['period_scores']['totals']['home']['score'], '24')
                self.assertEqual(card['home_record'], '6-2')
                if path == 'baseball/mlb':
                    self.assertEqual(card['status'], 'Top 10th')
                    self.assertEqual(card['period_scores']['totals']['home']['hits'], 9)
                    self.assertEqual(card['period_scores']['totals']['home']['errors'], 0)
        self.network.assert_not_called()

    def test_changed_records_replace_previous_records_on_next_api_refresh(self):
        item = game(lines=[7, 3])
        app._espn_cache['raw_events'] = {CFB: [item]}
        self.assertEqual(self.data()['teams'][0]['home_record'], '6-2')
        item['competitions'][0]['competitors'][0]['records'][1]['summary'] = '7-2'
        self.assertEqual(self.data()['teams'][0]['home_record'], '7-2')
        self.network.assert_not_called()

    def test_missing_or_malformed_details_do_not_remove_other_scorecards(self):
        item = game('1')
        item['competitions'][0]['competitors'][0].update(records=None, linescores='invalid')
        item['competitions'][0]['competitors'][1].update(records=[None], linescores=[None, {'value': 'NaN'}])
        app._espn_cache['raw_events'] = {CFB: [item, game('2', lines=[7, 0])]}
        cards = self.data()['teams']
        self.assertEqual(len(cards), 2)
        self.assertIsNone(cards[0]['period_scores'])
        self.assertEqual(cards[0]['home_record'], '')
        self.assertEqual(cards[1]['period_scores']['home'][:2], [7, 0])
        self.network.assert_not_called()

    def test_offline_snapshot_roundtrip_restores_enriched_periods_and_records(self):
        app._espn_cache.update(raw_events={CFB: [game()]}, updated_at='2026-10-19T12:00:00Z')
        for competitor in app._espn_cache['raw_events'][CFB][0]['competitions'][0]['competitors']:
            competitor.pop('records', None)
        compact = {'version': 1, 'entries': [{'key': CFB + ':1', 'fetched': time.time(), 'state': 'post',
                    'data': {'home': {'id': '245', 'record': '7-2', 'periods': {'1': 7, '2': 0, '3': 7, '4': 10}},
                             'away': {'id': '333', 'record': '6-3', 'periods': {'1': 0, '2': 7, '3': 7, '4': 7}}}}]}
        self.assertEqual(app._score_details.restore(compact), 1)
        before = self.data()['teams'][0]
        self.assertTrue(app._save_score_snapshot(force=True))
        saved = json.loads(Path(app.SCORE_CACHE_FILE).read_text())
        self.assertEqual(saved['game_details']['version'], 1)
        app._score_details = app.ScoreDetailsCache()
        app._espn_cache = {'raw_events': {}, 'updated_at': None}
        self.assertTrue(app._load_score_snapshot())
        after = self.data()['teams'][0]
        for key in ('home_record', 'away_record', 'period_scores', 'home_score', 'away_score'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(after['home_record'], '7-2')
        self.assertEqual(after['period_scores']['home'], [7, 0, 7, 10])
        self.assertTrue(self.data()['cache_stale'])
        self.network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
