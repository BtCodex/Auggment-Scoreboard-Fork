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
                  'away_record': current['away']['record'], 'period_scores': None}
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
