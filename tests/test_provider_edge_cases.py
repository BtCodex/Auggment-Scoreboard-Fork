"""Additional provider regressions from the final audit."""
import unittest
from unittest.mock import Mock, patch
import test_backend_improvements as fixtures
import app


class ProviderEdgeTests(unittest.TestCase):
    setUp = fixtures.BackendImprovementTests.setUp

    def test_nascar_missing_schedule_never_invents_today_or_loses_identity(self):
        live = Mock()
        live.json.return_value = {'race_id': 42, 'flag_state': 1, 'lap_number': 10,
                                  'laps_in_race': 200, 'vehicles': [{'running_position': 1,
                                  'driver': {'full_name': 'A Driver'}, 'vehicle_number': 7}]}
        schedule = Mock()
        schedule.raise_for_status.side_effect = app.requests.HTTPError('503')
        with patch.object(app, '_NASCAR_SCHEDULE_CACHE', {}), patch.object(
                app.requests, 'get', side_effect=[live, schedule]):
            events = app._fetch_nascar_com_events()
        self.assertEqual(events[0]['id'], 'nascar-42')
        self.assertEqual(events[0]['date'], '')
        self.assertEqual(events[0]['status']['type']['state'], 'in')

    def test_nascar_missing_identity_is_not_accepted_as_a_new_race(self):
        response = Mock()
        response.json.return_value = {'vehicles': [{'running_position': 1}]}
        with patch.object(app.requests, 'get', return_value=response):
            with self.assertRaises(ValueError):
                app._fetch_nascar_com_events()

    def test_unchanged_score_snapshot_does_not_rewrite_the_sd_card(self):
        app._espn_cache = {'raw_events': {'football/nfl': [fixtures.game()]}, 'updated_at': '2026-10-16T12:00:00Z'}
        with patch.object(app.time_module, 'monotonic', return_value=1000):
            self.assertTrue(app._save_score_snapshot())
        original = self.directory.joinpath('score_cache.json').read_bytes()
        app._espn_cache['updated_at'] = '2026-10-16T12:05:00Z'
        with patch.object(app.time_module, 'monotonic', return_value=1301):
            self.assertFalse(app._save_score_snapshot())
        self.assertEqual(self.directory.joinpath('score_cache.json').read_bytes(), original)
        app._espn_cache['raw_events']['football/nfl'][0]['competitions'][0]['competitors'][0]['score'] = '27'
        with patch.object(app.time_module, 'monotonic', return_value=1602):
            self.assertTrue(app._save_score_snapshot())
        self.assertNotEqual(self.directory.joinpath('score_cache.json').read_bytes(), original)

    def test_canceled_pga_and_racing_events_are_not_finals(self):
        app.save_settings({'leagues': ['golf/pga', 'racing/f1']})
        for path in ['golf/pga', 'racing/f1']:
            event = fixtures.game(state='post', detail='Canceled')
            event['competitions'][0]['competitors'] = [
                {'order': 1, 'score': '-4', 'athlete': {'displayName': 'Participant'},
                 'status': {'position': {'displayName': '1'}}}]
            app._espn_cache['raw_events'][path] = [event]
        settings = app.get_settings()
        data = app._build_data_response(settings['leagues'], [], {}, settings['timezone'], settings)
        self.assertEqual(data['golf'][0]['status'], 'Canceled')
        self.assertNotEqual(data['golf'][0]['color_state'], 'final')
        self.assertEqual(data['races'][0]['status'], 'Canceled')
        self.assertNotEqual(data['races'][0]['color_state'], 'final')


if __name__ == '__main__':
    unittest.main()
