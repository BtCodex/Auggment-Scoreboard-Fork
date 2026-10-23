"""Official CFB boundaries and eligibility, independent of provider/network time."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cfb_week


def at(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def payload(week=9, season=2026, kind=2):
    return {'season': {'year': season, 'type': kind}, 'week': {'number': week},
            'leagues': [{'season': {'year': season, 'type': {'type': 3}}, 'calendar': [
                {'label': 'Regular Season', 'value': '2', 'entries': [
                    {'label': 'Week 9', 'value': '9', 'startDate': '2026-10-19T07:00Z', 'endDate': '2026-10-26T06:59Z'},
                    {'label': 'Week 10', 'value': '10', 'startDate': '2026-10-26T07:00Z', 'endDate': '2026-11-02T06:59Z'}]},
                {'label': 'Postseason', 'value': '3', 'entries': [
                    {'label': 'Bowls', 'value': '1', 'startDate': '2026-12-14T08:00Z', 'endDate': '2027-01-22T07:59Z'},
                    {'label': 'CFP', 'value': '999', 'startDate': '2026-12-21T08:00Z', 'endDate': '2027-01-21T07:59Z'}]},
                {'label': 'Off Season', 'value': '4', 'entries': [
                    {'label': 'All Star', 'value': '1', 'startDate': '2027-01-22T08:00Z', 'endDate': '2027-02-28T07:59Z'}]},
            ]}]}


def event(identifier='1', week=9, year=2026, kind=2, date='2026-10-24T17:00Z', home='251', away='145'):
    return {'id': identifier, 'date': date, 'season': {'year': year, 'type': kind}, 'week': {'number': week},
            'competitions': [{'competitors': [{'team': {'id': home}}, {'team': {'id': away}}]}]}


class FootballWeekTests(unittest.TestCase):
    def setUp(self):
        self.current = cfb_week.select_week(payload(), at('2026-10-24T17:00Z'))
        self.catalog = {'cfb': [{'id': '251', 'target': True}, {'id': '145', 'target': True},
                                {'id': '87', 'target': False}]}

    def test_current_calendar_overrides_misleading_league_season_type(self):
        self.assertEqual((self.current['season'], self.current['season_type'], self.current['week']), (2026, 2, 9))
        self.assertEqual(self.current['source'], 'espn_calendar')

    def test_current_clock_selects_new_week_even_when_root_default_is_cached(self):
        selection = cfb_week.select_week(payload(), at('2026-10-26T07:00Z'))
        self.assertEqual(selection['week'], 10)

    def test_minute_precision_calendar_end_includes_whole_minute(self):
        for instant in ('2026-10-26T06:59:00Z', '2026-10-26T06:59:30Z', '2026-10-26T06:59:59.999999Z'):
            self.assertEqual(cfb_week.select_week(payload(), at(instant))['week'], 9)

    def test_regular_to_postseason_uses_official_season_type(self):
        selection = cfb_week.select_week(payload(kind=3), at('2026-12-14T09:00Z'))
        self.assertEqual((selection['season_type'], selection['week']), (3, 1))

    def test_overlapping_cfp_subview_does_not_displace_complete_bowl_week(self):
        selection = cfb_week.select_week(payload(kind=3), at('2026-12-25T12:00Z'))
        self.assertEqual((selection['label'], selection['week']), ('Bowls', 1))

    def test_january_retains_previous_football_season_year(self):
        selection = cfb_week.select_week(payload(kind=3), at('2027-01-10T12:00Z'))
        self.assertEqual((selection['season'], selection['season_type']), (2026, 3))

    def test_offseason_and_preseason_gap_never_pick_upcoming_week(self):
        for instant in ('2026-07-01T12:00Z', '2027-02-01T12:00Z'):
            selection = cfb_week.select_week(payload(kind=4), at(instant))
            self.assertEqual(selection['state'], 'offseason')
            self.assertIsNone(selection['week'])

    def test_offseason_only_calendar_is_not_mistaken_for_live_all_star_week(self):
        source = payload(kind=4)
        source['leagues'][0]['calendar'] = source['leagues'][0]['calendar'][2:]
        self.assertEqual(cfb_week.select_week(source, at('2027-02-01T12:00Z'))['state'], 'offseason')

    def test_authoritative_root_week_fallback_when_calendar_absent(self):
        source = payload()
        source.pop('leagues')
        selection = cfb_week.select_week(source, at('2026-10-24T12:00Z'))
        self.assertEqual((selection['week'], selection['source']), (9, 'espn_scoreboard'))

    def test_malformed_or_ambiguous_metadata_fails_without_guessing_dates(self):
        bad_calendar = payload()
        bad_calendar['leagues'][0]['calendar'][0]['entries'].append({
            'label': 'Other', 'value': '11', 'startDate': '2026-10-24T07:00Z', 'endDate': '2026-10-25T07:00Z'})
        for source in ({}, {'season': None}, {'season': {'year': True, 'type': 2}}, bad_calendar,
                       {'season': {'year': 2026, 'type': 2}, 'week': {'number': 9},
                        'leagues': [{'calendar': [{'value': '2', 'entries': [{'value': '9', 'startDate': 'bad'}]}]}]}):
            with self.subTest(source=source), self.assertRaises(ValueError):
                cfb_week.select_week(source, at('2026-10-24T12:00Z'))

    def test_old_default_season_is_not_treated_as_current_offseason(self):
        with self.assertRaisesRegex(ValueError, 'stale football season'):
            cfb_week.select_week(payload(season=2024), at('2026-10-24T12:00Z'))

    def test_only_exact_week_year_and_season_type_match(self):
        self.assertTrue(cfb_week.matches_week(event(), self.current))
        for game in (event(week=10), event(year=2025), event(kind=3), {}, None, {'season': 'bad'}):
            self.assertFalse(cfb_week.matches_week(game, self.current))
        self.assertFalse(cfb_week.matches_week(event(), {'state': 'active'}))

    def test_major_team_against_fcs_or_group_of_five_and_notre_dame_qualify(self):
        for home, away in (('251', '999999'), ('999999', '145'), ('87', '999999')):
            self.assertTrue(cfb_week.eligible(event(home=home, away=away), self.catalog))
        self.assertFalse(cfb_week.eligible(event(home='999', away='998'), self.catalog))

    def test_missing_or_malformed_competitors_are_not_eligible(self):
        for game in (None, {}, {'competitions': None}, {'competitions': 3},
                     {'competitions': [None]}, {'competitions': [{'competitors': None}]},
                     {'competitions': [{'competitors': 42}]}, {'competitions': [{'competitors': ['bad']}]}):
            self.assertFalse(cfb_week.eligible(game, self.catalog))

    def test_sort_uses_actual_timestamp_offsets_then_lexical_event_id(self):
        games = [event('2', date='2026-10-24T12:00-05:00'), event('10', date='2026-10-24T17:00Z'),
                 event('earlier', date='2026-10-24T16:00Z'), event('unknown', date='bad')]
        self.assertEqual([game['id'] for game in sorted(games, key=cfb_week.sort_key)], ['earlier', '10', '2', 'unknown'])

    def test_snapshot_validation_normalizes_numeric_strings_and_bounds_fields(self):
        saved = {**self.current, 'season': '2026', 'season_type': '2', 'week': '9'}
        restored = cfb_week.validate_saved_week(saved)
        self.assertTrue(cfb_week.matches_week(event(), restored))
        self.assertEqual(restored['season'], 2026)
        for changes in ({'week': True}, {'season': None}, {'source': 'invented'}, {'start': 'bad'},
                        {'state': 'active', 'week': None}, {'state': 'offseason', 'week': 9}):
            self.assertIsNone(cfb_week.validate_saved_week({**self.current, **changes}))

    def test_metadata_retains_calendar_without_large_unused_payloads(self):
        source = payload()
        source.update(news=['unused'], events=[event()])
        retained = cfb_week.metadata(source)
        self.assertNotIn('news', retained)
        self.assertNotIn('events', retained)
        self.assertEqual(cfb_week.select_week(retained, at('2026-10-24T12:00Z')), self.current)
        source['leagues'][0]['calendar'][0]['entries'] *= 100
        self.assertLessEqual(len(cfb_week.metadata(source)['leagues'][0]['calendar'][0]['entries']), 100)


if __name__ == '__main__':
    unittest.main()
