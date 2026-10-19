"""Explicit AP poll parsing and bounded retries; no network or device access."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['WERKZEUG_RUN_MAIN'] = 'false'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def poll_payload():
    """Small example matching ESPN's public rankings API schema."""
    return {
        'latestSeason': {'year': 2026},
        'rankings': [
            {'type': 'usa', 'name': 'AFCA Coaches Poll', 'season': {'year': 2026},
             'ranks': [{'current': 1, 'team': {'id': '245'}}]},
            {'type': 'ap', 'id': '1', 'name': 'AP Top 25',
             'season': {'year': 2026}, 'date': '2026-10-18T07:00Z',
             'lastUpdated': '2026-10-18T21:15Z',
             'ranks': [{'current': 4, 'team': {'id': '245', 'abbreviation': 'TA&M'}},
                       {'current': 25, 'team': {'id': '333', 'abbreviation': 'ALA'}}]},
        ],
    }


class ApPollTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.snapshot_file = Path(directory.name) / 'score_cache.json'
        for name, value in {
            '_espn_cache': {'raw_events': {}, 'updated_at': None},
            '_ap_poll_request': {'retry_at': 0, 'failures': 0},
            '_cache_errors': {}, '_last_snapshot_write': 0,
            '_last_snapshot_fingerprint': None,
            'SCORE_CACHE_FILE': str(self.snapshot_file),
        }.items():
            patcher = patch.object(app, name, deepcopy(value))
            patcher.start()
            self.addCleanup(patcher.stop)
        clock_patch = patch.object(app.time_module, 'monotonic', return_value=10000)
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        network_patch = patch.object(app.requests, 'get')
        self.network = network_patch.start()
        self.addCleanup(network_patch.stop)
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = poll_payload()
        self.network.return_value = response

    def test_explicit_ap_poll_selected_instead_of_coaches_or_curated_rank(self):
        parsed = app._parse_ap_poll(poll_payload())
        self.assertEqual(parsed['ranks'], {'245': 4, '333': 25})
        self.assertEqual(parsed['season'], 2026)
        self.assertEqual(parsed['date'], '2026-10-18T07:00Z')
        self.assertIsNotNone(datetime.fromisoformat(parsed['updated_at']).tzinfo)

    def test_missing_ap_or_bad_container_cannot_be_mislabeled_ap(self):
        for payload in (None, [], {}, {'rankings': {}},
                        {'rankings': [poll_payload()['rankings'][0]]}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    app._parse_ap_poll(payload)

    def test_malformed_poll_metadata_is_rejected(self):
        for replacement in ({'season': {}}, {'season': {'year': True}},
                            {'season': {'year': '2026'}}, {'season': {'year': 1800}},
                            {'ranks': None}, {'ranks': []}, {'ranks': ['broken']}):
            payload = poll_payload()
            payload['rankings'][1].update(replacement)
            with self.subTest(replacement=replacement):
                with self.assertRaises(ValueError):
                    app._parse_ap_poll(payload)

    def test_bad_rows_do_not_drop_valid_neighbor_or_create_rank_zero(self):
        payload = poll_payload()
        payload['rankings'][1]['ranks'].extend([
            None, {}, {'current': True, 'team': {'id': '1'}},
            {'current': 0, 'team': {'id': '2'}},
            {'current': 26, 'team': {'id': '3'}},
            {'current': '5', 'team': {'id': '4'}},
            {'current': 5, 'team': {'id': 'not-a-provider-id'}},
            {'current': 5, 'team': []},
        ])
        self.assertEqual(app._parse_ap_poll(payload)['ranks'], {'245': 4, '333': 25})

    def test_rank_lookup_uses_provider_team_id_and_matching_season(self):
        app._espn_cache['ap_poll'] = app._parse_ap_poll(poll_payload())
        competitor = {'team': {'id': '245', 'abbreviation': 'OTHER'},
                      'curatedRank': {'current': 1}}
        self.assertEqual(app._ap_rank(competitor, {'season': {'year': 2026}}), 4)
        self.assertIsNone(app._ap_rank(competitor, {'season': {'year': 2025}}))
        self.assertIsNone(app._ap_rank(competitor, {}))
        self.assertIsNone(app._ap_rank({'team': {'id': '999', 'abbreviation': 'TA&M'},
                                     'curatedRank': {'current': 2}},
                                    {'season': {'year': 2026}}))

    def test_missing_poll_does_not_fall_back_to_unidentified_rank(self):
        competitor = {'team': {'id': '245'}, 'curatedRank': {'current': 4}}
        self.assertIsNone(app._ap_rank(competitor, {'season': {'year': 2026}}))

    def test_refresh_success_is_shared_for_one_hour(self):
        self.assertTrue(app._refresh_ap_poll())
        self.assertEqual(app._espn_cache['ap_poll']['ranks']['245'], 4)
        self.assertEqual(app._ap_poll_request['failures'], 0)
        self.assertEqual(app._ap_poll_request['retry_at'], 13600)
        self.assertFalse(app._refresh_ap_poll())
        self.assertEqual(self.network.call_count, 1)
        self.clock.return_value = 13600
        self.assertTrue(app._refresh_ap_poll())
        self.assertEqual(self.network.call_count, 2)
        self.assertIn('/college-football/rankings', self.network.call_args.args[0])
        self.assertEqual(self.network.call_args.kwargs.get('timeout'), (3, 8))

    def test_timeout_retains_last_good_poll_and_recovers(self):
        retained = app._parse_ap_poll(poll_payload())
        app._espn_cache['ap_poll'] = deepcopy(retained)
        self.network.side_effect = app.requests.Timeout('offline')
        self.assertFalse(app._refresh_ap_poll())
        self.assertEqual(app._espn_cache['ap_poll'], retained)
        self.assertEqual(app._ap_poll_request['retry_at'], 10300)
        self.assertFalse(app._refresh_ap_poll())
        self.assertEqual(self.network.call_count, 1)
        self.clock.return_value = 10300
        self.network.side_effect = None
        self.assertTrue(app._refresh_ap_poll())
        self.assertEqual(app._ap_poll_request['failures'], 0)

    def test_repeated_failures_back_off_to_one_hour(self):
        self.network.side_effect = app.requests.ConnectionError('no internet')
        now = 10000
        for expected_delay in (300, 600, 1200, 2400, 3600, 3600):
            self.clock.return_value = now
            self.assertFalse(app._refresh_ap_poll())
            self.assertEqual(app._ap_poll_request['retry_at'], now + expected_delay)
            now += expected_delay
        self.assertEqual(self.network.call_count, 6)

    def test_provider_rate_limit_retry_after_is_respected(self):
        response = Mock(status_code=429, headers={'Retry-After': '7200'})
        response.raise_for_status.side_effect = app.requests.HTTPError('rate limited', response=response)
        self.network.return_value = response
        self.assertFalse(app._refresh_ap_poll())
        self.assertGreaterEqual(app._ap_poll_request['retry_at'], 17200)

    def test_malformed_success_response_retains_last_good_data(self):
        retained = app._parse_ap_poll(poll_payload())
        app._espn_cache['ap_poll'] = deepcopy(retained)
        self.network.return_value.json.return_value = {'rankings': []}
        self.assertFalse(app._refresh_ap_poll())
        self.assertEqual(app._espn_cache['ap_poll'], retained)
        self.assertEqual(app._ap_poll_request['retry_at'], 10300)

    def test_snapshot_round_trip_preserves_verified_poll_and_fetch_timestamp(self):
        poll = app._parse_ap_poll(poll_payload())
        poll['updated_at'] = '2026-10-18T21:30:00+00:00'
        event = {'id': 'college', 'competitions': [{'competitors': []}]}
        app._espn_cache.update(raw_events={'football/college-football': [event]},
                               updated_at='2026-10-18T21:30:00+00:00', ap_poll=poll)
        self.assertTrue(app._save_score_snapshot())
        app._espn_cache.clear()
        app._espn_cache.update(raw_events={}, updated_at=None)
        self.assertTrue(app._load_score_snapshot())
        self.assertEqual(app._espn_cache['ap_poll'], poll)
        self.assertEqual(app._ap_rank({'team': {'id': '245'}},
                                     {'season': {'year': 2026}}), 4)
        self.assertIn('awaiting provider refresh', app._cache_errors['football/college-football'])

    def test_malformed_saved_poll_does_not_discard_saved_scores(self):
        for bad_poll in ({'ranks': None}, {'ranks': []},
                         {'ranks': {'245': 4}, 'season': 2026, 'updated_at': 'broken'},
                         {'ranks': {'245': 99}, 'season': 2026,
                          'updated_at': '2026-10-18T21:30:00+00:00'}):
            with self.subTest(bad_poll=bad_poll):
                self.snapshot_file.write_text(json.dumps({
                    'raw_events': {'football/nfl': [{'id': 'preserve', 'competitions': [{}]}]},
                    'updated_at': '2026-10-18T21:30:00+00:00', 'ap_poll': bad_poll}))
                app._espn_cache.clear()
                app._espn_cache.update(raw_events={}, updated_at=None)
                self.assertTrue(app._load_score_snapshot())
                self.assertEqual(app._espn_cache['raw_events']['football/nfl'][0]['id'], 'preserve')
                self.assertNotIn('ap_poll', app._espn_cache)

    def test_rankings_outage_does_not_interrupt_successful_score_refresh(self):
        college = 'football/college-football'
        event = {'id': 'live-score', 'competitions': [{}]}
        self.network.side_effect = app.requests.Timeout('rankings unavailable')
        settings = {'leagues': [college], 'football_priority': False, 'timezone': 'America/Chicago'}
        with patch.object(app, 'get_settings', return_value=settings), \
             patch.object(app, '_fetch_league_raw', return_value=[event]), \
             patch.object(app, '_requested_leagues', {}), \
             patch.object(app, '_last_refresh_attempt', 0):
            self.assertTrue(app._refresh_espn_cache())
        self.assertEqual(app._espn_cache['raw_events'][college], [event])
        self.assertNotIn(college, app._cache_errors)
        self.assertEqual(app._ap_poll_request['failures'], 1)


if __name__ == '__main__':
    unittest.main()
