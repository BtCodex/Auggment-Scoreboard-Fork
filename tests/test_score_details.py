"""Deterministic score detail parsing/cache regressions; no provider requests."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score_details import ScoreDetailsCache


NFL = 'football/nfl'
MLB = 'baseball/mlb'


def competitor(team_id, periods=None, record='8-2', score='24'):
    result = {'team': {'id': team_id}, 'score': score}
    if periods is not None:
        result['linescores'] = [{'value': value} for value in periods]
    if record is not None:
        result['records'] = [{'name': 'overall', 'type': 'total', 'summary': record}]
    return result


def event(event_id='123', state='in', period=2, detail='Q2 4:20'):
    return {'id': event_id, 'status': {'period': period, 'type': {
        'state': state, 'shortDetail': detail}}}


def summary(home=None, away=None, teams=None):
    home = deepcopy(home or competitor('1', [7, 7, 3, 7], '9-2'))
    away = deepcopy(away or competitor('2', [0, 7, 7, 7], '6-5'))
    home['homeAway'], away['homeAway'] = 'home', 'away'
    return {'header': {'competitions': [{'competitors': [away, home]}]},
            'boxscore': {'teams': teams or []}}


class Response:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        self.closed = True


class ScoreDetailTests(unittest.TestCase):
    def setUp(self):
        self.now = 10000
        self.request = Mock(return_value=Response(summary()))
        self.cache = ScoreDetailsCache(self.request, clock=lambda: self.now)
        self.home = competitor('1', [7, 0], '8-2', '7')
        self.away = competitor('2', [0, 3], '6-4', '3')

    def get(self, path=NFL, game=None, home=None, away=None):
        return self.cache.get(path, game or event(),
                              self.home if home is None else home,
                              self.away if away is None else away)

    def demand(self, game=None, path=NFL):
        return self.get(path, game, competitor('1', record=None), competitor('2', record=None))

    def test_football_regulation_preserves_unplayed_periods_and_real_zero(self):
        details = self.get()
        self.assertEqual(details['period_scores']['labels'], ['Q1', 'Q2', 'Q3', 'Q4'])
        self.assertEqual(details['period_scores']['home'], [7, 0, None, None])
        self.assertEqual(details['period_scores']['away'], [0, 3, None, None])
        self.assertEqual(details['period_scores']['totals']['home']['score'], '7')
        self.assertEqual(details['home_record'], '8-2')
        self.request.assert_not_called()

    def test_nfl_and_cfb_multiple_overtimes(self):
        for path in (NFL, 'football/college-football'):
            with self.subTest(path=path):
                details = self.get(path, event(state='post', period=6),
                                   competitor('1', [7, 0, 0, 7, 3, 7]),
                                   competitor('2', [0, 7, 7, 0, 3, 0]))
                self.assertEqual(details['period_scores']['labels'],
                                 ['Q1', 'Q2', 'Q3', 'Q4', 'OT', '2OT'])

    def test_nba_and_womens_college_basketball_use_quarters(self):
        for path in ('basketball/nba', 'basketball/womens-college-basketball'):
            with self.subTest(path=path):
                details = self.get(path, home=competitor('1', [30, 25, 24, 21, 10]))
                self.assertEqual(details['period_scores']['labels'], ['Q1', 'Q2', 'Q3', 'Q4', 'OT'])

    def test_mens_college_basketball_uses_halves_and_overtime(self):
        details = self.get('basketball/mens-college-basketball',
                           home=competitor('1', [35, 40, 8, 11]))
        self.assertEqual(details['period_scores']['labels'], ['H1', 'H2', 'OT', '2OT'])

    def test_baseball_extra_innings_and_runs_hits_errors(self):
        home = competitor('1', [0, 0, 0, 2, 0, 0, 0, 0, 0, 1, 2], '100-62', '5')
        home['statistics'] = [{'name': 'hits', 'displayValue': '9'},
                              {'abbreviation': 'E', 'displayValue': '0'}]
        details = self.get(MLB, event(period=11), home=home)
        table = details['period_scores']
        self.assertEqual(table['labels'], [str(index) for index in range(1, 12)])
        self.assertEqual(table['totals']['home'], {'score': '5', 'hits': 9, 'errors': 0})
        self.assertEqual(details['home_record'], '100-62')
        self.assertIsNone(table['totals']['away']['hits'])

    def test_unplayed_bottom_ninth_is_missing_not_zero(self):
        details = self.get(MLB, event(state='post', period=9),
                           home=competitor('1', [0] * 8, '91-71', '2'))
        self.assertEqual(len(details['period_scores']['home']), 9)
        self.assertIsNone(details['period_scores']['home'][-1])

    def test_mlb_unbatted_x_with_numeric_zero_remains_missing(self):
        home = competitor('1', [0] * 8, '91-71', '2')
        home['linescores'].append({'value': 0, 'displayValue': 'X'})
        table = self.get(MLB, event(state='post', period=9), home=home)['period_scores']
        self.assertIsNone(table['home'][8])

    def test_mlb_unbatted_x_overrides_older_cached_numeric_zero(self):
        self.request.return_value = Response(summary(
            home=competitor('1', [0] * 9), away=competitor('2', [0] * 9)))
        self.demand(path=MLB)
        self.cache.refresh()
        home = competitor('1', [0] * 8)
        home['linescores'].append({'value': 0, 'displayValue': 'X'})
        table = self.get(MLB, event(state='post', period=9), home=home)['period_scores']
        self.assertIsNone(table['home'][8])

    def test_missing_periods_omit_table_instead_of_inventing_values(self):
        details = self.get(home=competitor('1', record=None, score=None),
                           away=competitor('2', record=None, score=None))
        self.assertIsNone(details['period_scores'])
        self.assertEqual(details['home_record'], '')
        self.request.assert_not_called()

    def test_malformed_period_values_are_missing_and_explicit_periods_respected(self):
        self.home['linescores'] = [None, {'period': 3, 'displayValue': '7'},
                                   {'period': 4, 'value': 'NaN'}, {'period': -1, 'value': 7},
                                   {'period': 5, 'value': True}, {'period': 6, 'value': -1}]
        self.away['linescores'] = 'invalid'
        details = self.get()
        self.assertEqual(details['period_scores']['home'], [None, None, 7, None])
        self.assertEqual(details['period_scores']['away'], [None] * 4)

    def test_score_dictionary_and_missing_totals(self):
        self.home['score'] = {'displayValue': '14'}
        self.away['score'] = None
        totals = self.get()['period_scores']['totals']
        self.assertEqual(totals['home']['score'], '14')
        self.assertEqual(totals['away']['score'], '—')

    def test_overall_record_preferred_over_home_away_or_conference(self):
        self.home['records'] = [{'type': 'home', 'summary': '5-0'},
                                {'type': 'vsconf', 'summary': '3-1'},
                                {'name': 'overall', 'summary': '100-62'}]
        self.assertEqual(self.get()['home_record'], '100-62')
        self.home['records'] = [{'name': 'Home', 'summary': '5-0'}]
        self.assertEqual(self.get()['home_record'], '')

    def test_summary_style_record_and_ties(self):
        self.home.pop('records')
        self.home['record'] = [{'type': 'total', 'summary': '8-2-1'}]
        self.assertEqual(self.get()['home_record'], '8-2-1')

    def test_scheduled_games_show_records_but_never_fetch_summaries(self):
        details = self.demand(event(state='pre', period=0, detail='Scheduled'))
        self.assertIsNone(details['period_scores'])
        self.assertEqual(self.cache.refresh(), 0)
        self.request.assert_not_called()

    def test_live_halftime_overtime_and_final_games_register_missing_details(self):
        for detail, state in [('Q1 2:00', 'in'), ('Halftime', 'in'), ('2OT', 'in'), ('Final', 'post')]:
            with self.subTest(detail=detail):
                cache = ScoreDetailsCache(self.request, clock=lambda: self.now)
                cache.get(NFL, event(state=state, detail=detail), {}, {})
                self.assertEqual(cache.refresh(), 1)

    def test_canceled_postponed_and_delayed_games_never_request_summaries(self):
        for detail in ('Canceled', 'Postponed', 'Weather Delay', 'Suspended'):
            self.demand(event(state='post', detail=detail))
            self.assertEqual(self.cache.refresh(), 0)
        self.request.assert_not_called()

    def test_canceling_previously_live_game_clears_pending_demand(self):
        self.demand()
        self.demand(event(state='post', detail='Canceled'))
        self.assertEqual(self.cache.refresh(), 0)

    def test_complete_scoreboard_details_need_no_summary_request(self):
        self.get(game=event(state='post', period=4),
                 home=competitor('1', [7, 7, 0, 0]), away=competitor('2', [0, 3, 7, 0]))
        self.assertEqual(self.cache.refresh(), 0)

    def test_complete_scoreboard_details_clear_obsolete_summary_demand(self):
        self.demand()
        self.get(game=event(state='post', period=4),
                 home=competitor('1', [7, 7, 0, 0]), away=competitor('2', [0, 3, 7, 0]))
        self.assertEqual(self.cache.refresh(), 0)

    def test_partial_final_details_register_summary_demand(self):
        self.get(game=event(state='post', period=4))
        self.assertEqual(self.cache.refresh(), 1)

    def test_get_never_networks_and_duplicate_favorites_share_one_fetch(self):
        self.demand()
        self.demand()
        self.request.assert_not_called()
        self.assertEqual(self.cache.refresh(), 1)
        self.request.assert_called_once()
        args, kwargs = self.request.call_args
        self.assertTrue(args[0].endswith('/football/nfl/summary'))
        self.assertEqual(kwargs['params'], {'event': '123'})
        self.assertEqual(kwargs['timeout'], (3, 5))
        self.assertTrue(kwargs['stream'])

    def test_cached_summary_enriches_missing_details_but_current_total_and_period_win(self):
        self.demand()
        self.cache.refresh()
        details = self.get(home=competitor('1', [14], record=None, score='31'),
                           away=competitor('2', record=None, score='21'))
        self.assertEqual(details['home_record'], '9-2')
        self.assertEqual(details['period_scores']['home'], [14, 7, 3, 7])
        self.assertEqual(details['period_scores']['totals']['home']['score'], '31')

    def test_current_scoreboard_record_overrides_cached_record(self):
        self.demand()
        self.cache.refresh()
        self.assertEqual(self.get()['home_record'], '8-2')

    def test_summary_from_different_team_does_not_leak_into_card(self):
        self.demand()
        self.cache.refresh()
        details = self.get(home=competitor('99', record=None))
        self.assertEqual(details['home_record'], '')
        self.assertEqual(details['period_scores']['home'], [None] * 4)

    def test_mlb_boxscore_team_stats_join_by_id(self):
        self.request.return_value = Response(summary(teams=[
            {'team': {'id': '2'}, 'statistics': [{'name': 'hits', 'displayValue': '6'},
                                                {'name': 'errors', 'displayValue': '1'}]},
            {'team': {'id': '1'}, 'statistics': [{'name': 'hits', 'displayValue': '9'},
                                                {'name': 'errors', 'displayValue': '0'}]}]))
        self.demand(path=MLB)
        self.cache.refresh()
        totals = self.get(MLB)['period_scores']['totals']
        self.assertEqual((totals['home']['hits'], totals['home']['errors']), (9, 0))
        self.assertEqual((totals['away']['hits'], totals['away']['errors']), (6, 1))

    def test_live_cache_ttl_60_seconds(self):
        self.demand()
        self.assertEqual(self.cache.refresh(), 1)
        self.now += 59
        self.assertEqual(self.cache.refresh(), 0)
        self.now += 1
        self.assertEqual(self.cache.refresh(), 1)

    def test_final_cache_ttl_six_hours_with_renewed_demand(self):
        final = event(state='post', detail='Final')
        self.demand(final)
        self.cache.refresh()
        self.now += 21599
        self.demand(final)
        self.assertEqual(self.cache.refresh(), 0)
        self.now += 1
        self.assertEqual(self.cache.refresh(), 1)

    def test_live_to_final_transition_fetches_final_details_without_six_hour_wait(self):
        self.demand()
        self.cache.refresh()
        self.now += 1
        self.demand(event(state='post', detail='Final'))
        self.assertEqual(self.cache.refresh(), 1)
        self.assertEqual(self.cache.refresh(), 0)
        snapshot = self.cache.snapshot()
        self.assertEqual(snapshot['entries'][0]['state'], 'post')

    def test_restored_live_summary_is_refreshed_on_final_transition(self):
        self.demand()
        self.cache.refresh()
        restored = ScoreDetailsCache(self.request, clock=lambda: self.now)
        restored.restore(self.cache.snapshot())
        restored.get(NFL, event(state='post', detail='Final'), {}, {})
        self.assertEqual(restored.refresh(), 1)

    def test_unviewed_game_demand_expires(self):
        self.demand()
        self.now += 901
        self.assertEqual(self.cache.refresh(), 0)
        self.request.assert_not_called()

    def test_request_budget_two_per_pass_and_no_duplicate_key(self):
        for game_id in range(5):
            self.demand(event(str(game_id)))
        self.assertEqual(self.cache.refresh(), 2)
        self.assertEqual(self.cache.refresh(), 2)
        self.assertEqual(self.cache.refresh(), 1)
        self.assertEqual(self.request.call_count, 5)

    def test_eight_live_games_all_refresh_despite_stable_browser_request_order(self):
        for initial_time in (0, 10000):
            with self.subTest(initial_time=initial_time):
                self.now = initial_time
                attempts = {str(game_id): [] for game_id in range(8)}

                def fetch(*args, **kwargs):
                    attempts[kwargs['params']['event']].append(self.now)
                    return Response(summary())

                cache = ScoreDetailsCache(fetch, clock=lambda: self.now)
                for tick in range(16):
                    self.now = initial_time + tick * 30
                    for game_id in range(8):
                        cache.get(NFL, event(str(game_id)), {}, {})
                    self.assertEqual(cache.refresh(), 2)
                    if tick == 3:
                        self.assertTrue(all(times for times in attempts.values()))
                self.assertEqual([len(times) for times in attempts.values()], [4] * 8)
                for times in attempts.values():
                    self.assertEqual([later - earlier for earlier, later in zip(times, times[1:])],
                                     [120] * 3)

    def test_failed_first_game_does_not_starve_other_games(self):
        attempts = {str(game_id): 0 for game_id in range(8)}

        def fetch(*args, **kwargs):
            game_id = kwargs['params']['event']
            attempts[game_id] += 1
            if game_id == '0':
                raise requests.Timeout('first game unavailable')
            return Response(summary())

        cache = ScoreDetailsCache(fetch, clock=lambda: self.now)
        for tick in range(5):
            self.now += 30
            for game_id in range(8):
                cache.get(NFL, event(str(game_id)), {}, {})
            self.assertLessEqual(cache.refresh(), 2)
        self.assertTrue(all(count for count in attempts.values()))
        self.assertEqual(attempts['0'], 1)

    def test_failures_back_off_and_recover_while_retaining_good_details(self):
        self.demand()
        self.cache.refresh()
        self.now += 60
        self.request.side_effect = requests.Timeout('offline')
        self.assertEqual(self.cache.refresh(), 1)
        self.assertEqual(self.demand()['home_record'], '9-2')
        self.now += 299
        self.assertEqual(self.cache.refresh(), 0)
        self.now += 1
        self.assertEqual(self.cache.refresh(), 1)
        self.now += 599
        self.demand()
        self.assertEqual(self.cache.refresh(), 0)
        self.now += 1
        self.request.side_effect = None
        self.assertEqual(self.cache.refresh(), 1)
        self.now += 60
        self.assertEqual(self.cache.refresh(), 1)

    def test_backoff_has_one_hour_ceiling(self):
        self.request.side_effect = requests.ConnectionError('offline')
        for expected in (300, 600, 1200, 2400, 3600, 3600):
            self.demand()
            self.assertEqual(self.cache.refresh(), 1)
            self.now += expected - 1
            self.demand()
            self.assertEqual(self.cache.refresh(), 0)
            self.now += 1

    def test_malformed_response_is_failed_request_and_response_closed(self):
        for payload in ([], {}, {'header': {'competitions': 'invalid'}}, {'header': None}):
            with self.subTest(payload=payload):
                response = Response(payload)
                cache = ScoreDetailsCache(lambda *args, **kwargs: response, clock=lambda: self.now)
                cache.get(NFL, event(), {}, {})
                self.assertEqual(cache.refresh(), 1)
                self.assertEqual(cache.refresh(), 0)
                self.assertTrue(response.closed)
                self.assertIsNone(cache.get(NFL, event(), {}, {})['period_scores'])

    def test_oversized_summary_is_rejected_and_closed(self):
        response = Response({})
        response.body = b' ' * (2 * 1024 * 1024 + 1)
        self.request.return_value = response
        self.demand()
        self.assertEqual(self.cache.refresh(), 1)
        self.assertEqual(self.cache.snapshot()['entries'], [])
        self.assertTrue(response.closed)

    def test_invalid_event_or_unsupported_path_cannot_construct_summary_url(self):
        for path, game_id in [(NFL, '../../secret'), (NFL, '1&event=2'),
                              ('football/arbitrary', '123'), ('golf/pga', '123')]:
            self.demand(event(game_id), path=path)
        self.assertEqual(self.cache.refresh(), 0)
        self.request.assert_not_called()

    def test_entry_and_demand_counts_are_bounded(self):
        for game_id in range(200):
            self.demand(event(str(game_id)))
        self.assertEqual(len(self.cache._demand), 128)
        for _ in range(64):
            self.cache.refresh()
        self.assertEqual(len(self.cache.snapshot()['entries']), 128)
        for game_id in range(200, 210):
            self.demand(event(str(game_id)))
        for _ in range(5):
            self.cache.refresh()
        self.assertEqual(len(self.cache.snapshot()['entries']), 128)

    def test_snapshot_roundtrip_preserves_offline_details_not_raw_summary(self):
        payload = summary()
        payload['plays'] = ['large play body'] * 1000
        self.request.return_value = Response(payload)
        self.demand()
        self.cache.refresh()
        snapshot = self.cache.snapshot()
        self.assertLess(len(json.dumps(snapshot)), 2000)
        self.assertNotIn('plays', json.dumps(snapshot))
        restored = ScoreDetailsCache(self.request, clock=lambda: self.now)
        self.assertEqual(restored.restore(json.loads(json.dumps(snapshot))), 1)
        self.assertEqual(restored.get(NFL, event(), {}, {})['home_record'], '9-2')
        self.assertEqual(restored.refresh(), 0)
        snapshot['entries'][0]['data']['home']['record'] = '0-0'
        self.assertEqual(restored.get(NFL, event(), {}, {})['home_record'], '9-2')

    def test_restore_rejects_malformed_and_unbounded_fields(self):
        for invalid in (None, [], {'version': 2}, {'version': 1, 'entries': {}},
                        {'version': 1, 'entries': [None, {'key': 'bad', 'fetched': 1}]}):
            self.assertEqual(self.cache.restore(invalid), 0)
        source = {'key': NFL + ':123', 'fetched': self.now,
                  'data': {'home': {'id': '1', 'record': '<script>', 'periods': {
                      '1': 7, '2': False, '3': 'NaN', '65': 7, '9' * 5000: 3},
                      'hits': -1, 'errors': '0'}}}
        self.assertEqual(self.cache.restore({'version': 1, 'entries': [source]}), 1)
        details = self.get(home=competitor('1', record=None))
        self.assertEqual(details['home_record'], '')
        self.assertEqual(details['period_scores']['home'], [7, None, None, None])

    def test_restore_future_clock_retains_data_but_allows_refetch(self):
        self.demand()
        self.cache.refresh()
        snapshot = self.cache.snapshot()
        snapshot['entries'][0]['fetched'] = self.now + 999999
        restored = ScoreDetailsCache(self.request, clock=lambda: self.now)
        restored.restore(snapshot)
        self.assertEqual(restored.get(NFL, event(), {}, {})['home_record'], '9-2')
        self.assertEqual(restored.refresh(), 1)

    def test_period_payload_size_is_bounded(self):
        details = self.get(MLB, home=competitor('1', [1] * 5000))
        self.assertEqual(len(details['period_scores']['labels']), 64)


if __name__ == '__main__':
    unittest.main()
