"""Current-play widgets never infer state from absent or historical data."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score_details import ScoreDetailsCache


NFL = 'football/nfl'
CFB = 'football/college-football'
MLB = 'baseball/mlb'


def team(team_id, abbreviation, score='14'):
    return {'team': {'id': team_id, 'abbreviation': abbreviation}, 'score': score,
            'records': [{'name': 'overall', 'summary': '4-2'}]}


def game(situation=None, period=3, clock='4:20', detail='4:20 - 3rd', state='in'):
    status = {'period': period, 'displayClock': clock,
              'type': {'state': state, 'name': 'STATUS_IN_PROGRESS',
                       'detail': detail, 'shortDetail': detail}}
    return {'id': '123', 'status': status,
            'competitions': [{'situation': deepcopy(situation or {}),
                              'status': deepcopy(status)}]}


def football_situation(**changes):
    return {'possession': '2', 'possessionText': 'LSU 34', 'down': 3,
            'distance': 7, 'downDistanceText': '3rd & 7 at LSU 34', **changes}


def baseball_situation(**changes):
    return {'onFirst': False, 'onSecond': True, 'onThird': False, 'outs': 1, **changes}


class LiveStateTests(unittest.TestCase):
    def setUp(self):
        self.cache = ScoreDetailsCache()
        self.home = team('1', 'LSU', '21')
        self.away = team('2', 'TA&M', '14')

    def get(self, path=NFL, event=None):
        return self.cache.get(path, event or game(football_situation()), self.home, self.away)

    def test_both_football_leagues_use_current_scoreboard_state(self):
        for path in (NFL, CFB):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)['football_tracker'], {
                    'possession': 'away', 'team': 'TA&M', 'position': 66, 'direction': 'right',
                    'label': '3rd & 7 at LSU 34', 'quarter': 'Q3', 'clock': '4:20',
                    'red_zone': False, 'goal_to_go': False})
                self.assertIsNone(self.get(path)['baseball_tracker'])

    def test_own_side_position_is_normalized_toward_opposing_goal(self):
        tracker = self.get(event=game(football_situation(possession='1')))['football_tracker']
        self.assertEqual(tracker['position'], 34)
        self.assertEqual(tracker['possession'], 'home')
        self.assertEqual(tracker['team'], 'LSU')

    def test_possession_changes_reposition_ball_without_reusing_old_state(self):
        first = self.get()['football_tracker']
        second = self.get(event=game(football_situation(possession='1')))['football_tracker']
        self.assertEqual((first['position'], second['position']), (66, 34))

    def test_goal_to_go_and_red_zone(self):
        tracker = self.get(event=game(football_situation(
            possessionText='LSU 8', down=1, distance=8,
            downDistanceText='1st & Goal at LSU 8')))['football_tracker']
        self.assertEqual(tracker['position'], 92)
        self.assertEqual(tracker['label'], '1st & Goal at LSU 8')
        self.assertTrue(tracker['red_zone'])
        self.assertTrue(tracker['goal_to_go'])

    def test_field_goal_description_never_invents_goal_to_go(self):
        for text in ('Field goal attempt', 'Goal line', '1st & Goal at LSU 34'):
            with self.subTest(text=text):
                tracker = self.get(event=game(football_situation(
                    downDistanceText=text, shortDownDistanceText='3rd & 7')))['football_tracker']
                self.assertFalse(tracker['goal_to_go'])
                self.assertEqual(tracker['label'], '3rd & 7 at LSU 34')

    def test_explicit_goal_to_go_short_text_and_same_down_are_required(self):
        for text in ('3rd & Goal', '3rd and goal'):
            tracker = self.get(event=game(football_situation(
                downDistanceText='', shortDownDistanceText=text)))['football_tracker']
            self.assertTrue(tracker['goal_to_go'])
        tracker = self.get(event=game(football_situation(
            downDistanceText='3rd & 7', shortDownDistanceText='1st & Goal')))['football_tracker']
        self.assertFalse(tracker['goal_to_go'])

    def test_red_zone_uses_confirmed_position_not_malformed_provider_flag(self):
        tracker = self.get(event=game(football_situation(isRedZone='true')))['football_tracker']
        self.assertFalse(tracker['red_zone'])
        tracker = self.get(event=game(football_situation(
            possessionText='LSU 8', isRedZone=False)))['football_tracker']
        self.assertTrue(tracker['red_zone'])

    def test_red_zone_boundary_and_own_twenty(self):
        for possession, expected in [('2', True), ('1', False)]:
            tracker = self.get(event=game(football_situation(
                possession=possession, possessionText='LSU 20')))['football_tracker']
            self.assertEqual(tracker['red_zone'], expected)

    def test_midfield_requires_known_possession(self):
        for text in ('50', 'MIDFIELD', 'LSU 50'):
            with self.subTest(text=text):
                tracker = self.get(event=game(football_situation(possessionText=text)))['football_tracker']
                self.assertEqual(tracker['position'], 50)
        self.assertIsNone(self.get(event=game(football_situation(
            possessionText='50', possession='999')))['football_tracker'])

    def test_overtime_label_and_actual_clock(self):
        for period, label in [(4, 'Q4'), (5, 'OT'), (6, '2OT')]:
            with self.subTest(period=period):
                tracker = self.get(event=game(football_situation(), period, '0:00'))['football_tracker']
                self.assertEqual(tracker['quarter'], label)
                self.assertEqual(tracker['clock'], '0:00')

    def test_unknown_field_side_or_ambiguous_raw_yardline_hides_widget(self):
        for text in ('', 'UNKNOWN 34', 'LSU 51', 'LSU -1', '34', None):
            with self.subTest(text=text):
                event = game(football_situation(possessionText=text, yardLine=34))
                self.assertIsNone(self.get(event=event)['football_tracker'])

    def test_missing_down_distance_possession_or_clock_never_fabricates_state(self):
        for field in ('possession', 'possessionText', 'down', 'distance'):
            with self.subTest(field=field):
                situation = football_situation()
                del situation[field]
                self.assertIsNone(self.get(event=game(situation))['football_tracker'])
        for clock in ('', '12:60', '16:00', '15:01', '4:2', None, 123):
            with self.subTest(clock=clock):
                self.assertIsNone(self.get(event=game(football_situation(), clock=clock))['football_tracker'])

    def test_invalid_down_distance_and_period_values(self):
        for key, values in [('down', [0, 5, True, -1, 1.5]),
                            ('distance', [None, -1, True, 'NaN', 0.5, 101, 999])]:
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertIsNone(self.get(event=game(football_situation(**{key: value})))['football_tracker'])
        for period in (0, -1, True, None, 1.5, 999):
            self.assertIsNone(self.get(event=game(football_situation(), period=period))['football_tracker'])

    def test_missing_team_identity_or_duplicate_identity_hides_football_widget(self):
        for key, value in [('id', ''), ('abbreviation', ''), ('id', '2'), ('abbreviation', 'TA&M')]:
            with self.subTest(key=key, value=value):
                home = deepcopy(self.home)
                home['team'][key] = value
                details = self.cache.get(NFL, game(football_situation()), home, self.away)
                self.assertIsNone(details['football_tracker'])

    def test_unsupported_sports_never_get_widgets(self):
        for path in ('basketball/nba', 'basketball/mens-college-basketball', 'golf/pga'):
            details = self.get(path)
            self.assertIsNone(details['football_tracker'])
            self.assertIsNone(details['baseball_tracker'])

    def test_nonplaying_states_hide_both_widgets(self):
        for state, detail in [('pre', 'Scheduled'), ('post', 'Final'), ('in', 'Halftime'),
                              ('in', 'Weather Delay'), ('in', 'Suspended'), ('in', 'Postponed'),
                              ('in', 'Canceled'), ('in', 'End of 3rd'), ('in', 'End 1st'),
                              ('in', 'STATUS_END_OF_PERIOD'), ('in', 'Unknown')]:
            for path, situation in ((NFL, football_situation()), (MLB, baseball_situation())):
                with self.subTest(state=state, detail=detail, path=path):
                    details = self.get(path, game(situation, detail=detail, state=state))
                    self.assertIsNone(details['football_tracker'])
                    self.assertIsNone(details['baseball_tracker'])

    def test_conflicting_competition_state_hides_widget(self):
        event = game(football_situation())
        event['competitions'][0]['status']['type']['state'] = 'post'
        self.assertIsNone(self.get(event=event)['football_tracker'])

    def test_conflicting_competition_progress_hides_widget(self):
        for field, value in [('period', 4), ('displayClock', '4:19')]:
            with self.subTest(field=field):
                event = game(football_situation())
                event['competitions'][0]['status'][field] = value
                self.assertIsNone(self.get(event=event)['football_tracker'])
        event = game(football_situation())
        event['competitions'][0]['status']['displayClock'] = '04:20'
        self.assertIsNotNone(self.get(event=event)['football_tracker'])

    def test_malformed_secondary_clock_hides_widget(self):
        for clock in ('INVALID', None, '', '4:60', 123, True):
            with self.subTest(clock=clock):
                event = game(football_situation())
                event['competitions'][0]['status']['displayClock'] = clock
                self.assertIsNone(self.get(event=event)['football_tracker'])

    def test_competition_only_status_is_supported_without_guessing(self):
        event = game(football_situation())
        event.pop('status')
        self.assertIsNotNone(self.get(event=event)['football_tracker'])

    def test_explicit_stale_and_completed_flags_hide_widget(self):
        for marker in ('stale', 'completed'):
            event = game(football_situation())
            if marker == 'stale':
                event['cache_stale'] = True
            else:
                event['status']['type']['completed'] = True
            self.assertIsNone(self.get(event=event)['football_tracker'])

    def test_missing_competition_or_situation_preserves_other_card_data(self):
        event = game()
        event.pop('competitions')
        details = self.get(event=event)
        self.assertIsNone(details['football_tracker'])
        self.assertEqual(details['home_record'], '4-2')

    def test_mlb_live_bases_outs_current_half_and_scores(self):
        tracker = self.get(MLB, game(baseball_situation(), period=5, detail='Top 5th'))['baseball_tracker']
        self.assertEqual(tracker, {'bases': {'first': False, 'second': True, 'third': False},
                                  'inning': 5, 'half': 'top', 'outs': 1,
                                  'home_score': '21', 'away_score': '14'})

    def test_mlb_extra_innings_and_every_base_pattern(self):
        for occupied in range(8):
            situation = baseball_situation(onFirst=bool(occupied & 1), onSecond=bool(occupied & 2),
                                           onThird=bool(occupied & 4), outs=2)
            tracker = self.get(MLB, game(situation, period=12, detail='Bottom 12th'))['baseball_tracker']
            self.assertEqual(tracker['half'], 'bottom')
            self.assertEqual(tracker['inning'], 12)
            self.assertEqual(sum(tracker['bases'].values()), bin(occupied).count('1'))

    def test_mlb_all_explicit_empty_bases_are_valid(self):
        tracker = self.get(MLB, game(baseball_situation(onSecond=False, outs=0),
                                   period=1, detail='Bot 1st'))['baseball_tracker']
        self.assertFalse(any(tracker['bases'].values()))
        self.assertEqual(tracker['outs'], 0)

    def test_mlb_untimed_status_does_not_require_football_clock(self):
        event = game(baseball_situation(), period=5, detail='Top 5th', clock='')
        event['competitions'][0]['status']['displayClock'] = None
        self.assertIsNotNone(self.get(MLB, event)['baseball_tracker'])

    def test_mlb_missing_bases_are_unknown_not_empty(self):
        for field in ('onFirst', 'onSecond', 'onThird'):
            for value in (None, 0, 1, 'false', {}, []):
                with self.subTest(field=field, value=value):
                    situation = baseball_situation(**{field: value})
                    self.assertIsNone(self.get(MLB, game(situation, period=5, detail='Top 5th'))['baseball_tracker'])
            situation = baseball_situation()
            del situation[field]
            self.assertIsNone(self.get(MLB, game(situation, period=5, detail='Top 5th'))['baseball_tracker'])

    def test_mlb_three_outs_or_unrecognized_inning_half_hide_widget(self):
        for outs in (None, 3, -1, True, 0.5):
            self.assertIsNone(self.get(MLB, game(baseball_situation(outs=outs),
                                               period=5, detail='Top 5th'))['baseball_tracker'])
        for detail in ('Middle 5th', 'End 5th', 'In Progress', 'Top 6th', '', 'Final'):
            self.assertIsNone(self.get(MLB, game(baseball_situation(),
                                               period=5, detail=detail))['baseball_tracker'])

    def test_mlb_conflicting_half_details_hide_widget(self):
        event = game(baseball_situation(), period=5, detail='Top 5th')
        event['status']['type']['shortDetail'] = 'Bottom 5th'
        self.assertIsNone(self.get(MLB, event)['baseball_tracker'])
        event = game(baseball_situation(), period=5, detail='Top 5th')
        event['competitions'][0]['status']['type']['shortDetail'] = 'Bottom 5th'
        self.assertIsNone(self.get(MLB, event)['baseball_tracker'])

    def test_missing_scores_are_not_invented_zeroes(self):
        self.home.pop('score')
        self.away['score'] = {'displayValue': '0'}
        tracker = self.get(MLB, game(baseball_situation(), period=1, detail='Top 1st'))['baseball_tracker']
        self.assertIsNone(tracker['home_score'])
        self.assertEqual(tracker['away_score'], '0')

    def test_football_widgets_are_never_saved_in_summary_snapshot(self):
        self.get()
        self.assertEqual(self.cache.snapshot(), {'version': 1, 'entries': []})
        restored = ScoreDetailsCache()
        restored.restore(self.cache.snapshot())
        self.assertIsNone(restored.get(NFL, game(), self.home, self.away)['football_tracker'])

    def test_malformed_source_never_crashes_or_creates_widget(self):
        for event in ({}, {'competitions': None}, {'competitions': 'bad'},
                      {'competitions': [None], 'status': []},
                      {'competitions': [{'situation': []}], 'status': {'type': None}}):
            for path in (NFL, MLB):
                with self.subTest(event=event, path=path):
                    details = self.cache.get(path, event, {}, {})
                    self.assertIsNone(details['football_tracker'])
                    self.assertIsNone(details['baseball_tracker'])


if __name__ == '__main__':
    unittest.main()
