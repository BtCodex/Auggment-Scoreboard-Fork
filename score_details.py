"""Bounded, asynchronous enrichment of ESPN scorecards.

``get`` only reads normalized local data and registers demand. The application's
existing background worker calls ``refresh``; a slow summary endpoint therefore
never delays a browser request. Scoreboard totals always remain authoritative.
"""
from collections import OrderedDict
from copy import deepcopy
import json
import math
import re
import threading
import time

import requests


SUPPORTED_PATHS = frozenset({
    'football/nfl', 'football/college-football', 'basketball/nba',
    'basketball/mens-college-basketball', 'basketball/womens-college-basketball',
    'baseball/mlb',
})
_MAX_PERIODS = 64
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_RECORD = re.compile(r'^\d{1,3}-\d{1,3}(?:-\d{1,3})?$')


def _dict(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    if isinstance(value, dict):
        value = value.get('value', value.get('displayValue'))
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or number > 999 or not number.is_integer():
        return None
    return int(number)


def _record(competitor):
    """Return the season/overall record, never a home-only or away-only record."""
    for field in ('records', 'record'):
        records = competitor.get(field, [])
        if isinstance(records, str) and _RECORD.fullmatch(records.strip()):
            return records.strip()
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            continue
        candidates = []
        for item in records[:16]:
            if not isinstance(item, dict):
                continue
            summary = str(item.get('summary', item.get('displayValue', ''))).strip()
            if not _RECORD.fullmatch(summary):
                continue
            names = {str(item.get(key, '')).lower() for key in ('name', 'type', 'description')}
            if names & {'home', 'away', 'road', 'home record', 'away record'}:
                continue
            priority = 0 if names & {'overall', 'total', 'overall record'} else 1
            if priority == 0 or not any(names):
                candidates.append((priority, summary))
        if candidates:
            return min(candidates, key=lambda pair: pair[0])[1]
    return ''


def _periods(competitor):
    result = {}
    lines = competitor.get('linescores', [])
    if not isinstance(lines, list):
        return result
    for index, item in enumerate(lines[:_MAX_PERIODS], 1):
        if isinstance(item, dict) and str(item.get('displayValue', '')).strip().lower() in {'x', '-', '--', '—'}:
            continue  # MLB's unbatted half-inning is not a scored zero.
        period = _dict(item).get('period', index)
        if isinstance(period, bool):
            continue
        try:
            period = int(period)
        except (TypeError, ValueError, OverflowError):
            continue
        value = _number(item)
        if 1 <= period <= _MAX_PERIODS and value is not None:
            result[str(period)] = value
    return result


def _unbatted_periods(competitor):
    """An explicit MLB X supersedes an older cached numeric line score."""
    result = set()
    lines = competitor.get('linescores', [])
    if not isinstance(lines, list):
        return result
    for index, item in enumerate(lines[:_MAX_PERIODS], 1):
        if not isinstance(item, dict) or str(item.get('displayValue', '')).strip().lower() != 'x':
            continue
        try:
            period = int(item.get('period', index))
        except (TypeError, ValueError, OverflowError):
            continue
        if 1 <= period <= _MAX_PERIODS:
            result.add(str(period))
    return result


def _statistics(competitor):
    result = {'hits': None, 'errors': None}
    stats = competitor.get('statistics', [])
    if not isinstance(stats, list):
        return result
    for item in stats[:64]:
        if not isinstance(item, dict):
            continue
        names = {str(item.get(key, '')).lower() for key in ('name', 'abbreviation', 'label')}
        key = 'hits' if names & {'hits', 'h'} else 'errors' if names & {'errors', 'e'} else None
        if key:
            result[key] = _number(item.get('displayValue', item.get('value')))
    return result


def _team(competitor):
    competitor = _dict(competitor)
    return {'id': str(_dict(competitor.get('team')).get('id', ''))[:20],
            'record': _record(competitor), 'periods': _periods(competitor),
            **_statistics(competitor)}


def _summary(payload):
    """Discard players, commentary, and other large summary response fields."""
    payload = _dict(payload)
    competitions = _dict(payload.get('header')).get('competitions', [])
    competition = _dict(competitions[0]) if isinstance(competitions, list) and competitions else {}
    competitors = competition.get('competitors', [])
    result = {}
    if isinstance(competitors, list):
        for competitor in competitors[:4]:
            if isinstance(competitor, dict) and competitor.get('homeAway') in ('home', 'away'):
                result[competitor['homeAway']] = _team(competitor)
    teams = _dict(payload.get('boxscore')).get('teams', [])
    if isinstance(teams, list):
        for item in teams[:4]:
            if not isinstance(item, dict):
                continue
            details = _team(item)
            for side, existing in result.items():
                if details['id'] and details['id'] == existing['id']:
                    for key in ('hits', 'errors'):
                        if details[key] is not None:
                            existing[key] = details[key]
                    if not existing['periods']:
                        existing['periods'] = details['periods']
                    if not existing['record']:
                        existing['record'] = details['record']
    return result


def _state(event):
    status = _dict(event.get('status'))
    if not status:
        competitions = event.get('competitions', [])
        if isinstance(competitions, list) and competitions:
            status = _dict(_dict(competitions[0]).get('status'))
    kind = _dict(status.get('type'))
    detail = ' '.join(str(kind.get(key, '')).lower()
                      for key in ('name', 'description', 'detail', 'shortDetail'))
    if any(word in detail for word in ('cancel', 'postpon', 'suspend', 'delay')):
        return ''
    state = kind.get('state')
    return state if state in ('in', 'post') else ''


def _labels(path, length):
    if path == 'baseball/mlb':
        return [str(index) for index in range(1, max(9, length) + 1)]
    regulation = 2 if path == 'basketball/mens-college-basketball' else 4
    prefix = 'H' if regulation == 2 else 'Q'
    result = [prefix + str(index) for index in range(1, regulation + 1)]
    result.extend('OT' if index == 1 else str(index) + 'OT'
                  for index in range(1, max(0, length - regulation) + 1))
    return result


def _required_periods(path, event, state):
    status = _dict(event.get('status'))
    if not status:
        competitions = event.get('competitions', [])
        if isinstance(competitions, list) and competitions:
            status = _dict(_dict(competitions[0]).get('status'))
    period = _number(status.get('period')) or 0
    regulation = 9 if path == 'baseball/mlb' else 2 if path == 'basketball/mens-college-basketball' else 4
    return min(_MAX_PERIODS, max(period, regulation if state == 'post' else 1))


def _live_context(event, check_clock=False):
    """Return only a coherent, currently playing scoreboard competition.

    Historical summaries are deliberately excluded: a final play's situation is
    not a current ball position or base state. Cache freshness is also checked
    by the caller that owns the scoreboard cache.
    """
    competitions = event.get('competitions', [])
    competition = _dict(competitions[0]) if isinstance(competitions, list) and competitions else {}
    if not competition or event.get('cache_stale') is True or competition.get('cache_stale') is True:
        return None
    statuses = [value for value in (_dict(event.get('status')), _dict(competition.get('status'))) if value]
    if not statuses:
        return None
    for status in statuses:
        kind = _dict(status.get('type'))
        details = ' '.join(str(kind.get(field, '')).lower()
                           for field in ('name', 'description', 'detail', 'shortDetail')).replace('_', ' ')
        if (kind.get('state') != 'in' or kind.get('completed') is True
                or any(word in details for word in ('halftime', 'half time', 'cancel', 'postpon',
                                                   'suspend', 'delay', 'final', 'unknown'))
                or re.search(r'\bend(?:\s|\d|$)', details)):
            return None
    periods = {_number(value['period']) for value in statuses if 'period' in value}
    clocks = set()
    for value in statuses:
        if not check_clock or 'displayClock' not in value:
            continue
        clock = value['displayClock']
        if not isinstance(clock, str) or not re.fullmatch(r'\d{1,2}:[0-5]\d', clock.strip()):
            return None  # A malformed competing clock cannot corroborate current play.
        clocks.add(tuple(int(part) for part in clock.strip().split(':')))
    if len(periods) > 1 or len(clocks) > 1:
        return None  # A situation paired with conflicting game progress is unsafe.
    return competition, statuses[0]


def _football_tracker(event, home, away):
    context = _live_context(event, check_clock=True)
    if context is None:
        return None
    competition, status = context
    situation = _dict(competition.get('situation'))
    period = _number(status.get('period'))
    clock = status.get('displayClock')
    if period is None or not 1 <= period <= _MAX_PERIODS or not isinstance(clock, str):
        return None
    clock = clock.strip()
    match = re.fullmatch(r'(\d{1,2}):([0-5]\d)', clock)
    if not match or int(match[1]) > 15 or (int(match[1]) == 15 and match[2] != '00'):
        return None
    teams = {}
    for side, competitor in (('home', home), ('away', away)):
        team = _dict(competitor.get('team'))
        team_id, abbreviation = str(team.get('id', '')), team.get('abbreviation')
        if (not re.fullmatch(r'\d{1,20}', team_id) or not isinstance(abbreviation, str)
                or not re.fullmatch(r"[A-Za-z0-9&.'-]{1,12}", abbreviation)):
            return None
        teams[side] = {'id': team_id, 'abbreviation': abbreviation}
    if (teams['home']['id'] == teams['away']['id']
            or teams['home']['abbreviation'].casefold() == teams['away']['abbreviation'].casefold()):
        return None
    possession = str(situation.get('possession', ''))
    side = next((side for side, team in teams.items() if team['id'] == possession), None)
    if side is None:
        return None
    down, distance = _number(situation.get('down')), _number(situation.get('distance'))
    if down not in (1, 2, 3, 4) or distance is None or distance > 100:
        return None
    possession_text = situation.get('possessionText')
    if not isinstance(possession_text, str):
        return None
    possession_text = possession_text.strip()
    field_match = re.fullmatch(r"([A-Za-z0-9&.'-]{1,12})\s+([0-4]?\d|50)", possession_text)
    if field_match:
        ball_side = next((key for key, value in teams.items()
                          if value['abbreviation'].casefold() == field_match[1].casefold()), None)
        if ball_side is None:
            return None
        yards = int(field_match[2])
        position = yards if ball_side == side else 100 - yards
        field_label = teams[ball_side]['abbreviation'] + ' ' + str(yards)
    elif possession_text.upper() in ('50', 'MIDFIELD'):
        position, field_label = 50, 'midfield'
    else:
        return None
    down_label = ('1st', '2nd', '3rd', '4th')[down - 1]
    goal_pattern = re.compile(r'^' + down_label + r'\s*(?:&|and)\s*goal\b', re.IGNORECASE)
    goal_to_go = any(isinstance(situation.get(key), str)
                     and goal_pattern.match(situation[key].strip()) is not None
                     for key in ('downDistanceText', 'shortDownDistanceText'))
    distance_label = 'Goal' if goal_to_go else str(distance)
    quarter = 'Q' + str(period) if period <= 4 else 'OT' if period == 5 else str(period - 4) + 'OT'
    return {'possession': side, 'team': teams[side]['abbreviation'], 'position': position,
            'direction': 'right', 'label': down_label + ' & ' + distance_label + ' at ' + field_label,
            'quarter': quarter,
            'clock': clock, 'red_zone': position >= 80, 'goal_to_go': goal_to_go}


def _baseball_tracker(event, home, away):
    context = _live_context(event)
    if context is None:
        return None
    competition, status = context
    situation = _dict(competition.get('situation'))
    bases = {base: situation.get(source) for base, source in
             (('first', 'onFirst'), ('second', 'onSecond'), ('third', 'onThird'))}
    outs, inning = _number(situation.get('outs')), _number(status.get('period'))
    if (any(type(value) is not bool for value in bases.values()) or outs not in (0, 1, 2)
            or inning is None or not 1 <= inning <= _MAX_PERIODS):
        return None
    halves = set()
    for current_status in (status, _dict(competition.get('status'))):
        for field in ('detail', 'shortDetail'):
            text = _dict(current_status.get('type')).get(field, '')
            if not isinstance(text, str):
                continue
            match = re.fullmatch(r'(Top|Bottom|Bot)\s+(\d+)(?:st|nd|rd|th)?', text.strip(), re.IGNORECASE)
            if match:
                if int(match[2]) != inning:
                    return None
                halves.add('top' if match[1].lower() == 'top' else 'bottom')
    if len(halves) != 1:
        return None
    return {'bases': bases, 'inning': inning, 'half': halves.pop(), 'outs': outs,
            'home_score': str(_number(home.get('score'))) if _number(home.get('score')) is not None else None,
            'away_score': str(_number(away.get('score'))) if _number(away.get('score')) is not None else None}


class ScoreDetailsCache:
    """Small recent-demand cache shared by all favorites and browser clients."""

    MAX_ENTRIES = 128
    MAX_REQUESTS_PER_REFRESH = 2
    DEMAND_SECONDS = 15 * 60

    def __init__(self, request_get=None, clock=None):
        self._request_get = request_get
        self._clock = clock or time.time
        self._entries = OrderedDict()
        self._demand = OrderedDict()
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()

    @staticmethod
    def _key(path, event_id):
        event_id = str(event_id)
        if path not in SUPPORTED_PATHS or not re.fullmatch(r'[0-9]{1,20}', event_id):
            return None
        return path + ':' + event_id

    def get(self, path, event, home, away):
        """Read current scoreboard details, with cached summary fields as fallback."""
        event, home, away = _dict(event), _dict(home), _dict(away)
        key = self._key(path, event.get('id', ''))
        current = {'home': _team(home), 'away': _team(away)}
        scoreboard_periods = {side: value['periods'] for side, value in current.items()}
        scoreboard_records = {side: value['record'] for side, value in current.items()}
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key, {})
            cached = entry.get('data', {})
            if key in self._entries:
                self._entries.move_to_end(key)
            for side in ('home', 'away'):
                source = cached.get(side, {})
                target = current[side]
                if source.get('id') and target['id'] and source['id'] != target['id']:
                    continue
                if not target['record']:
                    target['record'] = source.get('record', '')
                target['periods'] = {**source.get('periods', {}), **target['periods']}
                if path == 'baseball/mlb':
                    for period in _unbatted_periods(home if side == 'home' else away):
                        target['periods'].pop(period, None)
                for field in ('hits', 'errors'):
                    if target[field] is None:
                        target[field] = source.get(field)
            state = _state(event)
            required = _required_periods(path, event, state)
            missing = any(not scoreboard_records[side] or any(str(index) not in scoreboard_periods[side]
                          for index in range(1, required + 1)) for side in ('home', 'away'))
            if path == 'baseball/mlb':
                missing |= any(_statistics(value)[field] is None
                               for value in (home, away) for field in ('hits', 'errors'))
            if key and state and missing:
                self._demand[key] = {'at': now, 'state': state}
                self._demand.move_to_end(key)
                while len(self._demand) > self.MAX_ENTRIES:
                    self._demand.popitem(last=False)
            elif key:
                self._demand.pop(key, None)
        result = {'home_record': current['home']['record'],
                  'away_record': current['away']['record'], 'period_scores': None,
                  'football_tracker': _football_tracker(event, home, away)
                  if path in ('football/nfl', 'football/college-football') else None,
                  'baseball_tracker': _baseball_tracker(event, home, away) if path == 'baseball/mlb' else None}
        all_periods = [int(period) for side in current.values() for period in side['periods']]
        if path not in SUPPORTED_PATHS or not all_periods:
            return result
        labels = _labels(path, max(all_periods))
        result['period_scores'] = {
            'labels': labels,
            'home': [current['home']['periods'].get(str(index)) for index in range(1, len(labels) + 1)],
            'away': [current['away']['periods'].get(str(index)) for index in range(1, len(labels) + 1)],
            'totals': {side: {'score': str(_number(competitor.get('score')))
                             if _number(competitor.get('score')) is not None else '—',
                             'hits': current[side]['hits'], 'errors': current[side]['errors']}
                       for side, competitor in (('home', home), ('away', away))},
        }
        return result

    def _fetch(self, path, event_id):
        response = (self._request_get or requests.get)(
            'https://site.api.espn.com/apis/site/v2/sports/' + path + '/summary',
            params={'event': event_id}, timeout=(3, 5), stream=True)
        try:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                body.extend(chunk)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise ValueError('ESPN summary exceeds response limit')
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError('ESPN summary must be an object')
            normalized = _summary(payload)
            if not normalized:
                raise ValueError('ESPN summary has no identified competitors')
            return normalized
        finally:
            response.close()

    def refresh(self):
        """Fetch at most two due summaries; return the number of attempted requests."""
        if not self._refresh_lock.acquire(blocking=False):
            return 0
        attempts = 0
        try:
            now = self._clock()
            with self._lock:
                self._demand = OrderedDict((key, value) for key, value in self._demand.items()
                                           if now - value['at'] <= self.DEMAND_SECONDS)
                def oldest_attempt(item):
                    entry = self._entries.get(item[0], {})
                    attempted = entry.get('attempted', entry.get('fetched'))
                    return (attempted is not None, attempted if attempted is not None else 0)

                # Browsers re-register cards in display order. Using that order
                # here starves later cards once the first games' TTLs expire.
                pending = sorted(self._demand.items(), key=oldest_attempt)
            for key, demand in pending:
                with self._lock:
                    entry = self._entries.get(key, {})
                    ttl = 6 * 3600 if demand['state'] == 'post' else 60
                    if entry.get('retry_at', 0) > now:
                        continue
                    newly_final = demand['state'] == 'post' and entry.get('state') != 'post'
                    if not newly_final and entry.get('fetched') is not None and now - entry['fetched'] < ttl:
                        continue
                path, event_id = key.rsplit(':', 1)
                attempts += 1
                try:
                    data = self._fetch(path, event_id)
                    replacement = {'data': data, 'fetched': now, 'state': demand['state'],
                                   'failures': 0, 'retry_at': 0}
                except (requests.RequestException, ValueError, TypeError, OverflowError):
                    failures = min(entry.get('failures', 0) + 1, 5)
                    replacement = {**entry, 'failures': failures,
                                   'retry_at': now + min(3600, 300 * (2 ** (failures - 1)))}
                replacement['attempted'] = now
                with self._lock:
                    self._entries[key] = replacement
                    self._entries.move_to_end(key)
                    while len(self._entries) > self.MAX_ENTRIES:
                        self._entries.popitem(last=False)
                if attempts >= self.MAX_REQUESTS_PER_REFRESH:
                    break
            return attempts
        finally:
            self._refresh_lock.release()

    def snapshot(self):
        """Copy compact successful results only; no raw API bodies or demand queue."""
        with self._lock:
            return {'version': 1, 'entries': [
                {'key': key, 'data': deepcopy(entry['data']), 'fetched': entry['fetched'],
                 'state': entry.get('state', '')}
                for key, entry in self._entries.items() if entry.get('data')]}

    def restore(self, snapshot):
        """Load only validated compact fields from an offline backend snapshot."""
        if not isinstance(snapshot, dict) or snapshot.get('version') != 1:
            return 0
        entries = snapshot.get('entries')
        if not isinstance(entries, list):
            return 0
        restored = OrderedDict()
        for item in entries[-self.MAX_ENTRIES:]:
            if not isinstance(item, dict) or not isinstance(item.get('key'), str):
                continue
            try:
                path, event_id = item['key'].rsplit(':', 1)
                key = self._key(path, event_id)
                fetched = float(item.get('fetched'))
            except (TypeError, ValueError, OverflowError):
                continue
            if not key or not math.isfinite(fetched) or fetched < 0:
                continue
            if fetched > self._clock() + 300:
                fetched = 0  # Retain offline scores but refetch after clock corrections.
            data = {}
            for side in ('home', 'away'):
                source = _dict(_dict(item.get('data')).get(side))
                if not source:
                    continue
                periods = _dict(source.get('periods'))
                validated = {}
                for period, value in list(periods.items())[:_MAX_PERIODS]:
                    if isinstance(period, str) and len(period) <= 2 and period.isdigit() and 1 <= int(period) <= _MAX_PERIODS:
                        number = _number(value)
                        if number is not None:
                            validated[str(int(period))] = number
                record = source.get('record', '')
                data[side] = {'id': str(source.get('id', ''))[:20],
                              'record': record if isinstance(record, str) and _RECORD.fullmatch(record) else '',
                              'periods': validated, 'hits': _number(source.get('hits')),
                              'errors': _number(source.get('errors'))}
            if data:
                restored[key] = {'data': data, 'fetched': fetched,
                                 'state': item.get('state') if item.get('state') in ('in', 'post') else '',
                                 'failures': 0, 'retry_at': 0}
        with self._lock:
            self._entries.update(restored)
            while len(self._entries) > self.MAX_ENTRIES:
                self._entries.popitem(last=False)
        return len(restored)
