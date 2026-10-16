"""Timezone and twelve-hour formatting for manual schedules and RSS dates."""
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ['WERKZEUG_RUN_MAIN'] = 'false'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as scoreboard


class LocalScheduleTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(scoreboard.requests, 'get',
                               side_effect=AssertionError('Unexpected network request'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def manual(self, date='2026-01-02', time='00:00', timezone='America/Chicago'):
        settings = {'local_schedule': {'items': [{
            'date': date, 'time': time, 'away_team': 'Texas A&M (8-2)',
            'home_team': 'Alabama', 'enabled': True,
        }], 'home_team_keywords': ['Texas A&M']}}
        original = deepcopy(settings)
        items = scoreboard._build_local_schedule_items(settings, timezone)
        self.assertEqual(settings, original, 'Rendering must not change persisted input values')
        return items[0]

    def test_required_noon_midnight_and_nearby_times(self):
        for raw, expected in [('00:00', '12:00 AM'), ('00:01', '12:01 AM'),
                              ('11:59', '11:59 AM'), ('12:00', '12:00 PM'),
                              ('12:01', '12:01 PM'), ('23:59', '11:59 PM')]:
            with self.subTest(time=raw):
                item = self.manual(time=raw)
                self.assertEqual(item['time'], expected)
                self.assertEqual(item['date'], 'Fri Jan 2')
                self.assertEqual(item['event_iso'], '2026-01-02T' + raw + ':00-06:00')
                self.assertEqual(item['away_team'], 'Texas A&M')
                self.assertEqual(item['away_record'], '8-2')
                self.assertTrue(item['away_is_fav'])

    def test_manual_schedule_observes_configured_timezone_and_dst(self):
        self.assertTrue(self.manual(date='2026-07-02', time='19:30')['event_iso'].endswith('-05:00'))
        item = self.manual(time='19:30', timezone='Pacific/Honolulu')
        self.assertEqual(item['time'], '7:30 PM')
        self.assertTrue(item['event_iso'].endswith('-10:00'))

    def test_ambiguous_and_nonexistent_manual_dst_times_are_not_guessed(self):
        for date, raw in [('2026-03-08', '02:30'), ('2026-11-01', '01:30')]:
            with self.subTest(date=date), self.assertLogs(scoreboard.app.logger, level='WARNING'):
                item = self.manual(date=date, time=raw)
                self.assertEqual(item['time'], '')
                self.assertEqual(item['event_iso'], '')

    def test_date_only_item_does_not_invent_a_kickoff_time(self):
        item = self.manual(time='')
        self.assertEqual(item['date'], 'Fri Jan 2')
        self.assertEqual(item['time'], '')
        self.assertEqual(item['event_iso'], '2026-01-02')

    def test_invalid_date_retains_the_matchup_without_a_misleading_time(self):
        with self.assertLogs(scoreboard.app.logger, level='WARNING'):
            item = self.manual(date='not-a-date', time='00:00 PM')
        self.assertEqual(item['away_team'], 'Texas A&M')
        self.assertEqual(item['time'], '')
        self.assertEqual(item['event_iso'], '')

    def parse_rss(self, date, timezone='America/Chicago'):
        response = Mock()
        response.content = ('<rss><channel><item><title>Football game schedule</title>'
                            '<pubDate>' + date + '</pubDate>'
                            '<description>News item</description></item></channel></rss>').encode()
        items = []
        with patch.object(scoreboard.requests, 'get', return_value=response):
            scoreboard._parse_rss_feed('https://example.test/sports.rss', 'SCHOOL', '', items, timezone)
        response.raise_for_status.assert_called_once()
        return items[0]

    def test_rss_provider_offset_converts_to_configured_calendar_and_time(self):
        item = self.parse_rss('Fri, 02 Jan 2026 05:59:00 GMT')
        self.assertEqual(item['date'], 'Thu Jan 1')
        self.assertEqual(item['time'], '11:59 PM')
        self.assertEqual(item['event_iso'], '2026-01-01T23:59:00-06:00')
        item = self.parse_rss('Thu, 02 Jul 2026 05:00:00 GMT')
        self.assertEqual(item['time'], '12:00 AM')
        self.assertEqual(item['event_iso'], '2026-07-02T00:00:00-05:00')

    def test_rss_missing_or_ambiguous_timestamp_keeps_item_without_inventing_time(self):
        for raw in ['', '2026-01-02 12:00', 'not-a-date']:
            with self.subTest(raw=raw):
                item = self.parse_rss(raw)
                self.assertEqual(item['title'], 'Football game schedule')
                self.assertEqual(item['date'], '')
                self.assertEqual(item['time'], '')
                self.assertEqual(item['event_iso'], '')

    def test_rss_timezone_is_forwarded_from_legacy_feed_configuration(self):
        settings = {'local_schedule': {'rss_url': 'https://example.test/sports.rss', 'rss_label': 'SCHOOL'}}
        with patch.object(scoreboard, '_cached_local_feed_items', return_value=[]) as cached:
            scoreboard._build_local_schedule_items(settings, 'Pacific/Honolulu')
        cached.assert_called_once_with('https://example.test/sports.rss', 'Pacific/Honolulu')

    def test_failed_rss_http_response_is_not_interpreted_as_schedule_data(self):
        response = Mock()
        response.raise_for_status.side_effect = scoreboard.requests.HTTPError('HTTP 503')
        items = []
        with patch.object(scoreboard.requests, 'get', return_value=response):
            with self.assertRaises(scoreboard.requests.HTTPError):
                scoreboard._parse_rss_feed('https://example.test/sports.rss', 'SCHOOL', '', items)
        self.assertEqual(items, [])

    def parse_ical(self, start, now='2026-01-02T18:00:00+00:00', zone='America/Chicago'):
        response = Mock()
        response.text = ('BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Football game\n' +
                         start + '\nLOCATION:Home field\nEND:VEVENT\nEND:VCALENDAR\n')
        items = []
        current = datetime.fromisoformat(now).astimezone(scoreboard.pytz.timezone(zone))
        with patch.object(scoreboard.requests, 'get', return_value=response), \
                patch.object(scoreboard, 'datetime', wraps=datetime) as calendar:
            calendar.now.return_value = current
            scoreboard._parse_ical_feed('https://example.test/schedule.ics', 'SCHOOL', '', items, zone)
        response.raise_for_status.assert_called_once()
        return items[0]

    def test_ical_tzid_is_converted_instead_of_assuming_display_timezone(self):
        item = self.parse_ical('DTSTART;TZID=America/New_York:20260102T190000')
        self.assertEqual(item['date'], 'Fri Jan 2')
        self.assertEqual(item['time'], '6:00 PM')
        self.assertEqual(item['event_iso'], '2026-01-02T18:00:00-06:00')
        quoted = self.parse_ical('DTSTART;TZID="America/New_York":20260102T190000')
        self.assertEqual(quoted['event_iso'], item['event_iso'])

    def test_ical_utc_and_floating_times_use_the_correct_zone(self):
        utc = self.parse_ical('DTSTART:20260102T180000Z')
        floating = self.parse_ical('DTSTART:20260102T180000')
        self.assertEqual(utc['time'], '12:00 PM')
        self.assertEqual(floating['time'], '6:00 PM')
        self.assertEqual(datetime.fromisoformat(utc['event_iso']).astimezone(timezone.utc).hour, 18)

    def test_ical_dst_transition_converts_source_timezone(self):
        item = self.parse_ical('DTSTART;TZID=America/New_York:20260308T033000',
                               now='2026-03-08T18:00:00+00:00')
        # New York has advanced its clock while Chicago is still on CST.
        self.assertEqual(item['time'], '1:30 AM')
        self.assertEqual(item['event_iso'], '2026-03-08T01:30:00-06:00')
        after = self.parse_ical('DTSTART;TZID=America/New_York:20260308T043000',
                                now='2026-03-08T18:00:00+00:00')
        self.assertEqual(after['time'], '3:30 AM')
        self.assertEqual(after['event_iso'], '2026-03-08T03:30:00-05:00')

    def test_ical_invalid_tzid_and_dst_local_times_do_not_invent_instants(self):
        for start, now in [
            ('DTSTART;TZID=Unknown/Zone:20260102T190000', '2026-01-02T18:00:00+00:00'),
            ('DTSTART;TZID=America/New_York:20260308T023000', '2026-03-08T18:00:00+00:00'),
            ('DTSTART;TZID=America/New_York:20261101T013000', '2026-11-01T18:00:00+00:00'),
        ]:
            with self.subTest(start=start):
                item = self.parse_ical(start, now=now)
                self.assertEqual(item['title'], 'Football game')
                self.assertEqual(item['time'], '')
                self.assertEqual(item['event_iso'], '')

    def test_ical_all_day_date_does_not_invent_midnight_or_shift_calendar_day(self):
        item = self.parse_ical('DTSTART;VALUE=DATE:20260102')
        self.assertEqual(item['date'], 'Fri Jan 2')
        self.assertEqual(item['time'], '')
        self.assertEqual(item['event_iso'], '2026-01-02')

    def test_ical_failed_http_is_not_interpreted_as_calendar(self):
        response = Mock()
        response.raise_for_status.side_effect = scoreboard.requests.HTTPError('HTTP 503')
        with patch.object(scoreboard.requests, 'get', return_value=response):
            with self.assertRaises(scoreboard.requests.HTTPError):
                scoreboard._parse_ical_feed('https://example.test/schedule.ics', 'SCHOOL', '', [])


class LocalFeedCacheTests(unittest.TestCase):
    def setUp(self):
        self.pending = []
        pending = self.pending

        class DeferredWorker:
            def __init__(self, target, args=(), **kwargs):
                self.target, self.args = target, args

            def start(self):
                pending.append(self)

            def run(self):
                self.target(*self.args)

        for name, value in [('_local_feed_cache', {}),
                            ('_local_feed_slots', scoreboard.threading.BoundedSemaphore(2))]:
            patcher = patch.object(scoreboard, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(scoreboard.threading, 'Thread', DeferredWorker)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(scoreboard.time_module, 'monotonic', return_value=1000)
        self.monotonic = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(scoreboard, '_resolve_feed', return_value=('https://example.test/rss', 'rss'))
        self.resolve = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(scoreboard, '_parse_rss_feed', side_effect=self.parse)
        self.parser = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(scoreboard.requests, 'get',
                               side_effect=AssertionError('Unexpected network request'))
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def parse(url, label, logo, out, tz_str):
        out.append({'type': 'rss', 'title': 'Texas A&M vs Alabama football',
                    'date': 'Fri Jan 2', 'time': '12:00 PM', 'event_iso': '2026-01-02T12:00:00-06:00'})

    def cached(self, url='https://example.test/rss', zone='America/Chicago'):
        return scoreboard._cached_local_feed_items(url, zone)

    def test_request_returns_manual_games_without_waiting_for_feed_network(self):
        settings = {'local_schedule': {'items': [{'date': '2026-01-02', 'time': '12:00',
                                                 'home_team': 'Alabama', 'away_team': 'Texas A&M'}],
                                       'rss_feeds': [{'url': 'https://example.test/rss'}]}}
        items = scoreboard._build_local_schedule_items(settings, 'America/Chicago')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['time'], '12:00 PM')
        self.assertEqual(len(self.pending), 1)
        self.resolve.assert_not_called()
        self.parser.assert_not_called()
        # Even a completely blocked worker does not occupy an HTTP handler.
        for _ in range(50):
            scoreboard._build_local_schedule_items(settings, 'America/Chicago')
        self.assertEqual(len(self.pending), 1)

    def test_single_shared_refresh_per_ttl_and_independent_return_values(self):
        self.assertEqual(self.cached(), [])
        self.pending[0].run()
        first = self.cached()
        self.assertEqual(first[0]['time'], '12:00 PM')
        first[0]['title'] = 'caller changed it'
        self.assertNotEqual(self.cached()[0]['title'], first[0]['title'])
        self.monotonic.return_value = 1299
        self.cached()
        self.assertEqual(len(self.pending), 1)
        self.monotonic.return_value = 1300
        self.cached()
        self.cached()
        self.assertEqual(len(self.pending), 2)
        self.assertEqual(self.resolve.call_count, 1)

    def test_failed_refresh_retains_good_data_with_backoff_then_recovers(self):
        self.cached()
        self.pending[0].run()
        original = self.cached()[0]['title']
        self.monotonic.return_value = 1300
        self.cached()
        self.parser.side_effect = scoreboard.requests.Timeout('offline')
        with self.assertLogs(scoreboard.app.logger, level='WARNING'):
            self.pending[1].run()
        self.assertEqual(self.cached()[0]['title'], original)
        self.assertTrue(self.cached()[0]['feed_stale'])
        self.monotonic.return_value = 1329
        self.cached()
        self.assertEqual(len(self.pending), 2)
        self.monotonic.return_value = 1330
        self.cached()
        with self.assertLogs(scoreboard.app.logger, level='WARNING'):
            self.pending[2].run()
        entry = scoreboard._local_feed_cache[('https://example.test/rss', 'America/Chicago')]
        self.assertEqual(entry['retry_at'], 1390)
        self.assertEqual(entry['failures'], 2)
        self.monotonic.return_value = 1390
        self.parser.side_effect = self.parse
        self.cached()
        self.pending[3].run()
        self.assertFalse(self.cached()[0]['feed_stale'])
        self.assertEqual(entry['failures'], 0)
        # A successfully fetched, legitimately empty feed removes old games.
        self.monotonic.return_value = 1690
        self.parser.side_effect = lambda *args: None
        self.cached()
        self.pending[4].run()
        self.assertEqual(self.cached(), [])

    def test_worker_limit_and_cache_capacity_are_bounded(self):
        for index in range(100):
            self.cached('https://example.test/' + str(index))
        self.assertEqual(len(self.pending), 2)
        self.assertEqual(len(scoreboard._local_feed_cache), 64)
        self.assertIn(('https://example.test/0', 'America/Chicago'), scoreboard._local_feed_cache)
        self.assertIn(('https://example.test/1', 'America/Chicago'), scoreboard._local_feed_cache)
        self.pending[0].run()
        self.cached('https://example.test/new')
        self.assertEqual(len(self.pending), 3)

    def test_same_feed_reuses_data_across_labels_and_matchup_preferences(self):
        settings = {'local_schedule': {'rss_feeds': [{'url': 'https://example.test/rss', 'label': 'First',
                                                     'home_team_keywords': ['Alabama']}]}}
        scoreboard._build_local_schedule_items(settings, 'America/Chicago')
        self.pending[0].run()
        first = scoreboard._build_local_schedule_items(settings, 'America/Chicago')[0]
        settings['local_schedule']['rss_feeds'][0]['label'] = 'Second'
        second = scoreboard._build_local_schedule_items(settings, 'America/Chicago')[0]
        self.assertEqual(first['label'], 'FIRST')
        self.assertEqual(second['label'], 'SECOND')
        self.assertEqual(len(self.pending), 1)
        self.assertNotIn('label', self.cached()[0])

    def test_changed_timezone_uses_a_separate_parse(self):
        self.cached()
        self.cached(zone='Pacific/Honolulu')
        self.assertEqual(len(self.pending), 2)
        self.pending[0].run()
        self.pending[1].run()
        self.assertEqual([call.args[-1] for call in self.parser.call_args_list],
                         ['America/Chicago', 'Pacific/Honolulu'])

    def test_unknown_feed_does_not_replace_previous_success(self):
        self.cached()
        self.pending[0].run()
        self.monotonic.return_value = 1300
        self.resolve.return_value = ('https://example.test/rss', None)
        self.cached()
        with self.assertLogs(scoreboard.app.logger, level='WARNING'):
            self.pending[1].run()
        self.assertTrue(self.cached()[0]['feed_stale'])
        self.assertEqual(self.parser.call_count, 1)


class FeedValidationTests(unittest.TestCase):
    def test_invalid_http_200_payloads_raise_instead_of_erasing_cached_games(self):
        response = Mock(content=b'<html>Provider outage</html>', text='<html>Provider outage</html>')
        response.json.return_value = {'error': 'Provider outage'}
        with patch.object(scoreboard.requests, 'get', return_value=response):
            for parser in [scoreboard._parse_rss_feed, scoreboard._parse_ical_feed,
                           scoreboard._parse_maxpreps_feed, scoreboard._parse_thrillshare_feed]:
                with self.subTest(parser=parser.__name__), self.assertRaises(ValueError):
                    parser('https://example.test/feed', 'SCHOOL', '', [])

    def test_legitimate_empty_payloads_are_successful(self):
        for parser, text, data in [
            (scoreboard._parse_rss_feed, '<rss><channel /></rss>', None),
            (scoreboard._parse_ical_feed, 'BEGIN:VCALENDAR\nEND:VCALENDAR', None),
            (scoreboard._parse_maxpreps_feed,
             '<script id="__NEXT_DATA__">{"props":{"pageProps":{"initSchoolContests":[]}}}</script>', None),
            (scoreboard._parse_thrillshare_feed, '', {'events': []}),
        ]:
            response = Mock(text=text, content=text.encode())
            response.json.return_value = data
            items = []
            with self.subTest(parser=parser.__name__), patch.object(scoreboard.requests, 'get', return_value=response):
                parser('https://example.test/feed', 'SCHOOL', '', items)
                self.assertEqual(items, [])


if __name__ == '__main__':
    unittest.main()
