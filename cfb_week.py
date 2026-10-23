"""Small, deterministic ESPN football-week helpers; no network or dependencies added."""
from datetime import datetime, timedelta, timezone
import re
from dateutil.parser import isoparse


CFB = 'football/college-football'


def _integer(value, minimum=0, maximum=999):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        number = int(value)
    else:
        return None
    return number if minimum <= number <= maximum else None


def _date(value):
    try:
        result = isoparse(value)
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _season_type(value):
    if isinstance(value, dict):
        value = value.get('type', value.get('id'))
    return _integer(value, 1, 4)


def metadata(payload):
    """Retain just the provider's selection/calendar, not its news/advertisements."""
    if not isinstance(payload, dict):
        return {}
    leagues = payload.get('leagues')
    league = leagues[0] if isinstance(leagues, list) and leagues and isinstance(leagues[0], dict) else {}
    calendar = league.get('calendar')
    clean_calendar = []
    if isinstance(calendar, list):
        for block in calendar[:8]:
            if not isinstance(block, dict):
                continue
            entries = block.get('entries', [])
            clean_calendar.append({key: block.get(key) for key in ('label', 'value', 'startDate', 'endDate')})
            clean_calendar[-1]['entries'] = [{key: entry.get(key) for key in
                ('label', 'value', 'startDate', 'endDate')} for entry in entries[:100]
                if isinstance(entry, dict)] if isinstance(entries, list) else []
    return {'season': payload.get('season'), 'week': payload.get('week'),
            'leagues': [{'calendar': clean_calendar}]}


def select_week(payload, now=None):
    """Choose the official calendar entry containing now, never an arbitrary date window.

    ESPN's historical leagues[].season can describe a different current season;
    use the response's top-level season instead. Postseason CFP is a subview of
    the canonical Bowls week and must not displace that complete selection.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('CFB week selection requires an aware current time')
    season = payload.get('season') if isinstance(payload, dict) else None
    if not isinstance(season, dict):
        raise ValueError('ESPN response has no football season')
    year = _integer(season.get('year'), 1900, 2200)
    season_type = _season_type(season.get('type'))
    if year is None or season_type is None:
        raise ValueError('ESPN response has an invalid football season')
    if not now.year - 1 <= year <= now.year + 1:
        raise ValueError('ESPN response describes a stale football season')
    leagues = payload.get('leagues') or []
    league = leagues[0] if isinstance(leagues, list) and leagues and isinstance(leagues[0], dict) else {}
    calendar = league.get('calendar') or []
    candidates = []
    valid_entries = 0
    for block in calendar if isinstance(calendar, list) else []:
        if not isinstance(block, dict):
            continue
        kind = _integer(block.get('value'), 1, 4)
        entries = block.get('entries') or []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            number = _integer(entry.get('value'))
            start, end = _date(entry.get('startDate')), _date(entry.get('endDate'))
            if end and isinstance(entry.get('endDate'), str) and re.search(r'T\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$', entry['endDate']):
                end += timedelta(seconds=59, microseconds=999999)
            if kind not in (1, 2, 3, 4) or number is None or not start or not end or start > end:
                continue
            valid_entries += 1
            if kind != 4 and start <= now <= end:
                candidates.append({'season': year, 'season_type': kind, 'week': number,
                    'label': str(entry.get('label') or ('Week ' + str(number)))[:100],
                    'start': start.isoformat(), 'end': end.isoformat(),
                    'source': 'espn_calendar', 'state': 'active'})
    if candidates:
        matching = [entry for entry in candidates if entry['season_type'] == season_type]
        candidates = matching or candidates
        canonical = [entry for entry in candidates if entry['week'] != 999]
        candidates = canonical or candidates
        identities = {(entry['season_type'], entry['week']) for entry in candidates}
        if len(identities) != 1:
            raise ValueError('ESPN football calendar has ambiguous current weeks')
        return candidates[0]
    if valid_entries:
        return {'season': year, 'season_type': season_type, 'week': None,
                'label': 'No active ESPN football week', 'start': None, 'end': None,
                'source': 'espn_calendar', 'state': 'offseason'}
    if calendar:
        raise ValueError('ESPN football calendar is malformed')
    if season_type == 4:
        return {'season': year, 'season_type': 4, 'week': None,
                'label': 'No active ESPN football week', 'start': None, 'end': None,
                'source': 'espn_scoreboard', 'state': 'offseason'}
    week = payload.get('week') or {}
    number = _integer(week.get('number')) if isinstance(week, dict) else None
    if number is None or season_type == 4:
        raise ValueError('ESPN response has no current football week')
    return {'season': year, 'season_type': season_type, 'week': number,
            'label': 'Week ' + str(number), 'start': None, 'end': None,
            'source': 'espn_scoreboard', 'state': 'active'}


def validate_saved_week(value):
    if not isinstance(value, dict) or value.get('source') not in ('espn_calendar', 'espn_scoreboard'):
        return None
    if (_integer(value.get('season'), 1900, 2200) is None or
            _integer(value.get('season_type'), 1, 4) is None or value.get('state') not in ('active', 'offseason')):
        return None
    if value['state'] == 'active' and _integer(value.get('week')) is None:
        return None
    if value['state'] == 'offseason' and value.get('week') is not None:
        return None
    start, end = value.get('start'), value.get('end')
    if (start is None) != (end is None) or (start is not None and
            (not _date(start) or not _date(end) or _date(start) > _date(end))):
        return None
    return {key: value.get(key) for key in ('start', 'end', 'source', 'state')} | {
        'season': _integer(value['season'], 1900, 2200),
        'season_type': _integer(value['season_type'], 1, 4),
        'week': _integer(value.get('week')) if value['state'] == 'active' else None,
        'label': str(value.get('label', ''))[:100]}


def matches_week(event, week):
    if (not isinstance(week, dict) or week.get('state') != 'active' or not isinstance(event, dict)
            or not all(key in week for key in ('season', 'season_type', 'week'))):
        return False
    season = event.get('season') or {}
    selection = event.get('week') or {}
    return (isinstance(season, dict) and isinstance(selection, dict)
            and _integer(season.get('year'), 1900, 2200) == week['season']
            and _season_type(season.get('type')) == week['season_type']
            and _integer(selection.get('number')) == week['week'])


def sort_key(event):
    if not isinstance(event, dict):
        return (float('inf'), '')
    kickoff = _date(event.get('date', event.get('kickoff_iso')))
    return (kickoff.timestamp() if kickoff else float('inf'), str(event.get('id', event.get('event_id', ''))))


def eligible(event, catalog):
    """One major-program participant is enough, including its G5/FCS opponents."""
    if not isinstance(event, dict) or not isinstance(catalog, dict):
        return False
    rows = catalog.get('cfb', [])
    if not isinstance(rows, list):
        return False
    major = {str(row.get('id')) for row in rows
             if isinstance(row, dict) and (row.get('target') is True or str(row.get('id')) == '87')}
    competitions = event.get('competitions')
    if not isinstance(competitions, list):
        return False
    for competition in competitions:
        competitors = competition.get('competitors') if isinstance(competition, dict) else None
        if not isinstance(competitors, list):
            continue
        for competitor in competitors:
            team = competitor.get('team') if isinstance(competitor, dict) else None
            if isinstance(team, dict) and str(team.get('id')) in major:
                return True
    return False
