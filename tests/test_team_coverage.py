"""Offline regression checks for the shipped 2026 football selection baseline."""
from collections import Counter
import json
from pathlib import Path
import unittest
from urllib.parse import urlparse


CATALOG_PATH = Path(__file__).resolve().parents[1] / 'static/data/football-teams-2026.json'


class FootballCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text())
        cls.cfb = {team['id']: team for team in cls.catalog['cfb']}
        cls.nfl = {team['abbr']: team for team in cls.catalog['nfl']}

    def test_all_75_requested_2026_conference_members_are_present(self):
        expected = {
            'ACC': {'103', '150', '152', '153', '154', '183', '221', '228',
                    '2390', '24', '25', '2567', '258', '259', '52', '59', '97'},
            'Big Ten': {'120', '127', '130', '135', '158', '164', '194', '213',
                        '2294', '2483', '2509', '26', '264', '275', '30', '356', '77', '84'},
            'Big 12': {'12', '197', '2116', '2132', '2305', '2306', '239', '248',
                       '252', '254', '2628', '2641', '277', '38', '66', '9'},
            'SEC': {'142', '145', '2', '201', '238', '245', '251', '2579',
                    '2633', '333', '344', '57', '61', '8', '96', '99'},
            'Pac-12': {'204', '21', '265', '278', '326', '328', '36', '68'},
        }
        selected = [team for team in self.catalog['cfb'] if team['target']]
        self.assertEqual(len(selected), 75)
        self.assertEqual(Counter(team['conference'] for team in selected),
                         {conference: len(ids) for conference, ids in expected.items()})
        for conference, ids in expected.items():
            with self.subTest(conference=conference):
                self.assertEqual({team['id'] for team in selected
                                  if team['conference'] == conference}, ids)

    def test_realignment_and_nonfootball_members_are_handled(self):
        for team_id in ('24', '25', '2567'):
            self.assertEqual(self.cfb[team_id]['conference'], 'ACC')
        for team_id in ('201', '251'):
            self.assertEqual(self.cfb[team_id]['conference'], 'SEC')
        for team_id in ('26', '30', '264', '2483'):
            self.assertEqual(self.cfb[team_id]['conference'], 'Big Ten')
        for team_id in ('21', '36', '68', '204', '265', '278', '326', '328'):
            self.assertEqual(self.cfb[team_id]['conference'], 'Pac-12')
        self.assertNotIn('2250', self.cfb, 'Gonzaga has no football team')

    def test_notre_dame_remains_an_independent_choice(self):
        self.assertEqual(len(self.catalog['cfb']), 76)
        self.assertEqual(self.cfb['87']['abbr'], 'ND')
        self.assertEqual(self.cfb['87']['conference'], 'Independents')
        self.assertFalse(self.cfb['87']['target'])

    def test_exactly_all_32_current_nfl_franchises_use_espn_ids(self):
        expected = {
            'ARI': '22', 'ATL': '1', 'BAL': '33', 'BUF': '2', 'CAR': '29',
            'CHI': '3', 'CIN': '4', 'CLE': '5', 'DAL': '6', 'DEN': '7',
            'DET': '8', 'GB': '9', 'HOU': '34', 'IND': '11', 'JAX': '30',
            'KC': '12', 'LAC': '24', 'LAR': '14', 'LV': '13', 'MIA': '15',
            'MIN': '16', 'NE': '17', 'NO': '18', 'NYG': '19', 'NYJ': '20',
            'PHI': '21', 'PIT': '23', 'SEA': '26', 'SF': '25', 'TB': '27',
            'TEN': '10', 'WSH': '28',
        }
        self.assertEqual(len(self.catalog['nfl']), 32)
        self.assertEqual({abbr: team['id'] for abbr, team in self.nfl.items()}, expected)
        self.assertEqual(self.nfl['WSH']['name'], 'Washington Commanders')
        self.assertEqual(self.nfl['LV']['name'], 'Las Vegas Raiders')
        self.assertNotIn('OAK', self.nfl)
        self.assertNotIn('STL', self.nfl)

    def test_each_team_has_a_unique_stable_identity_and_valid_metadata(self):
        for league in ('cfb', 'nfl'):
            teams = self.catalog[league]
            with self.subTest(league=league):
                self.assertEqual(len({team['id'] for team in teams}), len(teams))
                self.assertEqual(len({team['abbr'] for team in teams}), len(teams))
                for team in teams:
                    self.assertTrue(team['id'].isdigit())
                    self.assertTrue(team['abbr'].strip())
                    self.assertTrue(team['name'].strip())
                    self.assertTrue(team['conference'].strip())
                    self.assertRegex(team['color'], r'^[0-9A-Fa-f]{6}$')

    def test_logo_urls_are_safe_espn_assets_without_bundled_artwork(self):
        for league in ('cfb', 'nfl'):
            for team in self.catalog[league]:
                with self.subTest(league=league, team=team['abbr']):
                    url = urlparse(team['logo'])
                    self.assertEqual(url.scheme, 'https')
                    self.assertEqual(url.netloc, 'a.espncdn.com')
                    self.assertFalse(url.query)
                    self.assertTrue(url.path.endswith('.png'))
                    if league == 'cfb':
                        self.assertTrue(url.path.endswith('/' + team['id'] + '.png'))

    def test_existing_favorite_and_provider_abbreviations_are_preserved(self):
        self.assertEqual(self.cfb['245']['abbr'], 'TA&M')
        self.assertEqual(self.cfb['2567']['abbr'], 'SMU')
        self.assertEqual(self.nfl['HOU']['name'], 'Houston Texans')
        # These differ in old metadata. Aliases permit safe favorite matching
        # without replacing a user's saved team list.
        for team_id, primary, alias in [('152', 'NCSU', 'NCST'),
                                        ('84', 'IU', 'IND'),
                                        ('201', 'OU', 'OKLA'),
                                        ('2390', 'MIA', 'MIAMI'),
                                        ('68', 'BOIS', 'BSU'),
                                        ('77', 'NU', 'NW')]:
            self.assertEqual(self.cfb[team_id]['abbr'], primary)
            self.assertIn(alias, self.cfb[team_id]['aliases'])
        self.assertIn('WAS', self.nfl['WSH']['aliases'])
        self.assertIn('OAK', self.nfl['LV']['aliases'])

    def test_all_fbs_memberships_support_conference_filters(self):
        memberships = self.catalog['cfb_memberships']
        self.assertEqual(len(memberships), 138)
        self.assertEqual(Counter(memberships.values()), {
            'ACC': 17, 'Big Ten': 18, 'Big 12': 16, 'SEC': 16, 'Pac-12': 8,
            'American Athletic': 14, 'Sun Belt': 14, 'MAC': 13,
            'Conference USA': 10, 'Mountain West': 10, 'Independents': 2,
        })
        for team in self.catalog['cfb']:
            self.assertEqual(memberships[team['id']], team['conference'])

    def test_conference_ids_match_2026_published_espn_groups(self):
        ids = self.catalog['conference_ids']
        self.assertEqual({name: ids[name] for name in ('ACC', 'Big Ten', 'Big 12', 'SEC', 'Pac-12')},
                         {'ACC': '1', 'Big Ten': '5', 'Big 12': '4', 'SEC': '8', 'Pac-12': '9'})
        for team in self.catalog['cfb']:
            self.assertEqual(team['conference_id'], ids[team['conference']])

    def test_source_audit_distinguishes_snapshots_from_live_verification(self):
        self.assertEqual(self.catalog['season'], 2026)
        self.assertEqual(self.catalog['source_checked_at'], '2026-10-19')
        self.assertIn('Direct ESPN API and official conference websites were blocked',
                      self.catalog['verification_status'])
        self.assertGreaterEqual(len(self.catalog['sources']), 6)
        for source in self.catalog['sources']:
            self.assertEqual(urlparse(source['url']).scheme, 'https')
            self.assertRegex(source['content_sha256'], r'^[0-9a-f]{64}$')


if __name__ == '__main__':
    unittest.main()
