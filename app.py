import os, json, requests, subprocess, pytz, threading, time as time_module, uuid, random, string
import zipfile, io, shutil, tempfile
import hmac, hashlib, secrets, struct, zlib, stat, ast
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, make_response
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta, timezone
from functools import wraps
from dateutil import parser as dateutil_parser
from score_details import ScoreDetailsCache
import cfb_week


app = Flask(__name__)
app.permanent_session_lifetime = timedelta(hours=1)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  MAX_CONTENT_LENGTH=9 * 1024 * 1024)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, 'settings.json')
KIOSK_CONFIG_FILE = os.path.join(APP_DIR, 'kiosk.json')
KIOSKS_FILE = os.path.join(APP_DIR, 'paired_kiosks.json')
VERSION_FILE = os.path.join(APP_DIR, 'version.txt')


def _load_session_key(path):
    """Keep session signatures private and stable across service restarts."""
    try:
        with open(path, 'rb') as handle:
            key = handle.read()
    except FileNotFoundError:
        fd, temporary = tempfile.mkstemp(prefix='.session-', dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(secrets.token_bytes(32))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass  # Another server worker published its complete key first.
        finally:
            os.unlink(temporary)
        with open(path, 'rb') as handle:
            key = handle.read()
    if len(key) < 32:
        raise RuntimeError('Invalid session key; restore the .session-key backup')
    return key


app.secret_key = _load_session_key(os.path.join(APP_DIR, '.session-key'))
_auth_failures = {}
_auth_lock = threading.Lock()

_pairing_codes = {}  # code -> expiry (time.time())
_settings_lock = threading.RLock()
_kiosks_lock = threading.RLock()
_refresh_lock = threading.Lock()
_last_refresh_attempt = 0.0
_score_request_lock = threading.Lock()
_score_requests = {}  # Bounded daily-response cache, shared by all displays.
# Only successful provider fetches renew these transient live-state timestamps.
# Never persisted: an offline restart may retain scores, but not ball/runner state.
_score_event_received_at = {}
LIVE_DETAIL_MAX_AGE = 90
SCORE_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'score_cache.json')
_last_snapshot_write = 0.0
_last_snapshot_fingerprint = None
_cache_errors = {}
_requested_leagues = {}  # Recently requested kiosk leagues, bounded by known ESPN paths.
_kiosk_server_unreachable = False
_kiosk_last_data = None
_unpaired_kiosk_id = uuid.uuid4().hex
_cache_lock = threading.Lock()
_espn_cache = {"raw_events": {}, "updated_at": None}  # raw_events: path -> [event, ...]
_ap_poll_request = {'retry_at': 0, 'failures': 0}
_score_details = ScoreDetailsCache()
_team_picker_cache = {}
_team_picker_lock = threading.Lock()
_football_catalog_cache = {'signature': None, 'data': {}, 'teams_by_id': {}}
_update_lock = threading.Lock()
_update_state = {
    "available": None,
    "download_url": None,
    "checked_at": None,
    "applying": False,
    "last_result": None,
    "last_message": "",
}

UPLOAD_FOLDER = os.path.join(APP_DIR, 'static', 'uploads')
SPECIALS_FOLDER = os.path.join(UPLOAD_FOLDER, 'specials')
RSS_LOGOS_FOLDER = os.path.join(UPLOAD_FOLDER, 'rss_logos')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SPECIALS_FOLDER, exist_ok=True)
os.makedirs(RSS_LOGOS_FOLDER, exist_ok=True)

# ESPN college football team IDs; conference metadata is not always in scoreboards.
SEC_TEAM_IDS = {'333', '8', '2', '57', '61', '96', '99', '145', '344',
                '201', '142', '2579', '2633', '245', '251', '238'}


def _logo_version():
    try:
        return str(os.stat(os.path.join(UPLOAD_FOLDER, 'logo.png')).st_mtime_ns)
    except OSError:
        return ''


LEAGUE_LABELS = {
    "football/nfl": "NFL",
    "football/cfl": "CFL",
    "football/xfl": "XFL",
    "baseball/mlb": "MLB",
    "basketball/nba": "NBA",
    "basketball/wnba": "WNBA",
    "basketball/euroleague": "EuroLeague",
    "hockey/nhl": "NHL",
    "hockey/mens-college-hockey": "NCAA Hockey",
    "soccer/usa.1": "MLS",
    "soccer/usa.nwsl": "NWSL",
    "soccer/eng.1": "EPL",
    "soccer/eng.2": "EFL Champ",
    "soccer/eng.3": "League One",
    "soccer/eng.4": "League Two",
    "soccer/esp.1": "La Liga",
    "soccer/esp.2": "La Liga 2",
    "soccer/ger.1": "Bundesliga",
    "soccer/ger.2": "2. Bundesliga",
    "soccer/ita.1": "Serie A",
    "soccer/ita.2": "Serie B",
    "soccer/fra.1": "Ligue 1",
    "soccer/fra.2": "Ligue 2",
    "soccer/ned.1": "Eredivisie",
    "soccer/por.1": "Liga Portugal",
    "soccer/sco.1": "Scottish Prem",
    "soccer/mex.1": "Liga MX",
    "soccer/bra.1": "Brasileirão",
    "soccer/arg.1": "LPF Argentina",
    "soccer/tur.1": "Süper Lig",
    "soccer/gre.1": "Greek Super Lg",
    "soccer/uefa.champions": "UEFA UCL",
    "soccer/uefa.europa": "Europa League",
    "soccer/uefa.europa.conf": "Conf. League",
    "soccer/fifa.world": "World Cup",
    "soccer/fifa.worldq": "WC Qualifiers",
    "soccer/fifa.wwc": "Women's WC",
    "football/college-football": "CFB",
    "basketball/mens-college-basketball": "CBK",
    "basketball/womens-college-basketball": "WCBK",
    "baseball/college-baseball": "CBB",
    "softball/college-softball": "CSB",
    "volleyball/womens-college-volleyball": "CVB",
    "volleyball/mens-college-volleyball": "NCAA MensVB",
    "lacrosse/mens-college-lacrosse": "NCAA MensLAX",
    "lacrosse/womens-college-lacrosse": "NCAA WomensLAX",
    "soccer/usa.usl.1": "USL Champ",
    "soccer/usa.usl.l1": "USL L1",
    "baseball/milb": "MiLB",
    "lacrosse/pll": "PLL",
    "lacrosse/nll": "NLL",
    "cricket/current": "Cricket",
    "cricket/8039": "BBL",
    "cricket/8048": "IPL",
    "cricket/8052": "County",
    "cricket/8623": "CPL",
    "cricket/8604": "T20 WC",
    "rugby/267979": "Prem Rugby",
    "rugby/270559": "Top 14",
    "rugby/180659": "6 Nations",
    "rugby/270557": "URC",
    "rugby/242041": "Super Rugby",
    "rugby/289234": "Rugby Tests",
    "rugby/164205": "Rugby WC",
    "rugby/289262": "MLR",
    "racing/nascar-cup": "NASCAR",
    "racing/irl": "IndyCar",
    "racing/f1": "F1",
    "golf/pga": "PGA",
}

ESPN_API_PATHS = {
    "football/nfl": ("football", "nfl"),
    "football/cfl": ("football", "cfl"),
    "football/xfl": ("football", "xfl"),
    "baseball/mlb": ("baseball", "mlb"),
    "basketball/nba": ("basketball", "nba"),
    "basketball/wnba": ("basketball", "wnba"),
    "basketball/euroleague": ("basketball", "euroleague"),
    "hockey/nhl": ("hockey", "nhl"),
    "hockey/mens-college-hockey": ("hockey", "mens-college-hockey"),
    "soccer/usa.1": ("soccer", "usa.1"),
    "soccer/usa.nwsl": ("soccer", "usa.nwsl"),
    "soccer/eng.1": ("soccer", "eng.1"),
    "soccer/eng.2": ("soccer", "eng.2"),
    "soccer/eng.3": ("soccer", "eng.3"),
    "soccer/eng.4": ("soccer", "eng.4"),
    "soccer/esp.1": ("soccer", "esp.1"),
    "soccer/esp.2": ("soccer", "esp.2"),
    "soccer/ger.1": ("soccer", "ger.1"),
    "soccer/ger.2": ("soccer", "ger.2"),
    "soccer/ita.1": ("soccer", "ita.1"),
    "soccer/ita.2": ("soccer", "ita.2"),
    "soccer/fra.1": ("soccer", "fra.1"),
    "soccer/fra.2": ("soccer", "fra.2"),
    "soccer/ned.1": ("soccer", "ned.1"),
    "soccer/por.1": ("soccer", "por.1"),
    "soccer/sco.1": ("soccer", "sco.1"),
    "soccer/mex.1": ("soccer", "mex.1"),
    "soccer/bra.1": ("soccer", "bra.1"),
    "soccer/arg.1": ("soccer", "arg.1"),
    "soccer/tur.1": ("soccer", "tur.1"),
    "soccer/gre.1": ("soccer", "gre.1"),
    "soccer/uefa.champions": ("soccer", "uefa.champions"),
    "soccer/uefa.europa": ("soccer", "uefa.europa"),
    "soccer/uefa.europa.conf": ("soccer", "uefa.europa.conf"),
    "soccer/fifa.world": ("soccer", "fifa.world"),
    "soccer/fifa.worldq": ("soccer", "fifa.worldq"),
    "soccer/fifa.wwc": ("soccer", "fifa.wwc"),
    "football/college-football": ("football", "college-football"),
    "basketball/mens-college-basketball": ("basketball", "mens-college-basketball"),
    "basketball/womens-college-basketball": ("basketball", "womens-college-basketball"),
    "baseball/college-baseball": ("baseball", "college-baseball"),
    "softball/college-softball": ("baseball", "college-softball"),
    "volleyball/womens-college-volleyball": ("volleyball", "womens-college-volleyball"),
    "volleyball/mens-college-volleyball": ("volleyball", "mens-college-volleyball"),
    "lacrosse/mens-college-lacrosse": ("lacrosse", "mens-college-lacrosse"),
    "lacrosse/womens-college-lacrosse": ("lacrosse", "womens-college-lacrosse"),
    "soccer/usa.usl.1": ("soccer", "usa.usl.1"),
    "soccer/usa.usl.l1": ("soccer", "usa.usl.l1"),
    "baseball/milb": ("baseball", "milb"),
    "lacrosse/pll": ("lacrosse", "pll"),
    "lacrosse/nll": ("lacrosse", "nll"),
    "cricket/current": ("cricket", "current"),
    "cricket/8039": ("cricket", "8039"),
    "cricket/8048": ("cricket", "8048"),
    "cricket/8052": ("cricket", "8052"),
    "cricket/8623": ("cricket", "8623"),
    "cricket/8604": ("cricket", "8604"),
    "rugby/267979": ("rugby", "267979"),
    "rugby/270559": ("rugby", "270559"),
    "rugby/180659": ("rugby", "180659"),
    "rugby/270557": ("rugby", "270557"),
    "rugby/242041": ("rugby", "242041"),
    "rugby/289234": ("rugby", "289234"),
    "rugby/164205": ("rugby", "164205"),
    "rugby/289262": ("rugby", "289262"),
    "racing/nascar-cup": ("racing", "nascar-cup"),
    "racing/irl": ("racing", "irl"),
    "racing/f1": ("racing", "f1"),
    "golf/pga": ("golf", "pga"),
}

ESPN_WEB_API_LEAGUES = {"softball/college-softball"}
ESPN_NO_DATE_LEAGUES = {
    "baseball/college-baseball", "softball/college-softball",
    "volleyball/mens-college-volleyball",
    "hockey/mens-college-hockey",
    "lacrosse/mens-college-lacrosse", "lacrosse/womens-college-lacrosse",
    "cricket/current", "cricket/8039", "cricket/8048", "cricket/8052", "cricket/8623", "cricket/8604",
}
MOTORSPORTS_LEAGUES = {"racing/nascar-cup", "racing/irl", "racing/f1"}
MOTORSPORTS_FAV_KEY = {
    "racing/nascar-cup": "nascar_favorites",
    "racing/irl":        "indycar_favorites",
    "racing/f1":         "f1_favorites",
}
GOLF_LEAGUES = {"golf/pga"}


def _event_status(event):
    """Normalize provider status without converting canceled games to finals."""
    status = event.get('status') or {}
    if not isinstance(status, dict):
        status = {}
    info = status.get('type') or {}
    if not isinstance(info, dict):
        info = {}
    detail = str(info.get('shortDetail') or info.get('detail') or info.get('description') or '')
    label = (str(info.get('name') or '') + ' ' + detail).lower()
    state = info.get('state')
    if 'cancel' in label:
        return 'canceled', detail or 'Canceled'
    if 'postpon' in label:
        return 'postponed', detail or 'Postponed'
    if 'delay' in label or 'suspend' in label:
        return 'delayed', detail or 'Delayed'
    if state == 'post' or info.get('completed') is True:
        return 'final', detail or 'Final'
    if state == 'in':
        if 'halftime' in label or 'half time' in label:
            return 'halftime', detail or 'Halftime'
        # Provider period numbering varies by sport; trust its explicit label.
        if 'overtime' in label or any(part.strip('0123456789') == 'ot' for part in label.replace('/', ' ').split()):
            return 'overtime', detail or 'Overtime'
        return 'live', detail or 'Live'
    if state == 'pre':
        return 'scheduled', detail or 'Scheduled'
    return 'unknown', detail or 'Status unavailable'


def _event_key(event):
    """Provider IDs are stable across reschedules and favorite-team matches."""
    if event.get('id'):
        return str(event['id'])
    competitions = event.get('competitions') or []
    competition = competitions[0] if competitions and isinstance(competitions[0], dict) else {}
    teams = sorted(str(c.get('team', {}).get('id') or c.get('team', {}).get('abbreviation') or '')
                   for c in competition.get('competitors', []) if isinstance(c, dict))
    return str(event.get('date', '')) + ':' + ':'.join(teams)


def _refresh_preferences(settings=None):
    settings = settings if settings is not None else get_settings()
    configured = settings.get('score_refresh', {})
    defaults = {'live_seconds': 30, 'upcoming_seconds': 300,
                'idle_seconds': 900, 'final_seconds': 3600}
    minimums = {'live_seconds': 30, 'upcoming_seconds': 60, 'idle_seconds': 300, 'final_seconds': 300}
    return {key: max(minimums[key], configured.get(key, default))
            for key, default in defaults.items()}


def _events_refresh_interval(events, preferences=None):
    preferences = preferences or _refresh_preferences()
    states = [_event_status(event)[0] for event in events]
    if any(state in ('live', 'halftime', 'overtime', 'delayed') for state in states):
        return preferences['live_seconds']
    if 'scheduled' in states:
        # Check on the kickoff boundary even with a long upcoming-game interval.
        now = datetime.now(timezone.utc)
        until_start = []
        for event in events:
            if _event_status(event)[0] != 'scheduled':
                continue
            try:
                start = dateutil_parser.isoparse(event.get('date', ''))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                seconds = (start - now).total_seconds()
                if seconds >= -12 * 3600:
                    until_start.append(max(preferences['live_seconds'], seconds))
            except (TypeError, ValueError, OverflowError):
                pass
        return min([preferences['upcoming_seconds']] + until_start) if until_start else preferences['idle_seconds']
    if states and all(state in ('final', 'canceled', 'postponed') for state in states):
        return preferences['final_seconds']
    return preferences['idle_seconds']


class _LeagueEvents(list):
    """A partial slate carries failures so successful live days can still update."""
    def __init__(self, events=(), errors=(), cfb_week=None):
        super().__init__(events)
        self.errors = list(errors)
        self.cfb_week = cfb_week


def _bounded_slate(events, days_back, days_ahead, tz_str):
    """Prune old outage data and cap memory after long-running partial failures."""
    now = datetime.now(pytz.timezone(tz_str))
    kept = []
    for event in events:
        try:
            parsed = dateutil_parser.isoparse(event.get('date', ''))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            local_date = parsed.astimezone(now.tzinfo).date()
            end_date = local_date
            if event.get('endDate'):
                try:
                    end = dateutil_parser.isoparse(event['endDate'])
                    if end.tzinfo is None:
                        end = end.replace(tzinfo=timezone.utc)
                    end_date = max(local_date, end.astimezone(now.tzinfo).date())
                except (ValueError, TypeError, OverflowError):
                    pass
            # A live multi-day tournament can start before the normal window.
            live = _event_status(event)[0] in ('live', 'halftime', 'overtime', 'delayed')
            back = max(days_back, 7) if live else days_back
            if end_date < now.date() - timedelta(days=back) or local_date > now.date() + timedelta(days=days_ahead):
                continue
        except (ValueError, TypeError, OverflowError):
            pass
        kept.append(event)
    if len(kept) > 2000:
        # Prefer provider-live events, then the closest dates. Preserve stable
        # order for equally dated events rather than shuffling each refresh.
        def priority(event):
            live = _event_status(event)[0] in ('live', 'halftime', 'overtime', 'delayed')
            try:
                parsed = dateutil_parser.isoparse(event.get('date', ''))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                distance = abs((parsed - now).total_seconds())
            except (ValueError, TypeError, OverflowError):
                distance = float('inf')
            return (not live, distance)
        kept = sorted(kept, key=priority)[:2000]
    return kept

HARDCODED_CONFERENCES = {
    "football/college-football": [
        {"id": "8",   "name": "SEC"},
        {"id": "1",   "name": "ACC"},
        {"id": "5",   "name": "Big Ten"},
        {"id": "4",   "name": "Big 12"},
        {"id": "9",   "name": "Pac-12"},
        {"id": "151", "name": "American Athletic"},
        {"id": "17",  "name": "Mountain West"},
        {"id": "37",  "name": "Sun Belt"},
        {"id": "15",  "name": "MAC"},
        {"id": "12",  "name": "Conference USA"},
        {"id": "18",  "name": "Independents"},
    ],
    "basketball/mens-college-basketball": [
        {"id": "23", "name": "SEC"},
        {"id": "2",  "name": "ACC"},
        {"id": "7",  "name": "Big Ten"},
        {"id": "8",  "name": "Big 12"},
        {"id": "4",  "name": "Big East"},
        {"id": "44", "name": "Mountain West"},
        {"id": "62", "name": "American Athletic"},
        {"id": "45", "name": "WCC"},
        {"id": "43", "name": "Atlantic 10"},
    ],
    "basketball/womens-college-basketball": [
        {"id": "23", "name": "SEC"},
        {"id": "2",  "name": "ACC"},
        {"id": "7",  "name": "Big Ten"},
        {"id": "8",  "name": "Big 12"},
        {"id": "4",  "name": "Big East"},
        {"id": "44", "name": "Mountain West"},
        {"id": "62", "name": "American Athletic"},
    ],
    "baseball/college-baseball": [
        {"id": "27", "name": "SEC"},
        {"id": "37", "name": "ACC"},
        {"id": "48", "name": "Big Ten"},
        {"id": "44", "name": "Big 12"},
        {"id": "58", "name": "American Athletic"},
        {"id": "68", "name": "Big East"},
        {"id": "61", "name": "Sun Belt"},
        {"id": "70", "name": "Big West"},
        {"id": "72", "name": "CAA"},
    ],
    "volleyball/womens-college-volleyball": [
        {"id": "71", "name": "SEC"},
        {"id": "49", "name": "ACC"},
        {"id": "54", "name": "Big Ten"},
        {"id": "69", "name": "Big 12"},
        {"id": "52", "name": "Big East"},
        {"id": "57", "name": "American Athletic"},
        {"id": "55", "name": "Big West"},
        {"id": "64", "name": "Missouri Valley"},
    ],
    "softball/college-softball": [
        {"id": "32", "name": "SEC"},
        {"id": "40", "name": "ACC"},
        {"id": "49", "name": "Big Ten"},
        {"id": "45", "name": "Big 12"},
        {"id": "59", "name": "American Athletic"},
        {"id": "64", "name": "Mountain West"},
        {"id": "60", "name": "Sun Belt"},
        {"id": "62", "name": "ASUN"},
    ],
}


# ─── AUTH ───

def _credentials_version():
    credentials = json.dumps(get_settings().get('admin_credentials', {}), sort_keys=True).encode('utf-8')
    return hmac.new(app.secret_key, credentials, hashlib.sha256).hexdigest()


def _valid_admin_session():
    if 'user' not in session:
        return False
    username = get_settings().get('admin_credentials', {}).get('username', 'admin')
    version = _credentials_version()
    if session['user'] != username or session.get('auth_version', version) != version:
        session.clear()
        return False
    # Upgrade a previously signed cookie from before credential versioning.
    session['auth_version'] = version
    return True


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _valid_admin_session():
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized", "status": "unauthorized"}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _valid_admin_session():
            return f(*args, **kwargs)
        auth = request.authorization
        if auth and _authenticate_request(auth.username, auth.password):
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper


def authenticate_linux_user(username, password):
    # Retain the historical name for callers; sudo is not an authentication API
    # (NOPASSWD systems accepted any password through the old fallback).
    if not isinstance(username, str) or not isinstance(password, str) or not password:
        return False
    # A damaged existing file must never silently re-enable admin/root.
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as handle:
                stored = json.load(handle)
            if not isinstance(stored, dict):
                return False
            if 'admin_credentials' in stored:
                _validate_settings({'admin_credentials': stored['admin_credentials']})
        except (OSError, ValueError):
            return False
    creds = get_settings().get('admin_credentials', {})
    if not hmac.compare_digest(creds.get('username', '').encode('utf-8'), username.encode('utf-8')):
        return False
    if creds.get('password_hash'):
        return _password_hash_matches(creds['password_hash'], password)
    if not hmac.compare_digest(creds.get('password', '').encode('utf-8'), password.encode('utf-8')):
        return False
    # Legacy files and the initial admin/root account migrate on first login.
    try:
        save_settings({'admin_credentials': {'username': username,
                       'password_hash': generate_password_hash(password, method='pbkdf2:sha256:600000')}})
    except OSError:
        app.logger.warning('Legacy credential migration failed; check configuration permissions')
    return True


def _password_hash_matches(password_hash, candidate):
    try:
        return check_password_hash(password_hash, candidate)
    except (ValueError, TypeError):
        return False


def _authenticate_request(username, password):
    """Bound failed login attempts without retaining attacker-controlled identities."""
    now = time_module.monotonic()
    address = request.remote_addr or 'local'
    with _auth_lock:
        for key, attempts in list(_auth_failures.items()):
            if now - attempts[0] > 300:
                _auth_failures.pop(key, None)
        attempts = _auth_failures.get(address, (now, 0))
        if attempts[1] >= 10:
            return False
    if authenticate_linux_user(username, password):
        with _auth_lock:
            _auth_failures.pop(address, None)
        return True
    with _auth_lock:
        if len(_auth_failures) < 1024 or address in _auth_failures:
            _auth_failures[address] = (attempts[0], attempts[1] + 1)
    return False


@app.before_request
def _protect_settings_requests():
    # Public score queries and pairing claims intentionally support other displays.
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE') or request.path in (
            '/api/data', '/api/pairing/claim'):
        return None
    origin = request.headers.get('Origin') or request.headers.get('Referer')
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return jsonify({'error': 'Invalid request origin'}), 403
        if (parsed.scheme, parsed.netloc) != (request.scheme, request.host):
            return jsonify({'error': 'Cross-origin settings changes are not allowed'}), 403
    return None


# ─── SETTINGS ───

# Default display palette. Kept at module level so the auto-palette resolver
# can merge user overrides on top of it without re-reading settings.json.
_DEFAULT_COLORS = {
    "live": "#00E676",
    "final": "#FF1744",
    "flash": "#FFD600",
    "team_abbr": "#ffffff",
    "league_label": "#099afc",
    "ticker_base": "#ffffff",
    "winner": "#00E676",
    "loser": "#FF1744",
    "tie_score": "#FFD600",
    "fav_abbr": "#F5A800",
    "fav_score": "#F5A800",
    "nascar_num": "#FFD600",
    "weather": "#dddddd",
    "vs_color": "#ffffff",
    "pre_time": "#ffffff",
    "score_sep": "#888888",
    "ticker_live": "#00E676",
    "ticker_final": "#FF1744",
    "ticker_sep": "#444444",
    "race_pos": "#F5A800",
    "race_laps": "#888888",
    "card_subtext": "#555555",
    # dark mode surface colors
    "dark_bg": "#080808",
    "dark_card": "#111111",
    "dark_border": "#2a2a2a",
    "dark_vs": "#ffffff",
    "dark_ticker_bg": "#000000",
    # light mode surface colors
    "light_bg": "#c4d6f0",
    "light_card": "#ffffff",
    "light_border": "#ffffff",
    "light_vs": "#445566",
    # previously-hardcoded elements (now configurable)
    "header_bg_dark": "#080808",
    "header_bg_light": "#eef2f8",
    "header_border": "#2a2a2a",
    "card_border": "#ffffff",
    "logo_glow": "#ffffff",
    "ticker_border": "#099afc",
    "ticker_border_cycle": True,
    "final_badge_text": "#ffffff",
    "rss_label": "#ffffff",
    "rss_event": "#ffffff",
    "rss_subevent": "#888888",
    "special_text": "#cccccc",
    "golf_pos": "#F5A800",
    "race_event": "#666666",
}


def _migrate_conference_filters(data):
    """Keep legacy UI selections when correcting the SEC/Pac-12 ESPN IDs."""
    result = dict(data)
    if result.get('conference_filters_version') != 2:
        original = result.get('league_conferences', {})
        conferences = dict(original) if isinstance(original, dict) else {}
        value = conferences.get('football/college-football')
        if isinstance(value, str) or (isinstance(value, list) and all(isinstance(group, str) for group in value)):
            def corrected(group):
                return {'9': '8', '21': '9'}.get(group, group)
            conferences['football/college-football'] = ([corrected(group) for group in value]
                if isinstance(value, list) else ','.join(corrected(group) for group in value.split(',')))
            result['league_conferences'] = conferences
    result['conference_filters_version'] = 2
    return result


def get_settings():
    default = {
        "city": "Auburn, NE",
        "display_name": "Scoreboard",
        "header_color": "#F5A800",
        "leagues": ["football/college-football", "football/nfl", "basketball/nba", "baseball/mlb", "golf/pga"],
        "football_priority": True,
        "football_display": "both",
        "cfb_coverage": "all_power5",
        "cfb_refresh_seconds": 180,
        "scorecard_filter": "both",
        "scorecard_include_completed": False,
        "show_logo_slide": True,
        "teams": ["football/college-football:TA&M", "football/nfl:HOU", "baseball/mlb:HOU", "basketball/nba:HOU"],
        "league_conferences": {},
        "conference_filters_version": 2,
        "timezone": "America/Chicago",
        "clock_format": "12h",
        "header_visibility": "auto",
        "show_time_bar": True,
        "show_title_bar": True,
        "display_mode": "hybrid",
        "score_refresh": {"live_seconds": 30, "upcoming_seconds": 300,
                          "idle_seconds": 900, "final_seconds": 3600},
        "admin_credentials": {"username": "admin", "password": "root"},
        "schedule": {
            "shutdown": {"enabled": False, "time": "23:00"},
            "startup":  {"enabled": False, "time": "07:00"},
        },
        "specials": [],
        "nascar_favorites": [],
        "indycar_favorites": [],
        "f1_favorites": [],
        "golf_favorites": [],
        "cast_orientation": "auto",
        "theme": "dark",
        # "auto" derives the whole palette from the favorite team's colors;
        # "manual" uses the explicit colors below.
        "color_mode": "auto",
        # Which team drives the auto palette. Blank = first favorite in "teams".
        "palette_team": "",
        "colors": dict(_DEFAULT_COLORS),
        "font_primary": "Barlow Condensed",
        # Default to kiosk mode if kiosk.json is present (placed by install.sh in kiosk mode)
        "device_mode": "kiosk" if os.path.exists(KIOSK_CONFIG_FILE) else "server",
        "server_enable_display": True,
        # Kiosk installs serve on 5001 (install.sh points the kiosk browser there); server/combined use 5000
        "port": 5001 if os.path.exists(KIOSK_CONFIG_FILE) else 5000,
        "update": {
            "source_url": "https://api.github.com/repos/auggnation/Auggment-Scoreboard/releases/latest",
            "auto_check": True,
            "check_hours": 6,
            "auto_apply": False,
        },
        "slide_duration": 8,
        "logo_slide_duration": 8,
        "transition_duration_ms": 500,
        "slide_transition": "slide-right",
        "ticker_speed": 120,
        "date_windows": {},
        # Local sports: manual games + parsed feeds (RSS/iCal/MaxPreps/Thrillshare).
        # home_team_keywords identifies YOUR team in a parsed event string so the
        # app can split "@" / "at" / "vs" matchups and highlight the right side.
        "local_schedule": {
            "items": [],
            "rss_feeds": [],
            "home_team_keywords": [],
        },
    }
    if not os.path.exists(SETTINGS_FILE):
        return default
    try:
        with open(SETTINGS_FILE, 'r') as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            return default
        for key, value in list(loaded.items()):
            try:
                _validate_settings({key: value})
            except ValueError:
                loaded.pop(key)
        loaded = _migrate_conference_filters(loaded)
        merged = {**default, **loaded}
        # Deep merge nested dicts so missing sub-keys fall back to defaults
        for key in ('update', 'colors', 'schedule', 'date_windows', 'local_schedule', 'score_refresh'):
            if key in default and isinstance(default[key], dict):
                merged[key] = {**default[key], **loaded.get(key, {})}
        return merged
    except Exception:
        return default


def _validate_settings(data):
    """Reject malformed settings before they reach startup or score processing."""
    if not isinstance(data, dict):
        raise ValueError('Settings must be a JSON object')
    if 'conference_filters_version' in data and (type(data['conference_filters_version']) is not int or
                                                data['conference_filters_version'] not in (1, 2)):
        raise ValueError('Invalid conference filters version')
    for key in ('city', 'display_name', 'header_color', 'font_primary', 'palette_team', 'server_url', 'kiosk_name', 'auth_token'):
        if key in data and not isinstance(data[key], str):
            raise ValueError(key + ' must be text')
    for key in ('clock_format', 'device_mode', 'theme', 'cast_orientation', 'display_mode', 'color_mode', 'slide_transition', 'football_display', 'header_visibility', 'cfb_coverage', 'scorecard_filter'):
        choices = {'clock_format': ('12h', '24h', 'hidden'),
                   'device_mode': ('server', 'kiosk'), 'theme': ('dark', 'light'),
                   'cast_orientation': ('auto', 'horizontal', 'vertical', 'phone'),
                   'display_mode': ('scoreboard', 'ticker', 'hybrid'),
                   'football_display': ('both', 'cfb', 'nfl', 'weekly'),
                   'cfb_coverage': ('all_power5', 'favorites'),
                   'scorecard_filter': ('live', 'upcoming', 'both'),
                   'header_visibility': ('always', 'hidden', 'auto'),
                   'color_mode': ('auto', 'manual'),
                   'slide_transition': ('slide-right', 'slide-left', 'slide-top', 'slide-bottom', 'fade')}
        if key in data and data[key] not in choices[key]:
            raise ValueError('Invalid ' + key)
    for key in ('show_logo_slide', 'football_priority', 'server_enable_display', 'show_time_bar', 'show_title_bar', 'scorecard_include_completed'):
        if key in data and not isinstance(data[key], bool):
            raise ValueError(key + ' must be true or false')
    for key in ('leagues', 'teams', 'nascar_favorites', 'indycar_favorites', 'f1_favorites', 'golf_favorites'):
        if key in data and (not isinstance(data[key], list) or
                            any(not isinstance(x, str) for x in data[key]) or len(data[key]) > 2000):
            raise ValueError('Invalid ' + key)
    for key in ('specials', 'slide_playlist'):
        if key in data and (not isinstance(data[key], list) or any(not isinstance(x, dict) for x in data[key])):
            raise ValueError('Invalid ' + key)
        for item in data.get(key, []):
            for field in ('uid', 'key', 'type', 'title', 'body', 'image', 'url', 'url_label', 'name', 'series', 'color', 'schedule_type'):
                if field in item and item[field] is not None and not isinstance(item[field], str):
                    raise ValueError(key + ': ' + field + ' must be text')
    for key in ('colors', 'schedule', 'date_windows', 'local_schedule', 'update', 'admin_credentials', 'league_conferences', 'score_refresh'):
        if key in data and not isinstance(data[key], dict):
            raise ValueError(key + ' must be an object')
    for key, low, high in (('port', 1, 65535), ('slide_duration', 1, 3600), ('ticker_speed', 1, 1000),
                           ('logo_slide_duration', 1, 3600), ('transition_duration_ms', 0, 2000),
                           ('cfb_refresh_seconds', 30, 900)):
        if key in data and (type(data[key]) not in (int, float) or not low <= data[key] <= high or
                            (key in ('port', 'cfb_refresh_seconds') and type(data[key]) is not int)):
            raise ValueError('Invalid ' + key)
    for key, low, high in (('live_seconds', 30, 300), ('upcoming_seconds', 60, 3600),
                          ('idle_seconds', 300, 21600), ('final_seconds', 300, 86400)):
        value = data.get('score_refresh', {}).get(key)
        if key in data.get('score_refresh', {}) and (type(value) is not int or not low <= value <= high):
            raise ValueError(key.replace('_', ' ') + f' must be {low}–{high} seconds')
    if 'timezone' in data:
        try:
            pytz.timezone(data['timezone'])
        except Exception:
            raise ValueError('Invalid timezone')
    for window in data.get('date_windows', {}).values():
        if not isinstance(window, dict):
            raise ValueError('Invalid date window')
        for key in ('days_back', 'days_ahead'):
            if key in window and (type(window[key]) is not int or not 0 <= window[key] <= 14):
                raise ValueError('Date windows must be 0–14 days')
    for value in data.get('league_conferences', {}).values():
        if not isinstance(value, (str, list)) or (isinstance(value, list) and any(not isinstance(x, str) for x in value)):
            raise ValueError('Invalid conference selection')
    for key, value in data.get('colors', {}).items():
        if key == 'ticker_border_cycle':
            if not isinstance(value, bool):
                raise ValueError('Invalid ticker border toggle')
        elif not isinstance(value, str):
            raise ValueError('Invalid color')
    for key in ('username', 'password', 'password_hash'):
        if key in data.get('admin_credentials', {}) and not isinstance(data['admin_credentials'][key], str):
            raise ValueError('Invalid admin credentials')
    for key in ('shutdown', 'startup'):
        entry = data.get('schedule', {}).get(key, {})
        if not isinstance(entry, dict):
            raise ValueError('Invalid display schedule')
        if 'time' in entry:
            try:
                datetime.strptime(entry['time'], '%H:%M')
            except (ValueError, TypeError):
                raise ValueError('Invalid schedule time')
    update = data.get('update', {})
    if 'source_url' in update and not isinstance(update['source_url'], str):
        raise ValueError('Invalid update URL')
    if 'check_hours' in update and (type(update['check_hours']) not in (int, float) or not 1 <= update['check_hours'] <= 168):
        raise ValueError('Update interval must be 1–168 hours')
    local = data.get('local_schedule', {})
    if 'home_team_keywords' in local and (not isinstance(local['home_team_keywords'], list) or any(not isinstance(x, str) for x in local['home_team_keywords'])):
        raise ValueError('Invalid home team keywords')
    for key in ('items', 'rss_feeds'):
        if key in local and (not isinstance(local[key], list) or any(not isinstance(x, dict) for x in local[key])):
            raise ValueError('Invalid local schedule')
        for item in local.get(key, []):
            for field in ('url', 'label', 'logo', 'category', 'away_team', 'home_team', 'date', 'time', 'location'):
                if field in item and item[field] is not None and not isinstance(item[field], str):
                    raise ValueError('Local schedule: ' + field + ' must be text')


def save_settings(data):
    _validate_settings(data)
    data = _migrate_conference_filters(data)
    with _settings_lock:
        for field in ('server_url', 'kiosk_name', 'paired', 'kiosk_id', 'auth_token'):
            data.pop(field, None)
        # Merge with what's already on disk so missing payload fields don't silently erase stored values
        existing = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    existing = json.load(f)
            except Exception:
                pass
        if not isinstance(existing, dict):
            existing = {}
        existing = _migrate_conference_filters(existing)
        if 'admin_credentials' in data:
            incoming = data['admin_credentials']
            credentials = dict(get_settings()['admin_credentials'])
            username = incoming.get('username', credentials.get('username', 'admin')).strip()
            if not username or len(username) > 80 or any(ord(c) < 32 for c in username):
                raise ValueError('Username must contain 1–80 printable characters')
            credentials['username'] = username
            password = incoming.get('password', '')
            if password:
                if not 8 <= len(password) <= 256:
                    raise ValueError('New passwords must contain 8–256 characters')
                credentials['password_hash'] = generate_password_hash(password, method='pbkdf2:sha256:600000')
            elif incoming.get('password_hash'):
                credentials['password_hash'] = incoming['password_hash']
            elif not credentials.get('password_hash'):
                credentials['password_hash'] = generate_password_hash(credentials.get('password', 'root'), method='pbkdf2:sha256:600000')
            credentials.pop('password', None)
            data['admin_credentials'] = credentials
        merged = {**existing, **data}
        # Deep-merge nested dicts — incoming data wins for any key it provides
        for key in ('update', 'colors', 'schedule', 'date_windows', 'local_schedule', 'score_refresh'):
            if isinstance(existing.get(key), dict) and isinstance(data.get(key), dict):
                merged[key] = {**existing[key], **data[key]}
        merged['last_saved'] = datetime.now(timezone.utc).isoformat()
        directory = os.path.dirname(os.path.abspath(SETTINGS_FILE))
        fd, temporary = tempfile.mkstemp(prefix='.settings-', suffix='.json', dir=directory)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(merged, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, SETTINGS_FILE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

# ─── KIOSK CONFIG ───

def get_kiosk_config():
    default = {"server_url": "", "kiosk_id": "", "kiosk_name": "Kiosk", "paired": False, "auth_token": ""}
    if not os.path.exists(KIOSK_CONFIG_FILE):
        # Reading server settings must not create kiosk.json and change the
        # inferred device mode/port on the next restart. Persist only on writes.
        default['kiosk_id'] = _unpaired_kiosk_id
        return default
    try:
        with open(KIOSK_CONFIG_FILE) as f:
            cfg = {**default, **json.load(f)}
        if not cfg.get('kiosk_id'):
            cfg['kiosk_id'] = uuid.uuid4().hex
            save_kiosk_config(cfg)
        return cfg
    except Exception:
        return default


def save_kiosk_config(updates):
    with _settings_lock:
        try:
            with open(KIOSK_CONFIG_FILE) as f:
                existing = json.load(f)
            if not isinstance(existing, dict):
                existing = {}
        except (OSError, ValueError):
            existing = {}
        merged = {**existing, **updates}
        allowed = ('server_url', 'kiosk_id', 'kiosk_name', 'paired', 'auth_token')
        _atomic_json_file(KIOSK_CONFIG_FILE, {k: merged[k] for k in allowed if k in merged})


def _atomic_json_file(path, value):
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix='.config-', suffix='.json', dir=directory)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# ─── KIOSK REGISTRY ───

def get_kiosks():
    if not os.path.exists(KIOSKS_FILE):
        return {}
    try:
        with open(KIOSKS_FILE) as f:
            data = json.load(f)
        return {key: value for key, value in data.items() if isinstance(value, dict)} if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_kiosks(kiosks):
    with _settings_lock:
        _atomic_json_file(KIOSKS_FILE, kiosks)


def _registry_transaction(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        with _kiosks_lock:
            return function(*args, **kwargs)
    return wrapper


# ─── ESPN CACHE ───

_NASCAR_SCHEDULE_CACHE = {}  # year -> {race_id -> {race_name, race_date}}

def _fetch_nascar_com_events():
    """Fetch live NASCAR Cup race data from NASCAR.com and return ESPN-compatible event list."""
    response = requests.get('https://cf.nascar.com/cacher/live/live-feed.json', timeout=6,
                            headers={'User-Agent': 'Mozilla/5.0'})
    response.raise_for_status()
    live = response.json()
    if not isinstance(live, dict):
        raise ValueError('Invalid NASCAR live response')
    vehicles = live.get('vehicles', [])
    if not vehicles:
        return []

    flag_state = live.get('flag_state', 0)
    lap = live.get('lap_number', 0)
    laps_in_race = live.get('laps_in_race', 0)
    race_id = live.get('race_id')
    if race_id is None:
        raise ValueError('NASCAR response has no race identity')

    # Race is complete if laps done, or flag is checkered (4) or any post-race flag
    race_complete = (laps_in_race > 0 and lap >= laps_in_race) or flag_state == 4
    if race_complete:
        state = 'post'
        status_detail = 'Final'
    elif flag_state == 0 and lap == 0:
        state = 'pre'
        status_detail = 'Scheduled'
    else:
        state = 'in'
        flag_label = {1: 'Green', 2: 'Yellow', 3: 'Red', 8: 'Caution', 9: 'Debris'}.get(flag_state, '')
        status_detail = f"Lap {lap} of {laps_in_race}" + (f" ({flag_label})" if flag_label else "")

    # Get race info (name + date) from schedule cache
    year = datetime.now().year
    if year not in _NASCAR_SCHEDULE_CACHE:
        try:
            response = requests.get(f'https://cf.nascar.com/cacher/{year}/1/race_list_basic.json',
                                    timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()
            sched = response.json()
            if not isinstance(sched, list):
                raise ValueError('Invalid NASCAR schedule response')
            _NASCAR_SCHEDULE_CACHE[year] = {
                r['race_id']: {'name': r.get('race_name', 'NASCAR Cup Race'),
                               'date': r.get('race_date') or r.get('date_scheduled', '')}
                for r in sched if 'race_id' in r
            }
        except (requests.RequestException, ValueError):
            pass  # Retry later; an unavailable schedule is not an empty season.

    race_info = _NASCAR_SCHEDULE_CACHE.get(year, {}).get(race_id, {})
    race_name = race_info.get('name', 'NASCAR Cup Race')
    race_date_str = race_info.get('date', '') or live.get('race_date', '')

    sorted_vehicles = sorted(
        [v for v in vehicles if v.get('running_position')],
        key=lambda v: v['running_position']
    )

    competitors = []
    for v in sorted_vehicles:
        drv = v.get('driver', {})
        full_name = drv.get('full_name', '') or f"{drv.get('first_name', '')} {drv.get('last_name', '')}".strip()
        last = drv.get('last_name', '')
        first_init = (drv.get('first_name', '') or '')[:1]
        short_name = f"{first_init}. {last}" if first_init and last else full_name
        competitors.append({
            'order': v['running_position'],
            'score': str(v['running_position']),
            'athlete': {
                'displayName': full_name,
                'shortName': short_name,
                'jersey': str(v.get('vehicle_number', '')),
            },
        })

    _FLAG_LABELS = {1:'Green',2:'Yellow',3:'Red',4:'Checkered',8:'Caution',9:'Debris',0:'Pre-Race'}
    return [{
        'id': f'nascar-{race_id}',
        'date': race_date_str,  # Never invent today's date when the source omits it.
        'name': race_name,
        'shortName': race_name,
        'status': {'type': {'state': state, 'shortDetail': status_detail}},
        'competitions': [{'competitors': competitors}],
        '_nascar_flag_label': _FLAG_LABELS.get(flag_state, '') if not race_complete else 'Checkered',
        '_nascar_lap': lap,
        '_nascar_laps_in_race': laps_in_race,
    }]


def _discover_espn_series(sport):
    ids = []
    seen = set()
    for region in ("us", "in", "gb", "au", "za"):
        try:
            r = requests.get(
                f"https://site.web.api.espn.com/apis/personalized/v2/scoreboard/header?sport={sport}&region={region}&lang=en",
                timeout=8,
            )
            if not r.ok:
                continue
            for s in r.json().get("sports", []):
                for lg in s.get("leagues") or []:
                    lid = str(lg.get("slug") or lg.get("id") or "")
                    if lid and lid not in seen:
                        seen.add(lid)
                        ids.append(lid)
        except Exception:
            continue
    return ids


def _fetch_discovered_events(sport, series_ids):
    events = []
    seen = set()
    for lid in series_ids:
        try:
            r = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{lid}/scoreboard",
                timeout=8,
            )
            if not r.ok:
                continue
            for e in r.json().get("events", []):
                eid = e.get("id")
                if eid and eid not in seen:
                    seen.add(eid)
                    events.append(e)
        except Exception:
            continue
    return events


def _cfb_refresh_interval(settings=None):
    settings = settings if settings is not None else get_settings()
    interval = settings.get('cfb_refresh_seconds', 180)
    demand = _requested_leagues.get(cfb_week.CFB, {})
    if isinstance(demand, dict):
        recent = [value for value, seen in demand.get('refreshes', {}).items()
                  if type(value) is int and 30 <= value <= 900 and time_module.monotonic() - seen <= 900]
        interval = min([interval] + recent)
    return interval


def _complete_cfb_requested(settings=None):
    settings = settings if settings is not None else get_settings()
    if settings.get('cfb_coverage', 'all_power5') == 'all_power5':
        return True
    demand = _requested_leagues.get(cfb_week.CFB, {})
    return (isinstance(demand, dict) and demand.get('complete_week') is True
            and time_module.monotonic() - demand.get('complete_week_seen_at', float('-inf')) <= 900)


def _fetch_cfb_week():
    """A complete official FBS week, independent of favorites/date/conference windows."""
    base = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard'
    interval = _cfb_refresh_interval()
    url = base + '?groups=80&limit=1000'
    _request_score_events(url, refresh_seconds=interval)
    source = _score_requests.get(url, {}).get('metadata', {})
    week = cfb_week.select_week(source, datetime.now(timezone.utc))
    if week['state'] == 'offseason':
        return _LeagueEvents([], cfb_week=week)
    # The default endpoint is only a calendar bootstrap, never proof that a
    # featured/default slate covers the week. Always request the explicit week.
    url = (base + '?groups=80&limit=1000&dates=' + str(week['season']) +
           '&seasontype=' + str(week['season_type']) + '&week=' + str(week['week']))
    events = _request_score_events(url, refresh_seconds=interval)
    source = _score_requests.get(url, {}).get('metadata', {})
    if not cfb_week.matches_week(source, week):
        raise ValueError('ESPN did not confirm the requested football week')
    matching = [event for event in events if cfb_week.matches_week(event, week)]
    if events and not matching:
        raise ValueError('ESPN returned no games matching the selected football week')
    deduplicated = {_event_key(event): event for event in matching}
    return _LeagueEvents(sorted(deduplicated.values(), key=cfb_week.sort_key), cfb_week=week)


def _fetch_league_raw(path, league_conferences, days_back=0, days_ahead=14):
    if path == cfb_week.CFB and _complete_cfb_requested():
        return _fetch_cfb_week()
    if path == "cricket/current":
        return _fetch_discovered_events("cricket", _discover_espn_series("cricket"))
    sport, league = ESPN_API_PATHS.get(path, (path.split('/')[0], path.split('/')[-1]))
    # Query dates in the configured display zone, rather than the server's zone.
    now = datetime.now(pytz.timezone(get_settings().get('timezone', 'America/Chicago')))
    start = now - timedelta(days=days_back)
    end = now + timedelta(days=days_ahead)
    base_host = "site.web.api.espn.com" if path in ESPN_WEB_API_LEAGUES else "site.api.espn.com"
    base_url = f"https://{base_host}/apis/site/v2/sports/{sport}/{league}/scoreboard"

    def _groups_param():
        conf_val = league_conferences.get(path, '')
        conf_id = ','.join(conf_val) if isinstance(conf_val, list) else conf_val
        return f"groups={conf_id}" if conf_id else ''


    events = []
    failures = []
    if path in ESPN_NO_DATE_LEAGUES:
        url = base_url
        qs = _groups_param()
        if qs:
            url += f"?{qs}"
        events = _request_score_events(url)
        if not events and qs:
            events = _request_score_events(base_url)
    else:
        # ESPN's hyphenated dates=START-END range now returns HTTP 400 ("Failed
        # to get events endpoint"), so fetch each day separately and merge.
        # This also lets the date window widen beyond ESPN's default slate.
        def _fetch_range(with_groups):
            fetched = []
            seen = set()
            with requests.Session() as s:
                day = start
                while day <= end:
                    url = f"{base_url}?dates={day.strftime('%Y%m%d')}"
                    qs = _groups_param() if with_groups else ''
                    if qs:
                        url += f"&{qs}"
                    if path == 'football/college-football':
                        url += '&limit=1000'
                    try:
                        daily_events = _request_score_events(url, session=s, ttl=30 if day.date() == now.date() else 300)
                    except (requests.RequestException, ValueError) as error:
                        # A failed future day must not prevent successful live
                        # scores from updating. Retain that day's cached data.
                        failures.append(str(error))
                        with _score_request_lock:
                            daily_events = _score_requests.get(url, {}).get('events', [])
                    for e in daily_events:
                        if _event_key(e) not in seen:
                            seen.add(_event_key(e))
                            fetched.append(e)
                    day += timedelta(days=1)
            return fetched

        events = _fetch_range(True)
        if not events and not failures and _groups_param():
            # A stale/empty conference group filter can make ESPN return nothing
            # (or stray empty events); fall back to the unfiltered slate.
            events = _fetch_range(False)

    # Fall back to NASCAR.com live feed if ESPN has no data
    if not events and path == 'racing/nascar-cup':
        try:
            events = _fetch_nascar_com_events()
        except Exception as e:
            print(f"[cache] nascar.com fallback: {e}")
            failures.append(str(e))

    try:
        return _LeagueEvents(sorted(events, key=lambda e: e.get('date', '')), failures)
    except Exception:
        return _LeagueEvents(events, failures)


def _priority_leagues(leagues, settings):
    if settings.get('football_priority', True):
        return list(dict.fromkeys(['football/college-football', 'football/nfl'] + list(leagues)))
    return leagues


def _football_display_mode(settings, tz_str, now=None):
    """Resolve weekly football visibility using the display's local calendar."""
    mode = settings.get('football_display', 'both')
    if mode != 'weekly':
        return mode if mode in ('both', 'cfb', 'nfl') else 'both'
    now = now if now is not None else datetime.now(timezone.utc)
    try:
        weekday = now.astimezone(pytz.timezone(tz_str)).weekday()
    except pytz.UnknownTimeZoneError:
        weekday = now.astimezone(timezone.utc).weekday()
    return {5: 'cfb', 6: 'nfl'}.get(weekday, 'both')


def _apply_football_display(data, settings, tz_str, now=None):
    """Filter presentation only; never alter favorites or retained source data."""
    mode = _football_display_mode(settings, tz_str, now)
    hidden = {'cfb': 'football/nfl', 'nfl': 'football/college-football'}.get(mode)
    result = dict(data)
    result['football_display'] = settings.get('football_display', 'both')
    result['football_display_active'] = mode
    if hidden:
        result['teams'] = [team for team in data.get('teams', [])
                           if team.get('league_path') != hidden]
        parts = []
        for part in data.get('ticker_parts', []):
            games = [game for game in part.get('games', [])
                     if game.get('league_path') != hidden]
            if games:
                parts.append({**part, 'games': games})
        result['ticker_parts'] = parts
    return result


def _apply_scorecard_filter(data, settings):
    """The main scorecard choice never removes games from the bottom ticker."""
    result = dict(data)
    mode = settings.get('scorecard_filter', 'both')
    completed = settings.get('scorecard_include_completed', False)
    live = {'live', 'halftime', 'overtime'} if mode in ('live', 'both') else set()
    states = live | ({'scheduled'} if mode in ('upcoming', 'both') else set())
    if completed:
        states.add('final')
    result['teams'] = [card for card in data.get('teams', []) if card.get('game_state') in states]
    result['scorecard_filter'] = mode
    result['scorecard_include_completed'] = completed
    if isinstance(data.get('cfb_week'), dict):
        result['cfb_week'] = {**data['cfb_week'], 'displayed_game_count': sum(
            card.get('league_path') == cfb_week.CFB for card in result['teams'])}
    description = {'live': 'live', 'upcoming': 'upcoming', 'both': 'live or upcoming'}.get(mode, 'live or upcoming')
    result['scorecard_empty_message'] = ('' if result['teams'] else
        'No ' + description + (' or completed' if completed else '') + ' games match your scorecard settings.')
    return result


def _parse_ap_poll(payload):
    """Read the explicitly identified AP poll, never Coaches/CFP/curated ranks."""
    if not isinstance(payload, dict) or not isinstance(payload.get('rankings'), list):
        raise ValueError('Invalid college rankings response')
    for poll in payload['rankings']:
        if not isinstance(poll, dict) or poll.get('type') != 'ap':
            continue
        season = poll.get('season') or {}
        year = season.get('year') if isinstance(season, dict) else None
        rows = poll.get('ranks')
        if type(year) is not int or not 2000 <= year <= 2100 or not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('Invalid AP poll season or ranks')
        ranks = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            team = row.get('team') or {}
            team_id = str(team.get('id', '')) if isinstance(team, dict) else ''
            rank = row.get('current')
            if team_id.isascii() and team_id.isdigit() and len(team_id) <= 10 and type(rank) is int and 1 <= rank <= 25:
                ranks[team_id] = rank
        if not ranks:
            raise ValueError('AP poll has no valid ranked teams')
        return {'ranks': ranks, 'season': year,
                'date': poll.get('date', '') if isinstance(poll.get('date', ''), str) else '',
                'updated_at': datetime.now(timezone.utc).isoformat()}
    raise ValueError('AP poll unavailable')


def _refresh_ap_poll():
    """Low-frequency background lookup, independent of score request success."""
    now = time_module.monotonic()
    if now < _ap_poll_request['retry_at']:
        return False
    response = None
    try:
        response = requests.get(
            'https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings',
            timeout=(3, 8))
        response.raise_for_status()
        poll = _parse_ap_poll(response.json())
        with _cache_lock:
            _espn_cache['ap_poll'] = poll
        _ap_poll_request.update(retry_at=now + 3600, failures=0)
        return True
    except (requests.RequestException, ValueError) as error:
        failures = min(5, _ap_poll_request['failures'] + 1)
        delay = min(3600, 300 * 2 ** (failures - 1))
        if response is not None:
            try:
                delay = max(delay, min(86400, int(response.headers.get('Retry-After', '0'))))
            except (TypeError, ValueError):
                pass
        _ap_poll_request.update(retry_at=now + delay, failures=failures)
        print(f'[rankings] retaining saved AP poll: {error}')
        return False


def _ap_rank(competitor, event):
    poll = _espn_cache.get('ap_poll') or {}
    season = event.get('season') or {}
    if not isinstance(season, dict) or type(season.get('year')) is not int or season['year'] != poll.get('season'):
        return None
    team = competitor.get('team') or {}
    rank = poll.get('ranks', {}).get(str(team.get('id', ''))) if isinstance(team, dict) else None
    return rank if type(rank) is int and 1 <= rank <= 25 else None


def _live_event_signature(event):
    """Identify the current live situation, without retaining large play histories."""
    try:
        competition = event['competitions'][0]
        situation = competition.get('situation') or {}
        keys = ('possession', 'possessionText', 'down', 'distance', 'yardLine',
                'isRedZone', 'downDistanceText', 'shortDownDistanceText',
                'onFirst', 'onSecond', 'onThird', 'outs')
        state = [event.get('status'), competition.get('status'),
                 {key: situation[key] for key in keys if key in situation},
                 [(c.get('homeAway'), c.get('score')) for c in competition.get('competitors', [])]]
        return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).digest()
    except (KeyError, TypeError, IndexError, AttributeError, ValueError):
        return None


def _live_detail_ttl(path, event):
    stamp = _score_event_received_at.get(str(event.get('id', '')))
    if path in _cache_errors or not stamp or stamp[1] != _live_event_signature(event):
        return 0
    age = time_module.monotonic() - stamp[0]
    return max(0, LIVE_DETAIL_MAX_AGE - age) if age >= 0 else 0


def _trim_live_details(data, elapsed=0, stale=False):
    """Forward a kiosk response without extending the upstream live-state lifetime."""
    data = dict(data)
    teams = []
    for card in data.get('teams', []):
        card = dict(card)
        if not any(key in card for key in ('live_detail_ttl_seconds', 'football_tracker', 'baseball_tracker')):
            teams.append(card)  # Older servers retain their original score payload.
            continue
        ttl = card.get('live_detail_ttl_seconds', 0)
        ttl = max(0, min(ttl, LIVE_DETAIL_MAX_AGE) - elapsed) if type(ttl) in (int, float) else 0
        card['live_detail_ttl_seconds'] = 0 if stale else ttl
        if stale or not ttl:
            card.update(football_tracker=None, baseball_tracker=None)
        teams.append(card)
    data['teams'] = teams
    return data


def _request_score_events(url, session=None, ttl=30, refresh_seconds=None):
    """Share provider requests, retain successes and exponentially back off errors.

    No endpoint is polled faster than once every 30 seconds. The source's own
    update cadence still determines when a score first becomes available.
    """
    with _score_request_lock:
        now = time_module.monotonic()
        entry = _score_requests.get(url)
        if entry:
            if entry.get('error') and now < entry['retry_at']:
                raise requests.RequestException(entry['error'])
            # Recompute expiry using current preferences so settings take effect
            # without restarting or creating duplicate per-display requests.
            interval = refresh_seconds if refresh_seconds is not None else _events_refresh_interval(entry.get('events', []))
            if not entry.get('error') and now < entry.get('fetched_at', 0) + interval:
                return entry['events']
        try:
            response = (session or requests).get(url, timeout=(3.05, 8))
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
                raise ValueError('ESPN response has no events list')
            # A malformed nonempty response must not erase a last-known slate.
            events = [e for e in payload['events'] if isinstance(e, dict) and
                      isinstance(e.get('competitions'), list) and e['competitions'] and e.get('id')]
            if payload['events'] and not events:
                raise ValueError('ESPN response contains no valid events')
            fetched_at = time_module.monotonic()
            for event in events:
                key = str(event['id'])
                _score_event_received_at.pop(key, None)
                _score_event_received_at[key] = (fetched_at, _live_event_signature(event))
            while len(_score_event_received_at) > 4096:
                del _score_event_received_at[next(iter(_score_event_received_at))]
            _score_requests[url] = {'events': events, 'fetched_at': fetched_at,
                                    'retry_at': fetched_at + (refresh_seconds if refresh_seconds is not None
                                                             else _events_refresh_interval(events)), 'failures': 0}
            if '/football/college-football/scoreboard' in url:
                _score_requests[url]['metadata'] = cfb_week.metadata(payload)
            return events
        except (requests.RequestException, ValueError) as error:
            failures = min((entry or {}).get('failures', 0) + 1, 10)
            delay = min(30 * (2 ** (failures - 1)), 900)
            response = getattr(error, 'response', None)
            if response is not None and response.status_code in (429, 503):
                retry_after = response.headers.get('Retry-After', '')
                try:
                    delay = max(delay, min(int(retry_after), 86400))
                except (ValueError, TypeError):
                    # HTTP-date form is also defined by Retry-After.
                    try:
                        from email.utils import parsedate_to_datetime
                        remaining = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                        delay = max(delay, min(max(0, remaining), 86400))
                    except (TypeError, ValueError, OverflowError):
                        pass
            _score_requests[url] = {**(entry or {}), 'retry_at': time_module.monotonic() + delay,
                                    'error': str(error), 'failures': failures}
            raise
        finally:
            # Bound memory even after weeks of changing dates/league selections.
            while len(_score_requests) > 512:
                del _score_requests[next(iter(_score_requests))]


def _refresh_espn_cache():
    global _last_refresh_attempt
    if not _refresh_lock.acquire(blocking=False):
        return False
    try:
        now = time_module.monotonic()
        if now - _last_refresh_attempt < 30:
            return False
        _last_refresh_attempt = now
        settings = get_settings()
        lc = dict(settings.get('league_conferences', {}))
        if settings.get('football_priority', True):
            # Full FBS slate includes unranked SEC/A&M and other Top 25 teams.
            lc['football/college-football'] = '80'
        leagues = _priority_leagues(settings.get('leagues', []), settings)
        with _cache_lock:
            for path in list(_requested_leagues):
                demand = _requested_leagues[path]
                seen_at = demand.get('seen_at', 0) if isinstance(demand, dict) else demand
                if now - seen_at > 900:
                    _requested_leagues.pop(path)
                elif isinstance(demand, dict):
                    demand['windows'] = {window: seen for window, seen in demand.get('windows', {}).items()
                                         if now - seen <= 900}
                    demand['refreshes'] = {value: seen for value, seen in demand.get('refreshes', {}).items()
                                           if now - seen <= 900}
                    demand['complete_week'] = now - demand.get('complete_week_seen_at', float('-inf')) <= 900
            leagues = list(dict.fromkeys(list(leagues) + list(_requested_leagues)))
            requested_windows = {path: list(demand.get('windows', {})) for path, demand in _requested_leagues.items()
                                 if isinstance(demand, dict)}
        dw = settings.get('date_windows', {})
        if 'football/college-football' in leagues:
            # Retain the complete FBS slate for independent conference/profile
            # filters. Apply selections locally rather than erasing other games.
            lc['football/college-football'] = '80'
        for path in leagues:
            window = dw.get(path, {})
            back = max([window.get('days_back', 1)] + [entry[0] for entry in requested_windows.get(path, [])])
            ahead = max([window.get('days_ahead', 7)] + [entry[1] for entry in requested_windows.get(path, [])])
            try:
                events = _fetch_league_raw(path, lc,
                    days_back=back, days_ahead=ahead)
                with _cache_lock:
                    failures = getattr(events, 'errors', [])
                    official_week = getattr(events, 'cfb_week', None)
                    if path == cfb_week.CFB and official_week is not None:
                        # A calendar week can extend beyond the rolling date window,
                        # especially bowls. Never prune its completed early games.
                        _espn_cache['raw_events'][path] = list(events)
                        _espn_cache['cfb_week'] = official_week
                        timestamp = datetime.now(timezone.utc).isoformat()
                        _espn_cache['updated_at'] = timestamp
                        _espn_cache.setdefault('league_updated_at', {})[path] = timestamp
                        _cache_errors.pop(path, None)
                    elif failures:
                        # Preserve events from unavailable days, overriding them
                        # only with a successfully retrieved matching event ID.
                        merged = {_event_key(event): event for event in _espn_cache['raw_events'].get(path, [])}
                        merged.update({_event_key(event): event for event in events})
                        _espn_cache['raw_events'][path] = _bounded_slate(merged.values(), back, ahead, settings['timezone'])
                        _cache_errors[path] = '; '.join(failures[:3])
                    else:
                        _espn_cache['raw_events'][path] = _bounded_slate(events, back, ahead, settings['timezone'])
                        timestamp = datetime.now(timezone.utc).isoformat()
                        _espn_cache['updated_at'] = timestamp
                        _espn_cache.setdefault('league_updated_at', {})[path] = timestamp
                        _cache_errors.pop(path, None)
            except Exception as error:
                # Do not replace last-known-good events or advance their timestamp.
                with _cache_lock:
                    _cache_errors[path] = str(error)
                print(f'[cache] {path}: {error}')
        if 'football/college-football' in leagues:
            _refresh_ap_poll()
        with _cache_lock:
            _espn_cache['raw_events'] = {key: value for key, value in _espn_cache['raw_events'].items() if key in leagues}
            _espn_cache['league_updated_at'] = {key: value for key, value in _espn_cache.get('league_updated_at', {}).items() if key in leagues}
            for key in list(_cache_errors):
                if key not in leagues:
                    _cache_errors.pop(key)
        return True
    finally:
        _refresh_lock.release()


def _get_league_events(path, league_conferences, window=None, complete_week=False, refresh_seconds=None):
    # Rendering never blocks on sports network calls. The background refresh owns
    # fetching and retries; all server/kiosk clients share its retained slate.
    with _cache_lock:
        if path in ESPN_API_PATHS:
            now = time_module.monotonic()
            old = _requested_leagues.get(path, {})
            windows = old.get('windows', {}) if isinstance(old, dict) else {}
            windows = {key: seen for key, seen in windows.items() if now - seen <= 900}
            if window is not None:
                windows[tuple(window)] = now
            refreshes = old.get('refreshes', {}) if isinstance(old, dict) else {}
            refreshes = {value: seen for value, seen in refreshes.items() if now - seen <= 900}
            if complete_week and refresh_seconds is not None:
                refreshes[refresh_seconds] = now
            complete_seen = now if complete_week else (old.get('complete_week_seen_at', float('-inf'))
                                                       if isinstance(old, dict) else float('-inf'))
            _requested_leagues[path] = {'seen_at': now, 'windows': windows,
                                       'refreshes': refreshes,
                                       'complete_week_seen_at': complete_seen,
                                       'complete_week': now - complete_seen <= 900}
        events = _espn_cache['raw_events'].get(path, [])
    if path == 'football/college-football' and not complete_week:
        selected = league_conferences.get(path, [])
        selected = selected if isinstance(selected, list) else selected.split(',')
        names = {entry['name'] for entry in HARDCODED_CONFERENCES[path] if entry['id'] in selected}
        memberships = _football_catalog().get('cfb_memberships', {})
        if names and memberships:
            events = [event for event in events if any(
                memberships.get(str(competitor.get('team', {}).get('id'))) in names
                for competition in event.get('competitions', []) if isinstance(competition, dict)
                for competitor in competition.get('competitors', []) if isinstance(competitor, dict)
                and isinstance(competitor.get('team'), dict))]
    return events


def _load_score_snapshot():
    """Restore provider data after an offline reboot; never treat it as fresh."""
    try:
        if os.path.getsize(SCORE_CACHE_FILE) > 16 * 1024 * 1024:
            raise ValueError('snapshot exceeds 16 MiB')
        with open(SCORE_CACHE_FILE) as saved:
            snapshot = json.load(saved)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('raw_events'), dict):
            raise ValueError('invalid score snapshot')
        events = {}
        for path, slate in snapshot['raw_events'].items():
            if path not in ESPN_API_PATHS or not isinstance(slate, list) or len(slate) > 2000:
                continue
            events[path] = [event for event in slate if isinstance(event, dict) and
                            isinstance(event.get('competitions'), list) and event.get('id')]
        updated_at = snapshot.get('updated_at')
        if updated_at is not None:
            dateutil_parser.isoparse(updated_at)
        timestamps = snapshot.get('league_updated_at', {})
        if not isinstance(timestamps, dict):
            timestamps = {}
        with _cache_lock:
            _espn_cache.update(raw_events=events, updated_at=updated_at,
                               league_updated_at={path: value for path, value in timestamps.items()
                                                  if path in events and isinstance(value, str)})
            saved_week = cfb_week.validate_saved_week(snapshot.get('cfb_week'))
            if saved_week:
                _espn_cache['cfb_week'] = saved_week
            poll = snapshot.get('ap_poll')
            if isinstance(poll, dict):
                try:
                    validated = _parse_ap_poll({'rankings': [{'type': 'ap',
                        'season': {'year': poll.get('season')}, 'date': poll.get('date', ''),
                        'ranks': [{'team': {'id': team_id}, 'current': rank}
                                  for team_id, rank in poll.get('ranks', {}).items()]}]})
                    # Preserve the actual fetch time, not the restart time.
                    dateutil_parser.isoparse(poll['updated_at'])
                    validated['updated_at'] = poll['updated_at']
                    _espn_cache['ap_poll'] = validated
                except (ValueError, TypeError, KeyError, AttributeError):
                    pass
            for path in events:
                _cache_errors[path] = 'Restored saved scores; awaiting provider refresh'
        _score_details.restore(snapshot.get('game_details'))
        return bool(events)
    except FileNotFoundError:
        return False
    except (OSError, ValueError, TypeError) as error:
        print(f'[cache] ignored saved scores: {error}')
        return False


def _save_score_snapshot(force=False):
    """Atomic, throttled state writes avoid unnecessary SD-card churn."""
    global _last_snapshot_write, _last_snapshot_fingerprint
    now = time_module.monotonic()
    if not force and _last_snapshot_write and now - _last_snapshot_write < 300:
        return False
    with _cache_lock:
        if not _espn_cache.get('updated_at'):
            return False
        game_details = _score_details.snapshot()
        payload = json.dumps({**_espn_cache, 'game_details': game_details}, separators=(',', ':'))
        fingerprint = (SCORE_CACHE_FILE, hashlib.sha256(json.dumps(
            [_espn_cache['raw_events'], _espn_cache.get('cfb_week'), _espn_cache.get('ap_poll'), game_details],
            sort_keys=True, separators=(',', ':')).encode()).digest())
    if not force and fingerprint == _last_snapshot_fingerprint:
        _last_snapshot_write = now
        return False
    if len(payload.encode('utf-8')) > 16 * 1024 * 1024:
        print('[cache] score snapshot exceeds 16 MiB; skipping disk write')
        return False
    temporary = None
    try:
        directory = os.path.dirname(os.path.abspath(SCORE_CACHE_FILE))
        fd, temporary = tempfile.mkstemp(prefix='.scores-', suffix='.json', dir=directory)
        with os.fdopen(fd, 'w') as saved:
            saved.write(payload)
            saved.flush()
            os.fsync(saved.fileno())
        os.replace(temporary, SCORE_CACHE_FILE)
        _last_snapshot_write = now
        _last_snapshot_fingerprint = fingerprint
        return True
    except OSError as error:
        print(f'[cache] cannot save scores: {error}')
        return False
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


import xml.etree.ElementTree as _ET

_SPORTS_KEYWORDS = {
    # sports
    'wrestling', 'cross country', 'soccer', 'basketball', 'football',
    'cheerleading', 'cheer', 'baseball', 'softball', 'volleyball',
    'track', 'golf', 'tennis', 'swimming', 'swim meet', 'gymnastics',
    'dance team', 'lacrosse', 'bowling', 'archery', 'powerlifting',
    'esports', 'e-sports',
    # event-type indicators used in school schedules
    'varsity', 'jv ', 'j.v.', 'junior varsity', 'freshman', 'frosh',
    ' vs ', 'vs.', ' vs.', '@ ', ' at ', 'game', 'meet', 'match',
    'tournament', 'invitational', 'scrimmage', 'playoff', 'playoffs',
    'semifinals', 'finals', 'championship', 'regionals', 'sectionals',
    'districts', 'conference', 'triangular', 'dual meet',
}

_SCHEDULE_NOISE = {
    'practice', 'picture day', 'pictures', 'banquet', 'first day', 'last day',
    'inservice', 'in-service', 'festival', 'concert', 'field trip', 'testing',
    'meeting', 'quiz bowl', 'speech', 'early release', 'registration',
    'orientation', 'parent night', 'open house', 'tryout', 'tryouts',
    'sign up', 'signup', 'fundraiser', 'spirit night', 'pep band',
}

# ─── HELPERS ───

def format_local_datetime(utc_str, tz_str):
    try:
        tz = pytz.timezone(tz_str)
        parsed = dateutil_parser.parse(utc_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local_dt = parsed.astimezone(tz)
        return {"date": local_dt.strftime('%a %b %-d'), "time": local_dt.strftime('%-I:%M %p')}
    except Exception:
        return {"date": "", "time": ""}


WEATHER_EMOJI = {
    113: "☀️", 116: "⛅", 119: "☁️", 122: "☁️",
    143: "🌫️", 248: "🌫️", 260: "🌫️",
    176: "🌦️", 179: "🌨️", 182: "🌨️", 185: "🌨️",
    200: "⛈️", 227: "🌨️", 230: "❄️",
    263: "🌦️", 266: "🌦️", 281: "🌧️", 284: "🌧️",
    293: "🌦️", 296: "🌦️", 299: "🌧️", 302: "🌧️",
    305: "🌧️", 308: "🌧️", 311: "🌨️", 314: "🌨️",
    317: "🌨️", 320: "🌨️", 323: "❄️", 326: "❄️",
    329: "❄️", 332: "❄️", 335: "❄️", 338: "❄️",
    350: "🌨️", 353: "🌦️", 356: "🌧️", 359: "🌧️",
    362: "🌨️", 365: "🌨️", 368: "❄️", 371: "❄️",
    374: "🌨️", 377: "🌨️", 386: "⛈️", 389: "⛈️",
    392: "⛈️", 395: "❄️",
}


WEATHER_CACHE = [None]
_weather_city = None
_weather_retry_at = 0.0
_weather_lock = threading.Lock()


def get_weather(city):
    global _weather_city, _weather_retry_at
    if not city:
        return '--'
    with _weather_lock:
        now = time_module.monotonic()
        if city == _weather_city and now < _weather_retry_at:
            return WEATHER_CACHE[0] or '--'
        if _weather_city != city:
            WEATHER_CACHE[0] = None
        _weather_city = city
        _weather_retry_at = now + 600
    return _fetch_weather(city)


def _fetch_weather(city):
    def _try():
        res = requests.get(f"https://wttr.in/{city}?format=j1", timeout=4)
        if res.status_code != 200:
            return None
        data = res.json()
        cc = data['current_condition'][0]
        temp = f"{cc['temp_F']}°F"
        try:
            emoji = WEATHER_EMOJI.get(int(cc.get('weatherCode', 0)), '')
        except (TypeError, ValueError):
            emoji = ''
        return f"{emoji} {temp}".strip() if emoji else temp
    try:
        val = _try()
        if val:
            WEATHER_CACHE[0] = val
            return val
    except Exception:
        pass
    if WEATHER_CACHE[0]:
        return WEATHER_CACHE[0]
    return "--"


def _special_active_today(sp, tz_str):
    stype = sp.get('schedule_type', 'always')
    if stype == 'always':
        return True
    days = sp.get('schedule_days', [])
    if not days:
        return True
    try:
        tz = pytz.timezone(tz_str)
        now_local = datetime.now(tz)
        if stype == 'dow':
            return now_local.weekday() in days
        if stype == 'dom':
            return now_local.day in days
    except Exception:
        pass
    return True


def _espn_record(comp):
    """Pull a team's W-L record from an ESPN scoreboard competitor.

    ESPN exposes `competitor['records']` as a list like
    [{"name": "overall", "abbreviation": "3-0", "summary": "3-0"}, ...].
    Prefer the overall record; fall back to any field whose summary is a
    W-L (or W-L-T) string."""
    try:
        for rec in comp.get('records', []) or []:
            if not isinstance(rec, dict):
                continue
            if (rec.get('name') or '').lower() == 'overall':
                summ = (rec.get('summary') or '').strip()
                if summ and re.fullmatch(r'\d{1,2}-\d{1,2}(?:-\d{1,2})?', summ):
                    return summ
        for rec in comp.get('records', []) or []:
            summ = (rec.get('summary') or '').strip()
            if summ and re.fullmatch(r'\d{1,2}-\d{1,2}(?:-\d{1,2})?', summ):
                return summ
    except Exception:
        pass
    return ''


def _split_record(team):
    """Split a trailing record off a team label, e.g. 'Auburn (3-1)' ->
    ('Auburn', '3-1'). Returns (team, record); record is '' when not given."""
    team = (team or '').strip()
    m = re.search(r'\s*\((\d{1,2}-\d{1,2}(?:-\d{1,2})?)\)\s*$', team)
    if m:
        return team[:m.start()].strip(), m.group(1)
    return team, ''


_local_feed_lock = threading.Lock()
_local_feed_slots = threading.BoundedSemaphore(2)
_local_feed_cache = {}  # (URL, display timezone) -> bounded parsed-feed state.
_LOCAL_FEED_CACHE_LIMIT = 64


def _refresh_local_feed(key, entry):
    """Fetch off the request path; one failed feed never hides live sports."""
    parsed = []
    error = None
    try:
        url, tz_str = key
        resolved_url, feed_type = _resolve_feed(url)
        parsers = {'rss': _parse_rss_feed, 'ical': _parse_ical_feed,
                   'maxpreps': _parse_maxpreps_feed, 'thrillshare': _parse_thrillshare_feed}
        if feed_type not in parsers:
            raise ValueError('No supported sports feed found')
        parsers[feed_type](resolved_url, '', '', parsed, tz_str)
    except Exception as failure:
        error = failure
    finally:
        with _local_feed_lock:
            now = time_module.monotonic()
            if error is None:
                entry.update(items=parsed[:50], failures=0, error='', retry_at=now + 300)
            else:
                failures = min(entry.get('failures', 0) + 1, 10)
                entry.update(failures=failures, error=type(error).__name__,
                             retry_at=now + min(30 * 2 ** (failures - 1), 900))
            entry['loading'] = False
        _local_feed_slots.release()
        if error is not None:
            # Feed URLs can contain private tokens; never log those URLs.
            app.logger.warning('Local sports feed unavailable; retaining saved items (%s)', type(error).__name__)


def _cached_local_feed_items(url, tz_str):
    """Return immediately, sharing at most two in-flight refreshes across clients."""
    key = (url, tz_str)
    launch = False
    with _local_feed_lock:
        now = time_module.monotonic()
        entry = _local_feed_cache.get(key)
        if entry is None:
            if len(_local_feed_cache) >= _LOCAL_FEED_CACHE_LIMIT:
                evictable = [old_key for old_key, value in _local_feed_cache.items() if not value['loading']]
                if not evictable:
                    return []
                oldest = min(evictable, key=lambda old_key: _local_feed_cache[old_key]['accessed_at'])
                del _local_feed_cache[oldest]
            entry = {'items': [], 'loading': False, 'retry_at': 0, 'failures': 0, 'error': ''}
            _local_feed_cache[key] = entry
        entry['accessed_at'] = now
        # Caller-specific favorite matching/labels cannot mutate cached data.
        cached = [dict(item, feed_stale=bool(entry['error'])) for item in entry['items']]
        if not entry['loading'] and now >= entry['retry_at'] and _local_feed_slots.acquire(blocking=False):
            entry['loading'] = True
            launch = True
    if launch:
        try:
            threading.Thread(target=_refresh_local_feed, args=(key, entry), daemon=True,
                             name='local-sports-feed').start()
        except RuntimeError:
            with _local_feed_lock:
                entry.update(loading=False, retry_at=time_module.monotonic() + 30)
            _local_feed_slots.release()
            app.logger.warning('Local sports feed worker unavailable; retrying later')
    return cached


def _build_local_schedule_items(settings, tz_str):
    items = []
    ls = settings.get('local_schedule', {})
    global_keywords = _home_keywords(settings)
    for entry in ls.get('items', []):
        if not entry.get('enabled', True):
            continue
        date_raw = entry.get('date', '')
        time_raw = entry.get('time', '')
        date_display, time_display, event_iso = date_raw, '', ''
        if date_raw:
            try:
                parsed = dateutil_parser.parse(f"{date_raw} {time_raw}".strip())
                tz = pytz.timezone(tz_str)
                if time_raw:
                    # A manually entered kickoff belongs to the configured
                    # display zone, never the server or browser's local zone.
                    # Reject ambiguous/nonexistent DST times instead of guessing.
                    parsed = (tz.localize(parsed, is_dst=None) if parsed.tzinfo is None
                              else parsed.astimezone(tz))
                    time_display = parsed.strftime('%-I:%M %p')
                    event_iso = parsed.isoformat()
                else:
                    # Date-only events have no known kickoff time.
                    event_iso = parsed.date().isoformat()
                date_display = parsed.strftime('%a %b %-d')
            except (ValueError, TypeError, OverflowError, pytz.InvalidTimeError, pytz.UnknownTimeZoneError) as error:
                app.logger.warning('Invalid local schedule date/time: %s', error)
        away_team, away_record = _split_record(entry.get('away_team', ''))
        home_team, home_record = _split_record(entry.get('home_team', ''))
        items.append({
            'type': 'schedule',
            'label': entry.get('label', 'LOCAL SPORTS'),
            'away_team': away_team,
            'home_team': home_team,
            'away_record': away_record,
            'home_record': home_record,
            'away_is_fav': _matches_keywords(away_team, global_keywords),
            'home_is_fav': _matches_keywords(home_team, global_keywords),
            'date': date_display,
            'time': time_display,
            'location': entry.get('location', ''),
            'event_iso': event_iso,
        })
    # Support both new multi-feed format and legacy single-feed fields
    rss_feeds = ls.get('rss_feeds', [])
    if not rss_feeds and ls.get('rss_url', '').strip():
        rss_feeds = [{'url': ls['rss_url'], 'label': ls.get('rss_label', 'LOCAL'), 'logo': ''}]

    for feed in rss_feeds:
        if not feed.get('enabled', True):
            continue
        rss_url = feed.get('url', '').strip()
        rss_label = (feed.get('label', '') or 'LOCAL').strip().upper()
        rss_logo = feed.get('logo', '')
        rss_tag = (feed.get('category', '') or '').strip().upper()
        if not rss_url:
            continue
        feed_keywords = _home_keywords(settings, feed) or global_keywords
        for item in _cached_local_feed_items(rss_url, tz_str):
            item['label'] = rss_label
            item['logo'] = rss_logo
            item['tag'] = rss_tag
            _apply_matchup_split(item, feed_keywords)
            items.append(item)
    return items


import re
from urllib.parse import urlparse as _urlparse, urljoin as _urljoin


# ─── AUTO PALETTE (derive the whole look from the favorite team) ───

def _hex_to_rgb(h):
    h = (h or '').strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _rgb_to_hex(rgb):
    return '#%02X%02X%02X' % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _mix(c1, c2, t):
    """Linear blend: t=0 -> c1, t=1 -> c2. Falls back to c1 on bad input."""
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    if not a or not b:
        return c1
    return _rgb_to_hex([a[i] + (b[i] - a[i]) * t for i in range(3)])


def _luminance(c):
    rgb = _hex_to_rgb(c)
    if not rgb:
        return 0.0
    def _ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (_ch(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


_team_color_cache = {}  # league_path -> {ABBR: (color, alternateColor)}


def _team_colors_for_league(path):
    with _cache_lock:
        if path in _team_color_cache:
            return _team_color_cache[path]
    sport, league = ESPN_API_PATHS.get(path, (path.split('/')[0], path.split('/')[-1]))
    out = {}
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams?limit=1000"
        res = requests.get(url, timeout=8)
        if res.ok:
            data = res.json()
            leagues = (data.get('sports') or [{}])[0].get('leagues') or [{}]
            for t in (leagues[0].get('teams') or []):
                team = t.get('team', {}) if isinstance(t, dict) else {}
                abbr = (team.get('abbreviation') or '').upper()
                if abbr:
                    out[abbr] = (team.get('color', ''), team.get('alternateColor', ''))
    except Exception as e:
        print(f"[palette] team colors {path}: {e}")
    with _cache_lock:
        _team_color_cache[path] = out
    return out


def _fav_team_key(settings):
    """Return the 'league_path:ABBR' that should drive the auto palette."""
    chosen = (settings.get('palette_team') or '').strip()
    if chosen and ':' in chosen:
        return chosen
    for t in (settings.get('teams') or []):
        if isinstance(t, str) and ':' in t:
            return t
    return ''


def _team_palette_colors(key):
    """Return (primary, alternate) hex colors for a 'path:ABBR' key, or None."""
    if not key or ':' not in key:
        return None
    path, abbr = key.rsplit(':', 1)
    entry = _team_colors_for_league(path).get(abbr.upper())
    if not entry:
        return None
    primary = entry[0] if _hex_to_rgb(entry[0]) else ''
    alternate = entry[1] if _hex_to_rgb(entry[1]) else ''
    if not primary and not alternate:
        return None
    return (primary or alternate, alternate or primary)


def _auto_palette(primary, alternate, theme):
    """Derive a full colors dict (surfaces + accents) from two team colors.

    Surfaces and accents are tinted from the team colors; semantic state
    colors (live/final/flash/winner/loser) are intentionally left alone so a
    live score still reads as green and a final as red.
    """
    p = primary if _hex_to_rgb(primary) else '#F5A800'
    a = alternate if _hex_to_rgb(alternate) else p
    # Keep the accents bright enough to read on a dark surface.
    accent = p if _luminance(p) > 0.14 else _mix(p, '#FFFFFF', 0.28)
    accent2 = a if _luminance(a) > 0.14 else _mix(a, '#FFFFFF', 0.28)
    header_color = _mix(p, '#000000', 0.4) if theme == 'light' else accent
    return {
        'dark_bg':         _mix(p, '#000000', 0.90),
        'dark_card':       _mix(p, '#000000', 0.82),
        'dark_border':     _mix(p, '#000000', 0.55),
        'dark_vs':         '#FFFFFF',
        'dark_ticker_bg':  _mix(p, '#000000', 0.94),
        'header_bg_dark':  _mix(p, '#000000', 0.86),
        'light_bg':        _mix(p, '#FFFFFF', 0.86),
        'light_card':      '#FFFFFF',
        'light_border':    _mix(p, '#FFFFFF', 0.70),
        'light_vs':        _mix(p, '#000000', 0.35),
        'header_bg_light': _mix(p, '#FFFFFF', 0.88),
        'header_border':   _mix(p, '#000000', 0.55),
        'card_border':     _mix(p, '#000000', 0.55),
        'logo_glow':       accent,
        'ticker_border':   accent,
        'league_label':    accent,
        'fav_abbr':        accent2,
        'fav_score':       accent2,
        'nascar_num':      accent2,
        'race_pos':        accent,
        'golf_pos':        accent,
        '_header_color':   header_color,
    }


def resolve_palette(settings):
    """Return (colors, header_color) for a settings dict.

    In auto mode the favorite team's ESPN colors override the surfaces and
    accents; manual mode returns exactly what the user configured.
    """
    base = dict(_DEFAULT_COLORS)
    base.update(settings.get('colors') or {})
    header = settings.get('header_color', '#F5A800')
    if (settings.get('color_mode') or 'auto') == 'auto':
        tc = _team_palette_colors(_fav_team_key(settings))
        if tc:
            palette = _auto_palette(tc[0], tc[1], settings.get('theme', 'dark'))
            header = palette.pop('_header_color', header)
            base.update(palette)
    return base, header


# ─── LOCAL SCHEDULE MATCHUP SPLITTING ───

def _split_matchup(text):
    """Split a local-event string into away/home teams.

    "TeamA @ TeamB" and "TeamA at TeamB" -> TeamA away, TeamB home.
    "TeamA vs TeamB" -> TeamA home, TeamB away (school schedules list the
    host school first). Returns None when the string is not a two-team
    matchup, e.g. "Team @ Home".
    """
    t = (text or '').strip()
    if not t:
        return None
    nonteams = {'home', 'away', 'neutral', 'tba', 'tbd', 'n/a', 'na', 'site'}
    patterns = (
        (r'\s+@\s+', False, 'at'),
        (r'\s+at\s+', False, 'at'),
        (r'\s+vs\.?\s+', True, 'vs'),
        (r'\s+v\.?\s+', True, 'vs'),
    )
    for pat, left_is_home, delim in patterns:
        parts = re.split(pat, t, maxsplit=1, flags=re.I)
        if len(parts) != 2:
            continue
        left = parts[0].strip(' -\u2013\u2014')
        right = parts[1].strip(' -\u2013\u2014')
        if not left or not right:
            continue
        if left.lower() in nonteams or right.lower() in nonteams:
            return None
        if left_is_home:
            return {'away': right, 'home': left, 'delim': delim}
        return {'away': left, 'home': right, 'delim': delim}
    return None


def _home_keywords(settings, feed=None):
    """Collect the user's home/favorite-team keywords (global + per-feed)."""
    ls = settings.get('local_schedule', {}) or {}
    kws = list(ls.get('home_team_keywords') or [])
    if feed:
        kws += list(feed.get('keywords') or [])
    return [str(k).strip().lower() for k in kws if str(k).strip()]


def _matches_keywords(name, keywords):
    nl = (name or '').lower()
    return any(kw in nl for kw in keywords)


def _apply_matchup_split(item, keywords):
    """Turn a free-text local event ("A vs B", "A @ B") into two sides.

    Marks which side is the user's team with *keys; for the ambiguous "vs"
    delimiter the user's team is placed on the home side so it renders like
    the ESPN game cards.
    """
    if item.get('type') != 'rss':
        return
    split = _split_matchup(item.get('title', ''))
    if not split:
        return
    away_team, away_record = _split_record(split['away'])
    home_team, home_record = _split_record(split['home'])
    away_is_fav = _matches_keywords(away_team, keywords)
    home_is_fav = _matches_keywords(home_team, keywords)
    if split.get('delim') == 'vs' and away_is_fav != home_is_fav and away_is_fav:
        away_team, home_team = home_team, away_team
        away_record, home_record = home_record, away_record
        away_is_fav, home_is_fav = home_is_fav, away_is_fav
    item.update({
        'away_team': away_team,
        'home_team': home_team,
        'away_record': away_record,
        'home_record': home_record,
        'away_is_fav': away_is_fav,
        'home_is_fav': home_is_fav,
        'is_matchup': True,
    })


def _resolve_feed(url):
    """Return (resolved_url, feed_type) where feed_type is 'rss', 'ical', 'thrillshare', 'maxpreps', or None."""
    # Already a known Thrillshare API URL
    if 'thrillshare.com' in url and '/cms/events' in url:
        return url, 'thrillshare'
    # MaxPreps school pages
    if 'maxpreps.com' in url:
        # Normalise to the /events/ page
        events_url = re.sub(r'(maxpreps\.com/[^/]+/[^/]+/[^/]+)/.*', r'\1/events/', url)
        if not events_url.endswith('/events/'):
            events_url = url.rstrip('/') + '/events/'
        return events_url, 'maxpreps'
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
    try:
        res = requests.get(url, timeout=10, headers=headers, allow_redirects=True)
        ct = res.headers.get('Content-Type', '')
        # Direct iCal feed
        if 'calendar' in ct or url.endswith('.ics'):
            if res.text.strip().startswith('BEGIN:VCALENDAR'):
                return url, 'ical'
        # Direct RSS/Atom/XML feed
        if any(t in ct for t in ('rss', 'atom', 'xml')):
            return url, 'rss'
        # Direct Thrillshare JSON response
        if 'json' in ct:
            try:
                data = res.json()
                if 'events' in data:
                    return url, 'thrillshare'
            except Exception:
                pass
        if 'html' not in ct and ct:
            return url, None

        text = res.text
        parsed = _urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        # <link type="application/rss+xml" href="...">
        rss_link = re.search(r'<link[^>]+type=["\']application/(rss|atom)\+xml["\'][^>]*href=["\']([^"\']+)["\']', text, re.I)
        if not rss_link:
            rss_link = re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*type=["\']application/(rss|atom)\+xml["\']', text, re.I)
        if rss_link:
            href = rss_link.group(2) if rss_link.lastindex >= 2 else rss_link.group(1)
            return _urljoin(base, href), 'rss'

        # Thrillshare API URL embedded in page JS
        ts_match = re.search(r'(https://thrillshare\.com/api/v\d+/o/\d+/cms/events[^"\'\\s<>]+)', text)
        if ts_match:
            return ts_match.group(1).rstrip('\\'), 'thrillshare'
        org_match = re.search(r'/api/v4/o/(\d+)/cms/events\?slug=([\w-]+)', text)
        if org_match:
            return f"https://thrillshare.com/api/v4/o/{org_match.group(1)}/cms/events?slug={org_match.group(2)}", 'thrillshare'

        # iCal link in page (e.g. href="...ics" or webcal://)
        ical_href = re.search(r'href=["\']([^"\']*\.ics[^"\']*)["\']', text, re.I)
        if not ical_href:
            ical_href = re.search(r'href=["\']webcal://([^"\']+)["\']', text, re.I)
            if ical_href:
                return 'https://' + ical_href.group(1), 'ical'
        if ical_href:
            return _urljoin(base, ical_href.group(1)), 'ical'

        # Sidearm Sports — try appending .ics to the calendar path
        if 'sidearm' in text.lower() or 'sidearmsports' in text.lower():
            ics_url = base + parsed.path.rstrip('/') + '.ics'
            try:
                r2 = requests.get(ics_url, timeout=6, headers=headers)
                if r2.status_code == 200 and r2.text.strip().startswith('BEGIN:VCALENDAR'):
                    return ics_url, 'ical'
            except Exception:
                pass

        # Generic fallback: try <page-path>.ics
        if not parsed.path.endswith('.ics'):
            ics_url = base + parsed.path.rstrip('/') + '.ics'
            try:
                r2 = requests.get(ics_url, timeout=6, headers=headers)
                if r2.status_code == 200 and r2.text.strip().startswith('BEGIN:VCALENDAR'):
                    return ics_url, 'ical'
            except Exception:
                pass

    except Exception as e:
        print(f"[resolve_feed] {url}: {e}")
    return url, None


def _parse_rss_feed(url, label, logo, out, tz_str='America/Chicago'):
    res = requests.get(url, timeout=5)
    res.raise_for_status()
    root = _ET.fromstring(res.content)
    channel = root.find('channel')
    if channel is None:
        if root.tag.lower() != 'rss':
            raise ValueError('Response is not an RSS feed')
        channel = root
    for item in (channel.findall('item') or [])[:20]:
        title = (item.findtext('title') or '').strip()
        if not title:
            continue
        title_lc = title.lower()
        if not any(kw in title_lc for kw in _SPORTS_KEYWORDS):
            continue
        if any(kw in title_lc for kw in _SCHEDULE_NOISE):
            continue
        pub_date = (item.findtext('pubDate') or '').strip()
        description = (item.findtext('description') or '').strip()
        date_str = time_str = event_iso = ''
        if pub_date:
            try:
                dt = dateutil_parser.parse(pub_date)
                # RSS dates normally include an offset. A missing offset has
                # no reliable instant; keep the news item without inventing one.
                if dt.tzinfo is None:
                    raise ValueError('RSS publication date has no timezone')
                dt = dt.astimezone(pytz.timezone(tz_str))
                date_str = dt.strftime('%a %b %-d')
                time_str = dt.strftime('%-I:%M %p')
                event_iso = dt.isoformat()
            except Exception:
                pass
        out.append({'type': 'rss', 'label': label, 'logo': logo,
                    'title': title, 'body': description[:120], 'date': date_str, 'time': time_str,
                    'event_iso': event_iso, 'date_kind': 'published'})


def _parse_ical_feed(url, label, logo, out, tz_str='America/Chicago'):
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.utc
    now_local = datetime.now(tz)
    # Preserve the existing three-day window, using calendar dates across DST.
    min_date = now_local.date() - timedelta(days=1 if now_local.hour < 11 else 0)
    max_date = min_date + timedelta(days=3)

    res = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
    res.raise_for_status()
    if not res.text.lstrip().startswith('BEGIN:VCALENDAR') or 'END:VCALENDAR' not in res.text:
        raise ValueError('Response is not a complete iCal calendar')
    lines = []
    for raw in res.text.splitlines():
        if raw.startswith((' ', '\t')) and lines:
            lines[-1] += raw.lstrip()
        else:
            lines.append(raw)
    event, count = {}, 0
    for line in lines:
        if line.strip() == 'BEGIN:VEVENT':
            event = {}
        elif line.strip() == 'END:VEVENT':
            title = event.get('summary', '').strip()
            title_lc = title.lower()
            if title and any(kw in title_lc for kw in _SPORTS_KEYWORDS) and not any(kw in title_lc for kw in _SCHEDULE_NOISE):
                date_str = time_str = ''
                event_dt = None
                dtstart_raw = event.get('dtstart', '')
                if dtstart_raw:
                    try:
                        dtstart = re.sub(r'^[^:]+:', '', dtstart_raw)  # strip TZID param
                        if 'T' in dtstart:
                            naive = datetime.strptime(dtstart.rstrip('Z'), '%Y%m%dT%H%M%S')
                            if dtstart.endswith('Z'):
                                event_dt = pytz.utc.localize(naive).astimezone(tz)
                            else:
                                event_zone = pytz.timezone(event.get('dtstart_tz') or tz_str)
                                event_dt = event_zone.localize(naive, is_dst=None).astimezone(tz)
                        else:
                            naive = datetime.strptime(dtstart, '%Y%m%d')
                            event_dt = tz.localize(naive)
                        date_str = event_dt.strftime('%a %b %-d')
                        if 'T' in dtstart:
                            time_str = event_dt.strftime('%-I:%M %p')
                    except Exception:
                        pass
                # Skip events outside the window
                if event_dt is not None and not (min_date <= event_dt.date() < max_date):
                    event = {}
                    continue
                out.append({'type': 'rss', 'label': label, 'logo': logo,
                            'title': title, 'body': event.get('location', ''),
                            'date': date_str, 'time': time_str,
                            'event_iso': (event_dt.isoformat() if 'T' in dtstart_raw else event_dt.date().isoformat()) if event_dt else ''})
                count += 1
                if count >= 20:
                    break
            event = {}
        elif ':' in line:
            key, _, val = line.partition(':')
            key_base = key.split(';')[0].lower().strip()
            if key_base in ('summary', 'dtstart', 'location', 'description'):
                store_key = 'dtstart' if key_base == 'dtstart' else key_base
                event[store_key] = (key.strip() + ':' + val).partition(':')[2].strip().replace('\\n', ' ').replace('\\,', ',')
                if key_base == 'dtstart':
                    event['dtstart_tz'] = next((part.split('=', 1)[1].strip('"')
                                                for part in key.split(';')[1:]
                                                if part.upper().startswith('TZID=')), '')


def _parse_maxpreps_feed(url, label, logo, out, tz_str='America/Chicago'):
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.utc
    now_local = datetime.now(tz)
    if now_local.hour < 11:
        min_dt = tz.localize(datetime(now_local.year, now_local.month, now_local.day)) - timedelta(days=1)
    else:
        min_dt = tz.localize(datetime(now_local.year, now_local.month, now_local.day))
    max_dt = min_dt + timedelta(days=31)

    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    res = requests.get(url, timeout=10, headers=headers)
    res.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script', res.text, re.S)
    if not m:
        raise ValueError('MaxPreps response contains no schedule data')
    data = json.loads(m.group(1))
    contests = data.get('props', {}).get('pageProps', {}).get('initSchoolContests', [])
    if not isinstance(contests, list):
        raise ValueError('MaxPreps contests must be a list')

    # JSON-LD fallback (game-day cards also present on the events page)
    if not contests:
        try:
            jm = re.search(r'<script type="application/ld\+json"[^>]*>({.*?})</script', res.text, re.S)
            if jm:
                jld = json.loads(jm.group(1))
                graph = jld.get('@graph', [jld])
                for n in graph:
                    evts = n.get('event') or []
                    if isinstance(evts, dict):
                        evts = [evts]
                    for ev in evts:
                        title = (ev.get('name') or '').strip()
                        if not title:
                            continue
                        start = (ev.get('startDate') or ev.get('start_date') or '').strip()
                        date_str = time_str = ''
                        event_dt = None
                        if start:
                            try:
                                event_dt = dateutil_parser.parse(start)
                                if event_dt.tzinfo is None:
                                    event_dt = tz.localize(event_dt)
                                else:
                                    event_dt = event_dt.astimezone(tz)
                                if event_dt < min_dt:
                                    continue
                                date_str = event_dt.strftime('%a %b %-d')
                                time_str = event_dt.strftime('%-I:%M %p')
                            except Exception:
                                pass
                        out.append({'type': 'rss', 'label': label, 'logo': logo,
                                    'title': title,
                                    'body': (ev.get('@type') or 'Sporting Event').replace('_', ' '),
                                    'date': date_str, 'time': time_str,
                                    'event_iso': event_dt.isoformat() if event_dt else ''})
            elif 'initSchoolContests' not in data.get('props', {}).get('pageProps', {}):
                raise ValueError('MaxPreps response contains no schedule data')
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError('Invalid MaxPreps schedule response') from error
        return

    count = 0
    for c in contests:
        title = (c.get('title') or '').strip()
        if not title:
            continue
        title_lc = title.lower()
        if not any(kw in title_lc for kw in _SPORTS_KEYWORDS):
            continue
        if any(kw in title_lc for kw in _SCHEDULE_NOISE):
            continue
        date_str = time_str = ''
        event_dt = None
        date_raw = c.get('date') or c.get('startDate') or ''
        if date_raw:
            try:
                naive = datetime.strptime(date_raw[:19], '%Y-%m-%dT%H:%M:%S')
                event_dt = tz.localize(naive)
                if not (min_dt <= event_dt < max_dt):
                    continue
                date_str = event_dt.strftime('%a %b %-d')
                time_str = event_dt.strftime('%-I:%M %p')
            except Exception:
                pass
        sport = (c.get('sport') or '').strip()
        out.append({'type': 'rss', 'label': label, 'logo': logo,
                    'title': title, 'body': sport, 'date': date_str, 'time': time_str,
                    'event_iso': event_dt.isoformat() if event_dt else ''})
        count += 1
        if count >= 20:
            break


def _parse_thrillshare_feed(url, label, logo, out, tz_str='America/Chicago'):
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.utc
    now_local = datetime.now(tz)
    if now_local.hour < 11:
        min_dt = tz.localize(datetime(now_local.year, now_local.month, now_local.day)) - timedelta(days=1)
    else:
        min_dt = tz.localize(datetime(now_local.year, now_local.month, now_local.day))

    res = requests.get(url, timeout=8)
    res.raise_for_status()
    data = res.json()
    if not isinstance(data, dict) or not isinstance(data.get('events'), list):
        raise ValueError('Thrillshare response has no events list')
    for event in (data.get('events') or [])[:30]:
        title = (event.get('title') or '').strip()
        # Strip HTML artifacts like ">Multiple Schools"
        if '">' in title:
            title = title[title.rfind('">') + 2:]
        title = title.strip()
        if not title:
            continue
        title_lc = title.lower()
        if not any(kw in title_lc for kw in _SPORTS_KEYWORDS):
            continue
        if any(kw in title_lc for kw in _SCHEDULE_NOISE):
            continue
        date_str = time_str = event_iso = ''
        event_dt = None
        start_at = event.get('start_at', '')
        if start_at:
            try:
                event_dt = dateutil_parser.parse(start_at)
                if event_dt.tzinfo is None:
                    event_dt = tz.localize(event_dt)
                else:
                    event_dt = event_dt.astimezone(tz)
                if event_dt < min_dt:
                    continue
                date_str = event_dt.strftime('%a %b %-d')
                time_str = event_dt.strftime('%-I:%M %p')
                event_iso = event_dt.isoformat()
            except Exception:
                pass
        venue = (event.get('venue') or '').strip()
        out.append({'type': 'rss', 'label': label, 'logo': logo,
                    'title': title, 'body': venue, 'date': date_str, 'time': time_str,
                    'event_iso': event_iso})


def _build_data_response(active_leagues, active_teams, active_lc, tz_str, settings):
    fav_cards = []
    fav_card_keys = set()
    ticker_parts = []
    race_cards = []
    golf_cards = []

    fav_set = set()
    for t in active_teams:
        if ':' in t:
            parts = t.rsplit(':', 1)
            fav_set.add(f"{parts[0].lower()}:{parts[1].upper()}")

    now = datetime.now(timezone.utc)
    try:
        local_now = now.astimezone(pytz.timezone(tz_str))
        today_local = local_now.date()
    except Exception:
        today_local = now.date()

    dw = settings.get('date_windows', {})
    complete_cfb = settings.get('cfb_coverage', 'all_power5') == 'all_power5'
    official_week = cfb_week.validate_saved_week(_espn_cache.get('cfb_week'))
    cfb_warning = ''
    if complete_cfb and official_week:
        if cfb_week.CFB in _cache_errors:
            cfb_warning = 'Showing saved ' + official_week['label'] + '; ESPN week refresh is unavailable'
        elif official_week.get('end'):
            try:
                if now > dateutil_parser.isoparse(official_week['end']):
                    cfb_warning = 'Showing saved ' + official_week['label'] + '; awaiting the next official ESPN week'
            except (ValueError, TypeError):
                pass

    def _get_window(path):
        entry = dw.get(path, {})
        if path in MOTORSPORTS_LEAGUES:
            return entry.get('days_back', 1), entry.get('days_ahead', 2)
        if path in GOLF_LEAGUES:
            return entry.get('days_back', 1), entry.get('days_ahead', 7)
        return entry.get('days_back', 1), entry.get('days_ahead', 7)

    for path in _priority_leagues(active_leagues, settings):
        try:
            weekly = path == cfb_week.CFB and complete_cfb
            if weekly:
                events = _get_league_events(path, {}, _get_window(path), complete_week=True,
                                           refresh_seconds=settings.get('cfb_refresh_seconds', 180))
                if official_week is None:
                    cfb_warning = 'Waiting for a verified ESPN football week; favorites and rankings do not define the complete schedule'
                events = [event for event in events if cfb_week.matches_week(event, official_week)
                          and cfb_week.eligible(event, _football_catalog())]
                events.sort(key=cfb_week.sort_key)
            else:
                events = _get_league_events(path, active_lc, _get_window(path))
            sport, league = ESPN_API_PATHS.get(path, (path.split('/')[0], path.split('/')[-1]))

            # ── Motorsports (NASCAR / IndyCar / F1) — leaderboard + ticker on race day ──
            if path in MOTORSPORTS_LEAGUES:
                fav_key = MOTORSPORTS_FAV_KEY.get(path, 'nascar_favorites')
                motor_favs = [n.strip().lower() for n in settings.get(fav_key, []) if n.strip()]
                league_label = LEAGUE_LABELS.get(path, 'RACING')
                for event in events:
                    try:
                        game_state, status_detail = _event_status(event)
                        state = ('in' if game_state in ('live', 'halftime', 'overtime') else
                                 'post' if game_state == 'final' else 'pre')
                        try:
                            event_local_date = dateutil_parser.parse(event['date']).astimezone(pytz.timezone(tz_str)).date()
                            r_back, r_ahead = _get_window(path)
                            racing_min = today_local - timedelta(days=r_back)
                            racing_max = today_local + timedelta(days=r_ahead)
                            in_window = (racing_min <= event_local_date <= racing_max)
                        except Exception:
                            in_window = True

                        if not in_window:
                            continue  # only show within configured racing window

                        color_state = 'live' if state == 'in' else ('final' if state == 'post' else 'pre')
                        competitors = event['competitions'][0].get('competitors', [])
                        sorted_drivers = sorted(
                            [c for c in competitors if c.get('order') is not None],
                            key=lambda c: int(c.get('order', 999))
                        ) or sorted(
                            competitors,
                            key=lambda c: int(c.get('score') or 999)
                        )

                        def _is_motor_fav(athlete, car, _favs=motor_favs):
                            full = athlete.get('displayName', '').lower()
                            return any(fav in full or fav == car.lower() for fav in _favs)

                        drivers = []
                        for d in sorted_drivers[:10]:
                            athlete = d.get('athlete', {})
                            name = athlete.get('shortName') or athlete.get('displayName') or '—'
                            car = athlete.get('jersey', '')
                            pos = d.get('order') or d.get('score', '?')
                            is_fav = _is_motor_fav(athlete, car)
                            drivers.append({"pos": pos, "name": name, "car": car, "is_fav": is_fav})

                        # Append favorites ranked outside top 10
                        if motor_favs:
                            for d in sorted_drivers[10:]:
                                athlete = d.get('athlete', {})
                                car = athlete.get('jersey', '')
                                if _is_motor_fav(athlete, car):
                                    name = athlete.get('shortName') or athlete.get('displayName') or '—'
                                    pos = d.get('order') or d.get('score', '?')
                                    drivers.append({"pos": pos, "name": name, "car": car, "is_fav": True})

                        race_name = event.get('shortName') or event.get('name', 'Race')
                        race_cards.append({
                            "league_path": path,
                            "league_label": league_label,
                            "race_name": race_name,
                            "color_state": color_state,
                            "status": status_detail,
                            "is_pre": state == 'pre',
                            "drivers": drivers,
                            "flag_label": event.get('_nascar_flag_label', ''),
                            "lap": event.get('_nascar_lap', 0),
                            "laps_in_race": event.get('_nascar_laps_in_race', 0),
                        })

                        if drivers:
                            # Top 10 by position order; mark fav with ★
                            ticker_drivers = sorted(drivers, key=lambda d: int(d['pos']) if str(d['pos']).isdigit() else 999)[:10]
                            sep = '&nbsp;&nbsp;&nbsp;&nbsp;'
                            top10_text = sep.join(
                                (f"{d['pos']}&nbsp;&nbsp;{'★ ' if d['is_fav'] else ''}{d['name']}&nbsp;&nbsp;#{d['car']}" if d.get('car') else f"{d['pos']}&nbsp;&nbsp;{'★ ' if d['is_fav'] else ''}{d['name']}")
                                for d in ticker_drivers
                            )
                            ticker_parts.append({
                                "label": league_label,
                                "games": [{"text": top10_text, "color_state": color_state,
                                           "away": "", "home": "", "away_score": "", "home_score": "", "winner": None}],
                            })
                    except Exception as e:
                        print(f"{path} event error: {e}")
                continue  # skip normal team-sports processing for this league

            # ── Golf (PGA) — leaderboard card + ticker top-10 on tournament days ──
            if path in GOLF_LEAGUES:
                golf_favs = [n.strip().lower() for n in settings.get('golf_favorites', []) if n.strip()]
                for event in events:
                    try:
                        game_state, status_detail = _event_status(event)
                        state = ('in' if game_state in ('live', 'halftime', 'overtime') else
                                 'post' if game_state == 'final' else 'pre')
                        try:
                            event_local_date = dateutil_parser.parse(event['date']).astimezone(pytz.timezone(tz_str)).date()
                            g_back, g_ahead = _get_window(path)
                            golf_min = today_local - timedelta(days=g_back)
                            golf_max = today_local + timedelta(days=g_ahead)
                            end_date = event.get('endDate') or event['date']
                            end_local_date = dateutil_parser.parse(end_date).astimezone(pytz.timezone(tz_str)).date()
                            # PGA events span several days; a Thursday start
                            # remains visible while the tournament is live.
                            in_window = (event_local_date <= golf_max and end_local_date >= golf_min) or state == 'in'
                        except Exception:
                            in_window = True

                        if not in_window:
                            continue  # only show within configured golf window

                        color_state = 'live' if state == 'in' else ('final' if state == 'post' else 'pre')
                        competitors = event['competitions'][0].get('competitors', [])

                        def _golf_pos_key(c):
                            pos = c.get('status', {}).get('position', {}).get('id', '') or ''
                            try:
                                return int(pos)
                            except Exception:
                                return 999

                        active = [c for c in competitors
                                  if c.get('status', {}).get('type', {}).get('state') not in ('cut', 'wd', 'dq')]
                        sorted_golfers = sorted(active or competitors, key=_golf_pos_key)

                        golfers = []
                        for g in sorted_golfers[:10]:
                            athlete = g.get('athlete', {})
                            full_name = athlete.get('displayName', '')
                            name = athlete.get('shortName') or full_name or '—'
                            pos = g.get('status', {}).get('position', {}).get('displayName', '?')
                            strokes = g.get('score', '—')
                            is_fav = any(fav in full_name.lower() for fav in golf_favs)
                            golfers.append({"pos": pos, "name": name, "strokes": strokes, "is_fav": is_fav})

                        # Append favorites ranked outside top 10
                        fav_extras = []
                        if golf_favs:
                            for g in sorted_golfers[10:]:
                                athlete = g.get('athlete', {})
                                full_name = athlete.get('displayName', '')
                                if any(fav in full_name.lower() for fav in golf_favs):
                                    name = athlete.get('shortName') or full_name or '—'
                                    pos = g.get('status', {}).get('position', {}).get('displayName', '?')
                                    strokes = g.get('score', '—')
                                    fav_extras.append({"pos": pos, "name": name, "strokes": strokes, "is_fav": True})

                        tournament_name = event.get('shortName') or event.get('name', 'Tournament')
                        golf_cards.append({
                            "league_path": path,
                            "league_label": LEAGUE_LABELS.get(path, 'PGA'),
                            "tournament_name": tournament_name,
                            "color_state": color_state,
                            "status": status_detail,
                            "is_pre": state == 'pre',
                            "golfers": golfers + fav_extras,
                        })

                        if golfers:
                            sep = '&nbsp;&nbsp;&nbsp;&nbsp;'
                            top10_text = sep.join(
                                f"{g['pos']}&nbsp;&nbsp;{g['name']}&nbsp;&nbsp;({g['strokes']})"
                                for g in golfers
                            )
                            ticker_parts.append({
                                "label": LEAGUE_LABELS.get(path, 'PGA'),
                                "games": [{"text": top10_text, "color_state": color_state,
                                           "away": "", "home": "", "away_score": "", "home_score": "", "winner": None}],
                            })
                    except Exception as e:
                        print(f"Golf event error: {e}")
                continue  # skip normal team-sports processing for this league

            league_games = []
            league_event_keys = set()

            for event in events:
                try:
                    comp_list = event.get('competitions') or []
                    if not comp_list or not isinstance(comp_list[0], dict):
                        continue
                    comp = comp_list[0]
                    competitors = [competitor for competitor in comp.get('competitors', [])
                                   if isinstance(competitor, dict) and isinstance(competitor.get('team'), dict)]
                    if len(competitors) < 2 or _event_key(event) in league_event_keys:
                        continue
                    league_event_keys.add(_event_key(event))
                    home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
                    away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[-1])
                    if home is away:
                        continue
                    h_abbr = home['team'].get('abbreviation') or home['team'].get('shortDisplayName') or home['team'].get('displayName', '?')
                    a_abbr = away['team'].get('abbreviation') or away['team'].get('shortDisplayName') or away['team'].get('displayName', '?')
                    def display_score(competitor):
                        score = competitor.get('score')
                        if isinstance(score, dict):
                            score = score.get('displayValue', score.get('value'))
                        return str(score) if type(score) in (str, int, float) and str(score).strip() else '—'
                    h_score, a_score = display_score(home), display_score(away)
                    game_state, status_detail = _event_status({**event, 'status': event.get('status') or comp.get('status')})
                    state = ('in' if game_state in ('live', 'halftime', 'overtime') else
                             'post' if game_state == 'final' else 'pre')
                    dt_info = format_local_datetime(event.get('date', ''), tz_str)
                    l_time_str = f"{dt_info['date']}  {dt_info['time']}".strip()

                    try:
                        event_date = dateutil_parser.parse(event['date'])
                        if event_date.tzinfo is None:
                            event_date = event_date.replace(tzinfo=timezone.utc)
                        event_local_date = event_date.astimezone(pytz.timezone(tz_str)).date()
                        is_today = (event_local_date == today_local)
                    except Exception:
                        event_local_date = None
                        is_today = state == 'in'

                    if state == 'pre':
                        schedule_text = l_time_str if game_state == 'scheduled' else status_detail
                        tick_text = f"{a_abbr} @ {h_abbr} | {schedule_text or status_detail}"
                        color_state = 'pre'
                        winner = None
                    elif state == 'in':
                        tick_text = f"{a_abbr} {a_score}  {h_abbr} {h_score}  ({status_detail})"
                        color_state = 'live'
                        try:
                            as_int, hs_int = int(a_score), int(h_score)
                            winner = 'away' if as_int > hs_int else ('home' if hs_int > as_int else 'tie')
                        except Exception:
                            winner = None
                    else:
                        tick_text = f"{a_abbr} {a_score}  {h_abbr} {h_score}  ({status_detail})"
                        color_state = 'final'
                        try:
                            as_int, hs_int = int(a_score), int(h_score)
                            winner = 'away' if as_int > hs_int else ('home' if hs_int > as_int else 'tie')
                        except Exception:
                            winner = None

                    def college_rank(team):
                        curated_rank = team.get('curatedRank') or {}
                        rank = curated_rank.get('current') if isinstance(curated_rank, dict) else None
                        return rank if type(rank) is int and 1 <= rank <= 25 else None
                    away_priority_rank, home_priority_rank = college_rank(away), college_rank(home)
                    away_rank, home_rank = ((_ap_rank(away, event), _ap_rank(home, event))
                                            if path == 'football/college-football' else
                                            (away_priority_rank, home_priority_rank))
                    if is_today:
                        league_games.append({
                            "event_id": event.get('id', ''), "league_path": path,
                            "text": tick_text, "color_state": color_state,
                            "away": a_abbr, "home": h_abbr,
                            "away_score": a_score, "home_score": h_score, "winner": winner,
                            "away_logo": away['team'].get('logo', ''), "home_logo": home['team'].get('logo', ''),
                            "away_rank": away_rank, "home_rank": home_rank,
                            "status": status_detail, "game_state": game_state,
                            "local_time": l_time_str,
                        })

                    away_is_fav = any(f"{path.lower()}:{abbr.upper()}" in fav_set
                                      for abbr in _team_aliases(path, away['team'].get('id'), a_abbr))
                    home_is_fav = any(f"{path.lower()}:{abbr.upper()}" in fav_set
                                      for abbr in _team_aliases(path, home['team'].get('id'), h_abbr))
                    priority = settings.get('football_priority', True)
                    is_aggies = path == 'football/college-football' and ('TA&M' in (a_abbr, h_abbr) or
                        any(str(c.get('team', {}).get('id')) == '245' for c in competitors))
                    is_sec = False
                    if path == 'football/college-football':
                        # Numeric conference IDs differ between ESPN resources;
                        # use known team membership or an explicit SEC label.
                        is_sec = any(str(c['team'].get('id')) in SEC_TEAM_IDS or
                                     (isinstance(c['team'].get('conference'), dict) and
                                      c['team']['conference'].get('abbreviation') == 'SEC')
                                     for c in competitors)
                    priority_game = priority and (path == 'football/nfl' or
                        (path == 'football/college-football' and (is_aggies or is_sec or away_priority_rank or home_priority_rank or away_rank or home_rank)))
                    is_fav = away_is_fav or home_is_fav
                    priority_order = (0 if is_aggies else 1 if is_sec else 2 if (away_priority_rank or home_priority_rank or away_rank or home_rank) else 4) if path == 'football/college-football' else (3 if path == 'football/nfl' else 4)
                    game_key = f"{path}:{_event_key(event)}"
                    t_back, t_ahead = _get_window(path)
                    team_min = today_local - timedelta(days=t_back)
                    team_max = today_local + timedelta(days=t_ahead)
                    in_window = team_min <= event_local_date <= team_max if event_local_date is not None else state == 'in'
                    if ((weekly or is_fav or priority_game) and (weekly or in_window)
                            and game_key not in fav_card_keys):
                        fav_card_keys.add(game_key)
                        details = _score_details.get(path, event, home, away)
                        live_ttl = (_live_detail_ttl(path, event)
                                    if details.get('football_tracker') or details.get('baseball_tracker') else 0)
                        if not live_ttl:
                            details.update(football_tracker=None, baseball_tracker=None)
                        details['live_detail_ttl_seconds'] = live_ttl
                        fav_cards.append({
                            "league_path": path,
                            "event_id": event.get("id", ""),
                            "kickoff_iso": event.get('date', ''),
                            "away_rank": away_rank, "home_rank": home_rank,
                            "priority_order": priority_order,
                            "league_label": LEAGUE_LABELS.get(path, league.upper()),
                            "home_name": h_abbr, "away_name": a_abbr,
                            "home_score": h_score, "away_score": a_score,
                            "home_logo": home['team'].get('logo', ''),
                            "away_logo": away['team'].get('logo', ''),
                            "status": status_detail, "local_time": l_time_str,
                            "game_state": game_state,
                            "is_pre": state == 'pre', "color_state": color_state,
                            "winner": winner,
                            **details,
                            "away_is_fav": away_is_fav,
                            "home_is_fav": home_is_fav,
                        })
                except Exception as e:
                    print(f"Event error in {path}: {e}")
                    continue

            if league_games:
                ticker_parts.append({"label": LEAGUE_LABELS.get(path, league.upper()), "games": league_games})
        except Exception as e:
            print(f"Error processing {path}: {e}")

    if settings.get('football_priority', True):
        fav_cards.sort(key=lambda card: card.get('priority_order', 4))
    if complete_cfb:
        college_cards = sorted((card for card in fav_cards if card['league_path'] == cfb_week.CFB),
                               key=cfb_week.sort_key)
        # Keep one ordered CFB block; other sports retain their relative order.
        if college_cards:
            first = next(index for index, card in enumerate(fav_cards) if card['league_path'] == cfb_week.CFB)
            others = [card for card in fav_cards if card['league_path'] != cfb_week.CFB]
            fav_cards = others[:first] + college_cards + others[first:]

    specials = [
        s for s in settings.get('specials', [])
        if s.get('enabled') and (s.get('title') or s.get('image')) and _special_active_today(s, tz_str)
    ]

    colors, header_color = resolve_palette(settings)

    response = {
        "display_name": settings.get('display_name', 'SCOREBOARD'),
        "header_color": header_color,
        "weather": get_weather(settings.get('city', '')),
        "teams": fav_cards,
        "races": race_cards,
        "golf": golf_cards,
        "ticker_parts": ticker_parts,
        "specials": specials,
        "local_schedule_items": _build_local_schedule_items(settings, tz_str),
        "cast_orientation": settings.get('cast_orientation', 'auto'),
        "theme": settings.get('theme', 'dark'),
        "colors": colors,
        "color_mode": settings.get('color_mode', 'auto'),
        "palette_team": settings.get('palette_team', ''),
        "font_primary": settings.get('font_primary', 'Barlow Condensed'),
        "display_mode": settings.get('display_mode', 'hybrid'),
        "logo_slide_duration": settings.get('logo_slide_duration', 8),
        "transition_duration_ms": settings.get('transition_duration_ms', 500),
        "show_logo_slide": settings.get('show_logo_slide', True),
        "logo_available": bool(_logo_version()),
        "logo_version": _logo_version(),
        "clock_format": settings.get('clock_format', '12h'),
        "cfb_coverage": settings.get('cfb_coverage', 'all_power5'),
        "cfb_refresh_seconds": settings.get('cfb_refresh_seconds', 180),
        "cfb_week": {**(official_week or {}), 'warning': cfb_warning,
                     'eligible_game_count': sum(card['league_path'] == cfb_week.CFB for card in fav_cards)},
        "header_visibility": settings.get('header_visibility', 'auto'),
        "show_time_bar": settings.get('show_time_bar', True),
        "show_title_bar": settings.get('show_title_bar', True),
        "timezone": tz_str,
        "slide_playlist": settings.get('slide_playlist', []),
        "slide_duration": settings.get('slide_duration', 8),
        "slide_transition": settings.get('slide_transition', 'slide-right'),
        "ticker_speed": settings.get('ticker_speed', 120),
        "cache_updated_at": _espn_cache.get("updated_at"),
        "cache_league_updated_at": dict(_espn_cache.get('league_updated_at', {})),
        "cache_stale": bool(_cache_errors) or bool(cfb_warning),
        "cache_errors": {**_cache_errors, **({cfb_week.CFB: cfb_warning} if cfb_warning else {})},
        "ap_rankings_updated_at": _espn_cache.get('ap_poll', {}).get('updated_at'),
        "ap_rankings_date": _espn_cache.get('ap_poll', {}).get('date'),
        "ap_rankings_stale": bool(_ap_poll_request['failures']),
        "browser_refresh_seconds": min(30, _refresh_preferences(settings)['live_seconds']),
        "settings_updated_at": settings.get('last_saved', ''),
        "app_version": _read_version(),
    }
    return _apply_scorecard_filter(_apply_football_display(response, settings, tz_str, now), settings)


# ─── ROUTES: WEB UI ───

@app.route('/')
def index():
    settings = get_settings()
    if settings.get('device_mode') == 'server' and not settings.get('server_enable_display', True):
        return redirect(url_for('settings_page'))
    resp = make_response(render_template('index.html', settings=settings))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.after_request
def _no_cache_headers(resp):
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'same-origin'
    resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return resp


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if _authenticate_request(username, password):
            session.clear()
            session.permanent = True
            session['user'] = username
            session['auth_version'] = _credentials_version()
            return redirect(url_for('settings_page'))
        return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


@app.route('/settings')
@login_required
def settings_page():
    return render_template('settings.html', username=session['user'])


# ─── ROUTES: API ───

@app.route('/api/auth', methods=['POST'])
def auth_api():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'error': 'Credentials must be a JSON object'}), 400
    if _authenticate_request(data.get('username', ''), data.get('password', '')):
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 401


@app.route('/api/settings', methods=['GET', 'POST'])
@require_admin
def settings_api():
    if request.method == 'POST':
        data = request.get_json(silent=True)
        try:
            _validate_settings(data)
            if 'password_hash' in data.get('admin_credentials', {}):
                raise ValueError('Supply a new password, not a password hash')
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        kiosk_updates = {}
        for field in ('server_url', 'kiosk_name', 'auth_token'):
            if field in data:
                kiosk_updates[field] = data.pop(field)
        try:
            save_settings(data)
            if kiosk_updates:
                save_kiosk_config(kiosk_updates)
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        except OSError:
            return jsonify({'error': 'Could not save settings; previous settings retained'}), 500
        if 'admin_credentials' in data and 'user' in session:
            session['user'] = get_settings()['admin_credentials']['username']
            session['auth_version'] = _credentials_version()
        return jsonify({"status": "ok"})
    s = get_settings()
    cfg = get_kiosk_config()
    s['server_url'] = cfg.get('server_url', '')
    s['kiosk_name'] = cfg.get('kiosk_name', 'Kiosk')
    s['paired'] = cfg.get('paired', False)
    s['kiosk_id'] = cfg.get('kiosk_id', '')
    credentials = s.get('admin_credentials', {})
    s['admin_credentials'] = {'username': credentials.get('username', 'admin'),
                             'password_set': bool(credentials.get('password_hash') or credentials.get('password')),
                             'default_password': (_password_hash_matches(credentials['password_hash'], 'root')
                                                  if credentials.get('password_hash') else credentials.get('password') == 'root')}
    return jsonify(s)


@app.route('/api/settings/safe-defaults', methods=['POST'])
@require_admin
def restore_safe_timings():
    """Recover display/update timing without erasing user content or account state."""
    try:
        save_settings({'clock_format': '12h', 'display_mode': 'hybrid',
                       'score_refresh': {'live_seconds': 30, 'upcoming_seconds': 300,
                                         'idle_seconds': 900, 'final_seconds': 3600},
                       'slide_duration': 8, 'logo_slide_duration': 8,
                       'transition_duration_ms': 500, 'ticker_speed': 120})
    except OSError:
        return jsonify({'error': 'Could not restore timings; previous settings retained'}), 500
    return jsonify({'status': 'ok'})


def _image_type(data):
    """Accept passive raster formats with bounded dimensions, never HTML or SVG."""
    width = height = 0
    extension = None
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 45:
        offset = 8
        seen_end = False
        while offset + 12 <= len(data):
            size = struct.unpack('>I', data[offset:offset + 4])[0]
            chunk = data[offset + 4:offset + 8]
            end = offset + 8 + size
            if end + 4 > len(data):
                break
            if zlib.crc32(data[offset + 4:end]) & 0xffffffff != struct.unpack('>I', data[end:end + 4])[0]:
                break
            if offset == 8:
                if chunk != b'IHDR' or size != 13:
                    break
                width, height = struct.unpack('>II', data[offset + 8:offset + 16])
            if chunk == b'IEND':
                seen_end = size == 0 and end + 4 == len(data)
                break
            offset = end + 4
        if seen_end:
            extension = '.png'
    elif data.startswith((b'GIF87a', b'GIF89a')) and len(data) >= 14 and data[-1:] == b';':
        width, height = struct.unpack('<HH', data[6:10])
        extension = '.gif'
    elif data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
        offset = 2
        while offset + 4 < len(data):
            if data[offset] != 0xff:
                break
            marker = data[offset + 1]
            if marker in (0xda, 0xd9):
                break
            length = struct.unpack('>H', data[offset + 2:offset + 4])[0]
            if length < 2 or offset + 2 + length > len(data):
                break
            if marker in (0xc0, 0xc1, 0xc2) and length >= 8:
                height, width = struct.unpack('>HH', data[offset + 5:offset + 9])
                extension = '.jpg'
                break
            offset += length + 2
    elif data.startswith(b'RIFF') and data[8:12] == b'WEBP' and len(data) >= 30:
        if struct.unpack('<I', data[4:8])[0] + 8 == len(data):
            if data[12:16] == b'VP8X':
                width = 1 + int.from_bytes(data[24:27], 'little')
                height = 1 + int.from_bytes(data[27:30], 'little')
            elif data[12:16] == b'VP8 ' and data[23:26] == b'\x9d\x01\x2a':
                width, height = (value & 0x3fff for value in struct.unpack('<HH', data[26:30]))
            elif data[12:16] == b'VP8L' and data[20] == 0x2f:
                bits = int.from_bytes(data[21:25], 'little')
                width, height = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
            extension = '.webp'
    if not extension or not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16000000):
        raise ValueError('Use a valid PNG, JPEG, GIF or WebP image up to 16 megapixels')
    return extension


def _save_uploaded_image(field, folder, fixed_name=None):
    file = request.files.get(field)
    if not file or not file.filename:
        raise ValueError('Choose an image file')
    data = file.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('Images must be 8 MB or smaller')
    extension = _image_type(data)
    os.makedirs(folder, exist_ok=True)
    name = fixed_name or uuid.uuid4().hex + extension
    fd, temporary = tempfile.mkstemp(prefix='.upload-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, os.path.join(folder, name))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return name


@app.errorhandler(413)
def _upload_too_large(error):
    return jsonify({'error': 'Request is too large; images must be 8 MB or smaller'}), 413


@app.route('/api/upload_special_image', methods=['POST'])
@require_admin
def upload_special_image():
    try:
        filename = _save_uploaded_image('image', SPECIALS_FOLDER)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    return jsonify({"url": f"/static/uploads/specials/{filename}"})


@app.route('/api/upload_rss_logo', methods=['POST'])
@require_admin
def upload_rss_logo():
    try:
        filename = _save_uploaded_image('logo', RSS_LOGOS_FOLDER)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    return jsonify({"url": f"/static/uploads/rss_logos/{filename}"})


@app.route('/api/upload_logo', methods=['POST'])
@require_admin
def upload_logo():
    try:
        _save_uploaded_image('logo', UPLOAD_FOLDER, fixed_name='logo.png')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    return jsonify({'status': 'ok', 'logo_version': _logo_version()})


@app.route('/api/logo', methods=['DELETE'])
@require_admin
def remove_logo():
    try:
        os.unlink(os.path.join(UPLOAD_FOLDER, 'logo.png'))
    except FileNotFoundError:
        pass
    return jsonify({'status': 'ok', 'logo_version': ''})


@app.route('/api/teams/<path:league_path>')
def teams_api(league_path):
    # In kiosk mode, try server first
    settings = get_settings()
    if settings.get('device_mode') == 'kiosk':
        cfg = get_kiosk_config()
        server_url = cfg.get('server_url', '').strip().rstrip('/')
        if server_url:
            try:
                r = requests.get(f"{server_url}/api/teams/{league_path}", timeout=8)
                if r.ok:
                    return jsonify(_merge_picker_teams(league_path, r.json()))
            except Exception:
                pass

    return jsonify(_picker_teams(league_path))


def _football_catalog():
    """Reload the small shipped catalog after a reviewed in-place code update."""
    path = os.path.join(APP_DIR, 'static', 'data', 'football-teams-2026.json')
    try:
        signature = (path, os.stat(path).st_mtime_ns)
        if _football_catalog_cache['signature'] != signature:
            if os.path.getsize(path) > 512 * 1024:
                raise ValueError('Team catalog too large')
            with open(path) as source:
                data = json.load(source)
            if not isinstance(data, dict):
                raise ValueError('Invalid team catalog')
            lookup = {}
            for key, league in [('cfb', 'football/college-football'), ('nfl', 'football/nfl')]:
                lookup[league] = {str(team['id']): team for team in data.get(key, [])
                                  if isinstance(team, dict) and team.get('id')}
            _football_catalog_cache.update(signature=signature, data=data, teams_by_id=lookup)
        return _football_catalog_cache['data']
    except (OSError, ValueError):
        return {}


def _team_aliases(path, team_id, abbreviation):
    if path not in ('football/college-football', 'football/nfl'):
        return [abbreviation]
    _football_catalog()
    row = _football_catalog_cache['teams_by_id'].get(path, {}).get(str(team_id), {})
    return list(dict.fromkeys([abbreviation, row.get('abbr', abbreviation)] + row.get('aliases', [])))


def _merge_picker_teams(path, teams):
    catalog_key = {'football/college-football': 'cfb', 'football/nfl': 'nfl'}.get(path)
    canonical = _football_catalog().get(catalog_key, []) if catalog_key else []
    merged = {str(team['id']): dict(team) for team in canonical if isinstance(team, dict) and team.get('id')}
    if not isinstance(teams, list):
        teams = []
    for team in teams[:1000]:
        if not isinstance(team, dict) or not isinstance(team.get('abbr'), str) or not isinstance(team.get('name'), str):
            continue
        key = str(team.get('id') or team['abbr'])
        if key in merged:
            # Keep the favorite identifier stable; fresh names/colors/logos can
            # improve the display without rewriting any saved favorite keys.
            abbr = merged[key]['abbr']
            merged[key].update({field: value for field, value in team.items() if value})
            merged[key]['abbr'] = abbr
        else:
            existing = next((value for value in merged.values() if value['abbr'] == team['abbr']), None)
            if existing is not None:
                existing.update({field: value for field, value in team.items() if value})
            else:
                merged[key] = dict(team)
    favorites = set(value.upper() for value in get_settings().get('teams', []))
    for team in merged.values():
        for alias in [team['abbr']] + team.get('aliases', []):
            if f'{path}:{alias}'.upper() in favorites:
                team['abbr'] = alias
                break
    return sorted(merged.values(), key=lambda team: team['name'].casefold())


def _picker_teams(league_path):
    if league_path not in ESPN_API_PATHS:
        return []
    now = time_module.monotonic()
    with _team_picker_lock:
        entry = _team_picker_cache.get(league_path, {})
        if now < entry.get('retry_at', 0):
            return _merge_picker_teams(league_path, entry.get('teams', []))
    sport, league = ESPN_API_PATHS[league_path]
    base_host = "site.web.api.espn.com" if league_path in ESPN_WEB_API_LEAGUES else "site.api.espn.com"
    try:
        response = requests.get(
            f"https://{base_host}/apis/site/v2/sports/{sport}/{league}/teams?limit=500",
            timeout=(3, 5))
        response.raise_for_status()
        res = response.json()
        teams = res['sports'][0]['leagues'][0]['teams']
        if not isinstance(teams, list):
            raise ValueError('Invalid team list')
        parsed = []
        for item in teams[:1000]:
            team = item.get('team') if isinstance(item, dict) else None
            if not isinstance(team, dict) or not all(isinstance(team.get(key), str) and team[key]
                                                     for key in ('abbreviation', 'displayName')):
                continue
            logos = team.get('logos')
            logo = logos[0].get('href', '') if isinstance(logos, list) and logos and isinstance(logos[0], dict) else ''
            parsed.append({'id': str(team.get('id', '')), 'abbr': team['abbreviation'],
                           'name': team['displayName'], 'logo': logo if isinstance(logo, str) else '',
                           'color': team.get('color', '') if isinstance(team.get('color', ''), str) else ''})
        teams = parsed
        if not teams:
            raise ValueError('Empty team response')
        entry = {'teams': teams, 'retry_at': now + 3600, 'failures': 0}
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError):
        failures = min(5, entry.get('failures', 0) + 1)
        entry = {**entry, 'failures': failures, 'retry_at': now + min(900, 60 * 2 ** (failures - 1))}
    with _team_picker_lock:
        _team_picker_cache[league_path] = entry
    return _merge_picker_teams(league_path, entry.get('teams', []))


@app.route('/api/conferences/<path:league_path>')
def conferences_api(league_path):
    if league_path in HARDCODED_CONFERENCES:
        return jsonify(HARDCODED_CONFERENCES[league_path])
    return jsonify([])


def _kiosk_display_data(data, settings, tz_str):
    data = dict(data)
    source_coverage = data.get('cfb_coverage')
    # Override server's display settings with this kiosk's own preferences
    kiosk_colors, kiosk_header = resolve_palette(settings)
    data['display_name']     = settings.get('display_name', data.get('display_name', 'SCOREBOARD'))
    data['header_color']     = kiosk_header
    data['cast_orientation'] = settings.get('cast_orientation', data.get('cast_orientation', 'auto'))
    data['theme']            = settings.get('theme', data.get('theme', 'dark'))
    data['colors']           = kiosk_colors
    data['color_mode']       = settings.get('color_mode', data.get('color_mode', 'auto'))
    data['palette_team']     = settings.get('palette_team', data.get('palette_team', ''))
    data['font_primary']     = settings.get('font_primary', data.get('font_primary', 'Barlow Condensed'))
    data['show_logo_slide']  = settings.get('show_logo_slide', True)
    data['logo_version']     = _logo_version()
    data['logo_available']   = bool(_logo_version())
    for key, fallback in [('display_mode', 'hybrid'), ('slide_playlist', []),
                          ('slide_duration', 8), ('logo_slide_duration', 8),
                          ('transition_duration_ms', 500), ('slide_transition', 'slide-right'),
                          ('ticker_speed', 120)]:
        data[key] = settings.get(key, fallback)
    data['clock_format']     = settings.get('clock_format', '12h')
    data['header_visibility'] = settings.get('header_visibility', 'auto')
    data['cfb_coverage'] = settings.get('cfb_coverage', 'all_power5')
    desired_coverage = data['cfb_coverage']
    source_errors = data.get('cache_errors')
    if (isinstance(source_errors, dict) and source_errors.get('kiosk') and source_coverage in ('all_power5', 'favorites')
            and source_coverage != desired_coverage):
        # Retained cards are not a new discovery result. Keep their actual mode
        # until the server can apply the saved preference and supply that slate.
        data['cfb_coverage'] = source_coverage
        data['cfb_coverage_pending'] = desired_coverage
        labels = {'all_power5': 'All Power 5 Games', 'favorites': 'favorites / priority games'}
        source_week = data.get('cfb_week')
        data['cfb_week'] = {**(source_week if isinstance(source_week, dict) else {}), 'warning':
            'College football coverage change saved; awaiting server reconnection. '
            'Showing cached ' + labels[source_coverage] + '.'}
    data['cfb_refresh_seconds'] = settings.get('cfb_refresh_seconds', 180)
    data['show_time_bar'] = settings.get('show_time_bar', True)
    data['show_title_bar'] = settings.get('show_title_bar', True)
    data['timezone']         = tz_str
    data['specials']         = [
        s for s in settings.get('specials', [])
        if s.get('enabled') and (s.get('title') or s.get('image'))
        and _special_active_today(s, tz_str)
    ]
    if settings.get('city'):
        data['weather'] = get_weather(settings['city'])
    data['local_schedule_items'] = _build_local_schedule_items(settings, tz_str)
    data['settings_updated_at'] = settings.get('last_saved', '')
    return _apply_scorecard_filter(_apply_football_display(data, settings, tz_str), settings)


@app.route('/api/data', methods=['GET', 'POST'])
def data_api():
    global _kiosk_server_unreachable, _kiosk_last_data
    settings = get_settings()
    mode = settings.get('device_mode', 'server')
    tz_str = settings.get('timezone', 'US/Central')

    if mode == 'kiosk':
        cfg = get_kiosk_config()
        server_url = cfg.get('server_url', '').strip().rstrip('/')
        if server_url:
            try:
                payload = {
                    "leagues": settings.get('leagues', []),
                    "teams": settings.get('teams', []),
                    "league_conferences": settings.get('league_conferences', {}),
                    "timezone": tz_str,
                    "conference_filters_version": 2,
                    # Keep both leagues in the retained slate so an offline
                    # kiosk can still switch at local midnight or after a save.
                    "football_display": "both",
                    "scorecard_filter": "both",
                    "scorecard_include_completed": True,
                }
                for key in ('date_windows', 'football_priority', 'cfb_coverage', 'cfb_refresh_seconds', 'nascar_favorites',
                            'indycar_favorites', 'f1_favorites', 'golf_favorites'):
                    payload[key] = settings.get(key)
                started = time_module.monotonic()
                r = requests.post(f"{server_url}/api/data", json=payload, timeout=10)
                if r.ok:
                    data = r.json()
                    if not isinstance(data, dict) or not isinstance(data.get('teams'), list) or not isinstance(data.get('ticker_parts', []), list):
                        raise ValueError('Invalid server data')
                    data = _trim_live_details(data, time_module.monotonic() - started)
                    _kiosk_server_unreachable = False
                    _kiosk_last_data = data
                    return jsonify(_kiosk_display_data(data, settings, tz_str))
            except Exception:
                pass
        if server_url and _kiosk_last_data is not None:
            _kiosk_server_unreachable = True
            retained = _trim_live_details(_kiosk_last_data, stale=True)
            retained['cache_stale'] = True
            retained['cache_errors'] = {**retained.get('cache_errors', {}),
                                        'kiosk': 'Server unreachable; showing saved scores'}
            return jsonify(_kiosk_display_data(retained, settings, tz_str))
        _kiosk_server_unreachable = True
        # Fall through to standalone if server is unreachable

    # Server mode (or kiosk fallback to direct ESPN)
    req_data = {}
    if request.method == 'POST':
        req_data = request.get_json(silent=True)
        try:
            _validate_settings(req_data)
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        req_data = _migrate_conference_filters(req_data)
    # Display-specific sports filters never mutate global/persistent settings.
    settings = dict(settings)
    for key in ('date_windows', 'football_priority', 'football_display', 'cfb_coverage', 'cfb_refresh_seconds', 'scorecard_filter', 'scorecard_include_completed', 'nascar_favorites',
                'indycar_favorites', 'f1_favorites', 'golf_favorites'):
        if key in req_data:
            settings[key] = req_data[key]

    active_leagues = req_data['leagues'] if req_data.get('leagues') is not None else settings.get('leagues', [])
    active_teams   = req_data['teams']   if req_data.get('teams')   is not None else settings.get('teams', [])
    active_lc      = req_data['league_conferences'] if 'league_conferences' in req_data else settings.get('league_conferences', {})
    active_tz      = req_data.get('timezone', tz_str)

    return jsonify(_build_data_response(active_leagues, active_teams, active_lc, active_tz, settings))


@app.route('/api/resolve_feed', methods=['POST'])
@require_admin
def resolve_feed_api():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    try:
        resolved, feed_type = _resolve_feed(url)
        labels = {'rss': 'RSS feed', 'ical': 'iCal calendar', 'thrillshare': 'Thrillshare calendar', 'maxpreps': 'MaxPreps schedule'}
        count = 0
        sample = ''
        if feed_type:
            probe = []
            tz_str = get_settings().get('timezone', 'America/Chicago')
            if feed_type == 'thrillshare':
                _parse_thrillshare_feed(resolved, 'PROBE', '', probe, tz_str)
            elif feed_type == 'maxpreps':
                _parse_maxpreps_feed(resolved, 'PROBE', '', probe, tz_str)
            elif feed_type == 'rss':
                _parse_rss_feed(resolved, 'PROBE', '', probe)
            elif feed_type == 'ical':
                _parse_ical_feed(resolved, 'PROBE', '', probe, tz_str)
            count = len(probe)
            if probe:
                sample = probe[0].get('title', '')
        return jsonify({"resolved_url": resolved, "feed_type": feed_type,
                        "feed_type_label": labels.get(feed_type, 'Unknown'),
                        "event_count": count, "sample_title": sample,
                        "ok": feed_type is not None})
    except Exception as e:
        return jsonify({"error": str(e), "ok": False}), 500


@app.route('/api/cache/status')
@require_admin
def cache_status_api():
    with _cache_lock:
        return jsonify({
            "updated_at": _espn_cache.get("updated_at"),
            "leagues_cached": list(_espn_cache["raw_events"].keys()),
            "errors": dict(_cache_errors),
            "stale": bool(_cache_errors),
        })


@app.route('/api/cache/refresh', methods=['POST'])
@require_admin
def cache_refresh_api():
    threading.Thread(target=_refresh_espn_cache, daemon=True).start()
    return jsonify({"ok": True, "message": "Refresh started"})


def _run_display_cmd(action):
    env = os.environ.copy()
    env.setdefault('DISPLAY', ':0')
    env.setdefault('XAUTHORITY', os.path.expanduser('~/.Xauthority'))
    try:
        if action == 'on':
            # Wake display, then disable DPMS/screensaver so it stays on
            for cmd in [
                ['xset', 'dpms', 'force', 'on'],
                ['xset', '-dpms'],
                ['xset', 's', 'off'],
                ['xset', 's', 'noblank'],
            ]:
                subprocess.run(cmd, env=env, timeout=5)
        else:
            subprocess.run(['xset', 'dpms', 'force', 'off'], env=env, timeout=5, check=True)
        return True, None
    except Exception as e:
        return False, str(e)


@app.route('/api/display/<action>', methods=['POST'])
@login_required
def display_control(action):
    if action not in ('on', 'off'):
        return jsonify({"error": "Invalid action"}), 400
    ok, err = _run_display_cmd(action)
    if ok:
        return jsonify({"status": "ok", "action": action})
    return jsonify({"error": err}), 500


@app.route('/api/backend/restart', methods=['POST'])
@login_required
def backend_restart():
    try:
        subprocess.Popen(['bash', '-c', 'sleep 1 && sudo -n systemctl restart scoreboard.service'])
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── WIFI MANAGEMENT ───

def _wifi_tool():
    """Returns ('nmcli'|'iw'|'iwlist'|'wpa', iface) or (None, None).

    NetworkManager is only used when it actually manages the wireless device.
    Interfaces bound by an external wpa_supplicant / dhcpcd show as 'unmanaged'
    in nmcli and yield empty scans, so those fall through to iw/iwlist/wpa_cli.
    """
    # Try nmcli first, but only for devices NetworkManager manages
    try:
        r = subprocess.run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device'],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            p = line.split(':')
            if len(p) >= 2 and p[1] == 'wifi':
                if len(p) < 3 or p[2] != 'unmanaged':
                    return 'nmcli', p[0]
                break
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Find wireless interface
    iface = None
    try:
        for name in sorted(os.listdir('/sys/class/net')):
            if os.path.isdir(f'/sys/class/net/{name}/wireless'):
                iface = name
                break
    except Exception:
        pass
    if not iface:
        return None, None
    # Prefer iwscan results (root needed) — wpa_cli is the reliable fallback for
    # supplicant-owned interfaces; iw/iwlist are still tried first.
    for cmd in ('iw', 'iwlist'):
        try:
            subprocess.run([cmd, '--version'], capture_output=True, timeout=2)
            return ('iw' if cmd == 'iw' else 'iwlist'), iface
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    # wpa_supplicant/wpa_cli without a scan tool — still usable for connect
    return 'wpa', iface


@app.route('/api/wifi/status')
@login_required
def wifi_status():
    tool, iface = _wifi_tool()
    if not iface:
        return jsonify({'available': False, 'error': 'No wireless interface found'})
    info = {'available': True, 'iface': iface, 'connected': False, 'ssid': '', 'ip': '', 'signal': 0}
    try:
        if tool == 'nmcli':
            r = subprocess.run(['nmcli', '-t', '-f', 'DEVICE,STATE,CONNECTION', 'device', 'status'],
                               capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                p = line.split(':')
                if p[0] == iface:
                    info['connected'] = p[1] == 'connected'
                    info['ssid'] = p[2] if len(p) > 2 else ''
                    break
            if info['connected']:
                r2 = subprocess.run(['nmcli', '-t', '-f', 'IP4.ADDRESS', 'device', 'show', iface],
                                    capture_output=True, text=True, timeout=5)
                for line in r2.stdout.splitlines():
                    if 'IP4.ADDRESS' in line:
                        info['ip'] = line.split(':')[-1].split('/')[0]
                        break
                r3 = subprocess.run(['nmcli', '-t', '-f', 'ACTIVE,SIGNAL,SSID', 'device', 'wifi'],
                                    capture_output=True, text=True, timeout=5)
                for line in r3.stdout.splitlines():
                    p = line.split(':')
                    if p[0] == 'yes' and len(p) >= 3:
                        try:
                            info['signal'] = int(p[1])
                        except ValueError:
                            pass
                        break
        else:
            # iw / iwlist / wpa fallback
            try:
                with open(f'/sys/class/net/{iface}/operstate') as f:
                    info['connected'] = f.read().strip() == 'up'
            except Exception:
                pass
            if info['connected']:
                r2 = subprocess.run(['ip', '-4', 'addr', 'show', iface],
                                    capture_output=True, text=True, timeout=3)
                for line in r2.stdout.splitlines():
                    if 'inet ' in line:
                        info['ip'] = line.strip().split()[1].split('/')[0]
                        break
                # Get SSID via iw if available
                try:
                    ri = subprocess.run(['iw', 'dev', iface, 'info'],
                                        capture_output=True, text=True, timeout=3)
                    for line in ri.stdout.splitlines():
                        if 'ssid' in line.lower():
                            info['ssid'] = line.strip().split(None, 1)[-1]
                            break
                except FileNotFoundError:
                    pass
                try:
                    with open('/proc/net/wireless') as f:
                        for line in f:
                            if iface in line:
                                parts = line.split()
                                info['signal'] = int(float(parts[3].rstrip('.')))
                except Exception:
                    pass
    except Exception as e:
        info['error'] = str(e)
    return jsonify(info)


# Retry only through the reviewed, root-owned network command allowlist.
_NETWORK_HELPER = '/usr/local/libexec/scoreboard-network'


def _run(cmd, timeout=20):
    last = None
    for prefix in ([], ['sudo', '-n', _NETWORK_HELPER]):
        try:
            r = subprocess.run(prefix + cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return r
            last = r
        except (subprocess.TimeoutExpired, FileNotFoundError):
            last = None
    return last


def _ensure_iface_up(iface):
    """Bring the interface up before scanning (iw/iwlist need it up)."""
    try:
        with open(f'/sys/class/net/{iface}/operstate') as f:
            if f.read().strip() == 'up':
                return
    except Exception:
        pass
    _run(['ip', 'link', 'set', iface, 'up'], timeout=10)


def _parse_nm_list(text):
    """Parse `nmcli -t -f SSID,SIGNAL,SECURITY,ACTIVE device wifi list` output.
    Parsing from the right keeps SSIDs containing colons intact."""
    nets = []
    for line in text.splitlines():
        p = line.split(':')
        if len(p) < 4:
            continue
        active = p[-1].strip()
        security = p[-2].strip()
        try:
            sig = int(p[-3].strip())
        except ValueError:
            sig = 0
        ssid = ':'.join(p[:-3]).strip()
        if ssid:
            nets.append({'ssid': ssid, 'signal': sig,
                         'security': security or 'Open', 'active': active == 'yes'})
    return nets


def _parse_iw_scan(text):
    nets = []
    entry = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('BSS '):
            if entry.get('ssid'):
                nets.append(entry)
            entry = {'ssid': '', 'signal': 0, 'security': 'Open', 'active': False}
        elif line.startswith('SSID:'):
            entry['ssid'] = line[5:].strip()
        elif line.startswith('signal:'):
            try:
                dbm = float(line.split(':')[1].split()[0])
                entry['signal'] = max(0, min(100, int(dbm + 110)))
            except Exception:
                pass
        elif 'RSN:' in line or 'WPA:' in line:
            entry['security'] = 'WPA2' if 'RSN' in line else 'WPA'
    if entry.get('ssid'):
        nets.append(entry)
    return nets


def _parse_iwlist_scan(text):
    nets = []
    ssid, sig, sec = '', 0, 'Open'
    for line in text.splitlines():
        line = line.strip()
        if 'ESSID:' in line:
            ssid = line.split('ESSID:')[1].strip().strip('"')
        elif 'Signal level=' in line:
            try:
                sig_str = line.split('Signal level=')[1].split(' ')[0]
                sig_val = int(sig_str.split('/')[0])
                sig = sig_val + 100 if sig_val < 0 else sig_val
            except Exception:
                sig = 0
        elif 'Encryption key:' in line:
            sec = 'WPA' if 'on' in line else 'Open'
        elif 'Extra:' in line and ssid:
            nets.append({'ssid': ssid, 'signal': sig, 'security': sec, 'active': False})
            ssid, sig, sec = '', 0, 'Open'
    if ssid:
        nets.append({'ssid': ssid, 'signal': sig, 'security': sec, 'active': False})
    return nets


def _parse_wpa_scan(text):
    """Parse `wpa_cli -i <iface> scan_results` output (tab-separated)."""
    nets = []
    for line in text.splitlines():
        p = line.split('\t')
        if len(p) < 4 or ':' not in p[0][:5]:
            continue
        sig_str = p[2].strip()
        flags = p[3]
        ssid = p[4].strip() if len(p) > 4 else ''
        if not ssid:
            continue
        try:
            dbm = float(sig_str)
            if abs(dbm) > 200:
                dbm = dbm / 100.0
            sig = max(0, min(100, int(dbm + 110)))
        except Exception:
            sig = 0
        if 'WPA2' in flags:
            sec = 'WPA2'
        elif 'WPA' in flags:
            sec = 'WPA'
        else:
            sec = 'Open'
        nets.append({'ssid': ssid, 'signal': sig, 'security': sec, 'active': False})
    return nets


@app.route('/api/wifi/scan')
@login_required
def wifi_scan():
    tool, iface = _wifi_tool()
    if not iface:
        return jsonify({'networks': [], 'error': 'No wireless interface found'})
    networks = []
    errors = []
    try:
        if tool == 'nmcli':
            # Make sure NetworkManager manages the device, then force a scan.
            # --rescan yes can return empty before the scan completes, so retry
            # a few times and fall back to a plain (non-rescan) list.
            _run(['nmcli', 'device', 'set', iface, 'managed', 'yes'], timeout=10)
            ok = False
            for _ in range(4):
                r = _run(['nmcli', '--escape', 'no', '-t', '-f', 'SSID,SIGNAL,SECURITY,ACTIVE',
                          'device', 'wifi', 'list', '--rescan', 'yes'], timeout=25)
                if r is None:
                    errors.append('nmcli unavailable')
                    break
                networks = _parse_nm_list(r.stdout)
                if networks:
                    ok = True
                    break
                time_module.sleep(2)
                r2 = _run(['nmcli', '--escape', 'no', '-t', '-f', 'SSID,SIGNAL,SECURITY,ACTIVE',
                           'device', 'wifi', 'list'], timeout=15)
                networks = _parse_nm_list(r2.stdout if r2 else '')
                if networks:
                    ok = True
                    break
            if not ok and not errors:
                errors.append('nmcli returned no networks — is Wi-Fi switched on?')
        elif tool == 'iw':
            _ensure_iface_up(iface)
            r = _run(['iw', 'dev', iface, 'scan'], timeout=25)
            if r is None:
                errors.append('iw scan failed (is the wireless interface up?)')
            else:
                networks = _parse_iw_scan(r.stdout)
        elif tool == 'iwlist':
            _ensure_iface_up(iface)
            r = _run(['iwlist', iface, 'scan'], timeout=20)
            if r is None:
                errors.append('iwlist scan failed (is the wireless interface up?)')
            else:
                networks = _parse_iwlist_scan(r.stdout)
        elif tool == 'wpa':
            # Dedicated wpa_supplicant (interface unmanaged by NM): scan via its
            # control socket. Privileged retry uses the reviewed network helper.
            _ensure_iface_up(iface)
            _run(['wpa_cli', '-i', iface, 'scan'], timeout=15)
            time_module.sleep(3)
            r = _run(['wpa_cli', '-i', iface, 'scan_results'], timeout=15)
            if r is None or r.returncode != 0:
                errors.append('wpa_cli scan failed (is the wireless interface up?)')
            else:
                networks = _parse_wpa_scan(r.stdout)
        else:
            return jsonify({'networks': [], 'error': 'No scan tool available (install iw or network-manager)'})
    except Exception as e:
        return jsonify({'networks': [], 'error': str(e)})

    networks.sort(key=lambda n: (not n['active'], -n['signal']))
    seen, unique = set(), []
    for n in networks:
        if n['ssid'] not in seen:
            seen.add(n['ssid'])
            unique.append(n)
    out = {'networks': unique}
    if errors:
        out['error'] = '; '.join(errors)
    return jsonify(out)


@app.route('/api/wifi/connect', methods=['POST'])
@login_required
def wifi_connect():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not isinstance(data.get('ssid', ''), str) or not isinstance(data.get('password', ''), str):
        return jsonify({'ok': False, 'error': 'SSID and password must be text'}), 400
    ssid = data.get('ssid', '')
    password = data.get('password', '')
    if not 1 <= len(ssid.encode('utf-8')) <= 32 or any(ord(c) < 32 for c in ssid):
        return jsonify({'ok': False, 'error': 'SSID must contain 1–32 bytes without control characters'}), 400
    if password and (any(ord(c) < 32 for c in password) or not (8 <= len(password) <= 63 or re.fullmatch(r'[0-9a-fA-F]{64}', password))):
        return jsonify({'ok': False, 'error': 'Wi-Fi password must contain 8–63 characters or 64 hexadecimal digits'}), 400
    tool, iface = _wifi_tool()
    if not iface:
        return jsonify({'ok': False, 'error': 'No wireless interface found'})
    try:
        if tool == 'nmcli':
            cmd = ['nmcli', 'device', 'wifi', 'connect', ssid, 'ifname', iface]
            if password:
                cmd += ['password', password]
            r = _run(cmd, timeout=30)
            if r is None:
                return jsonify({'ok': False, 'error': 'nmcli connect failed (is the interface available?)'})
            ok = r.returncode == 0
            msg = (r.stdout.strip() or r.stderr.strip()).splitlines()[0] if (r.stdout or r.stderr) else ''
            return jsonify({'ok': ok, 'message': msg})
        else:
            # iw / iwlist: connect via wpa_cli runtime commands (no file writes needed)
            def _wpa(args):
                result = _run(['wpa_cli', '-i', iface] + args, timeout=10)
                if result is None:
                    raise RuntimeError('Network command unavailable; install the reviewed scoreboard-network helper')
                if result.returncode or result.stdout.strip() == 'FAIL':
                    raise RuntimeError('Wi-Fi command failed; check the network helper and wireless interface')
                return result

            # Add a new network slot
            r = _wpa(['add_network'])
            net_id = r.stdout.strip().split('\n')[-1].strip()
            if not net_id.isdigit():
                return jsonify({'ok': False, 'error': f'wpa_cli add_network failed: {r.stderr.strip() or r.stdout.strip()}'})

            # Configure the network
            _wpa(['set_network', net_id, 'ssid', json.dumps(ssid, ensure_ascii=False)])
            if password:
                _wpa(['set_network', net_id, 'psk', password if len(password) == 64 else json.dumps(password, ensure_ascii=False)])
            else:
                _wpa(['set_network', net_id, 'key_mgmt', 'NONE'])

            # Enable and switch to this network
            _wpa(['enable_network', net_id])
            _wpa(['select_network', net_id])

            # Persist to config file if wpa_supplicant was started with update_config=1
            _wpa(['save_config'])

            return jsonify({'ok': True, 'message': f'Connecting to "{ssid}"…'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/wifi/disconnect', methods=['POST'])
@login_required
def wifi_disconnect():
    tool, iface = _wifi_tool()
    if not iface:
        return jsonify({'ok': False, 'error': 'No wireless interface found'})
    try:
        if tool == 'nmcli':
            r = _run(['nmcli', 'device', 'disconnect', iface], timeout=10)
            if r is None:
                return jsonify({'ok': False, 'error': 'nmcli disconnect failed'})
            return jsonify({'ok': r.returncode == 0, 'message': r.stdout.strip() or r.stderr.strip()})

        # wpa_cli fallback: disconnect + disable all networks to prevent auto-reconnect
        def _wpa(args):
            result = _run(['wpa_cli', '-i', iface] + args, timeout=10)
            if result is None or result.returncode or result.stdout.strip() == 'FAIL':
                raise RuntimeError('Wi-Fi command failed; check the reviewed network helper')
            return result

        # Disconnect
        _wpa(['disconnect'])

        # Disable all configured networks so supplicant won't auto-reconnect
        r_list = _wpa(['list_networks'])
        if r_list and r_list.returncode == 0:
            for line in r_list.stdout.splitlines():
                parts = line.strip().split('\t')
                if parts and parts[0].isdigit():
                    _wpa(['disable_network', parts[0]])

        _wpa(['save_config'])
        return jsonify({'ok': True, 'message': 'Disconnected.'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


def _kiosk_unit_installed():
    return os.path.exists('/etc/systemd/system/kiosk.service') or os.path.exists('/lib/systemd/system/kiosk.service')


def _kiosk_browser_running():
    try:
        r = subprocess.run(['pgrep', '-f', '--', '--kiosk'], capture_output=True, timeout=3)
        return r.returncode == 0
    except Exception:
        return False


def _systemctl(args, timeout=15):
    last = None
    for prefix in ([], ['sudo', '-n']):
        try:
            last = subprocess.run(prefix + ['systemctl'] + args,
                                  capture_output=True, text=True, timeout=timeout)
            if last.returncode == 0:
                return last
        except Exception as e:
            last = e
    if isinstance(last, Exception):
        raise last
    return last


@app.route('/api/kiosk/<action>', methods=['POST'])
@login_required
def kiosk_control(action):
    if action not in ('start', 'stop', 'restart'):
        return jsonify({"error": "Invalid action"}), 400
    if not _kiosk_unit_installed():
        return jsonify({"error": "kiosk.service is not installed. Re-run install.sh and choose Kiosk or Combined mode."}), 404
    try:
        if action == 'start':
            check = subprocess.run(
                ['systemctl', 'is-active', 'kiosk.service'],
                capture_output=True, text=True, timeout=5,
            )
            if check.stdout.strip() == 'active':
                action = 'restart'
        result = _systemctl([action, 'kiosk.service'])
        if result.returncode == 0:
            return jsonify({"status": "ok", "action": action})
        if action in ('restart', 'start'):
            # Fallback: force-kill any kiosk browser; systemd's Restart=always
            # (or an explicit start) will bring it back up.
            subprocess.run(['pkill', '-f', '--', '--kiosk'], capture_output=True, timeout=5)
            time_module.sleep(1)
            result2 = _systemctl(['start', 'kiosk.service'])
            if result2.returncode == 0:
                return jsonify({"status": "ok", "action": action, "fallback": True})
        return jsonify({"error": (result.stderr or result.stdout or "Command failed").strip()}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/kiosk/status', methods=['GET'])
@login_required
def kiosk_status():
    if not _kiosk_unit_installed():
        if _kiosk_browser_running():
            return jsonify({"status": "active"})
        return jsonify({"status": "not-installed"})
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'kiosk.service'],
            capture_output=True, text=True, timeout=5,
        )
        st = (result.stdout or '').strip() or 'unknown'
        if st != 'active' and _kiosk_browser_running():
            st = 'active'
        return jsonify({"status": st})
    except Exception as e:
        return jsonify({"status": "unknown", "error": str(e)})


@app.route('/api/debug')
@require_admin
def debug_api():
    settings = get_settings()
    tz_str = settings.get('timezone', 'US/Central')
    now = datetime.now()
    try:
        today_local = now.astimezone(pytz.timezone(tz_str)).date()
    except Exception:
        today_local = now.date()
    with _cache_lock:
        cached_paths = list(_espn_cache["raw_events"].keys())
        updated_at = _espn_cache.get("updated_at")
    return jsonify({
        "today_local": str(today_local),
        "cache_updated_at": updated_at,
        "cached_leagues": cached_paths,
        "device_mode": settings.get('device_mode'),
    })


# ─── ROUTES: PAIRING & KIOSK MANAGEMENT ───

@app.route('/api/ping')
def ping():
    settings = get_settings()
    return jsonify({
        "ok": True,
        "mode": settings.get('device_mode', 'server'),
        "name": settings.get('display_name', 'Server'),
    })


@app.route('/api/pairing/code', methods=['GET'])
@require_admin
def pairing_code_api():
    now = time_module.time()
    for c in list(_pairing_codes):
        if _pairing_codes[c] < now:
            del _pairing_codes[c]
    if len(_pairing_codes) >= 20:
        return jsonify({'error': 'Too many active pairing codes; try again after ten minutes'}), 429
    code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    _pairing_codes[code] = now + 600
    return jsonify({"code": code, "expires_in": 600})


def _valid_pairing_payload(data):
    if not isinstance(data, dict):
        return False
    for key in ('code', 'kiosk_id', 'kiosk_url', 'kiosk_name', 'server_url'):
        if key in data and (not isinstance(data[key], str) or len(data[key]) > 2048 or
                            any(ord(character) < 32 for character in data[key])):
            return False
    for key in ('server_url', 'kiosk_url'):
        if data.get(key):
            try:
                parsed = urlsplit(data[key])
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                    return False
            except ValueError:
                return False
    return True


@app.route('/api/pairing/claim', methods=['POST'])
@_registry_transaction
def pairing_claim():
    data = request.get_json(silent=True) or {}
    if not _valid_pairing_payload(data):
        return jsonify({'ok': False, 'error': 'Pairing fields must contain valid text and HTTP(S) URLs'}), 400
    code = data.get('code', '').upper().strip()
    kiosk_id = data.get('kiosk_id', '').strip()
    kiosk_name = data.get('kiosk_name', 'Kiosk')
    kiosk_url = data.get('kiosk_url', '')
    if not code or not kiosk_id:
        return jsonify({"ok": False, "error": "code and kiosk_id required"}), 400
    now = time_module.time()
    if code not in _pairing_codes or _pairing_codes[code] < now:
        return jsonify({"ok": False, "error": "Invalid or expired pairing code"}), 400
    del _pairing_codes[code]
    auth_token = uuid.uuid4().hex
    kiosks = get_kiosks()
    kiosks[kiosk_id] = {
        "name": kiosk_name,
        "url": kiosk_url,
        "ip": request.remote_addr,
        "last_seen": datetime.now(timezone.utc).isoformat(),
        "paired_at": datetime.now(timezone.utc).isoformat(),
        "auth_token": auth_token,
    }
    save_kiosks(kiosks)
    return jsonify({
        "ok": True,
        "server_name": get_settings().get('display_name', 'Server'),
        "auth_token": auth_token,
    })


@app.route('/api/pairing/connect', methods=['POST'])
@require_admin
def pairing_connect():
    data = request.get_json(silent=True) or {}
    if not _valid_pairing_payload(data):
        return jsonify({'ok': False, 'error': 'Pairing fields must contain valid text and HTTP(S) URLs'}), 400
    server_url = data.get('server_url', '').strip().rstrip('/')
    code = data.get('code', '').upper().strip()
    kiosk_name = data.get('kiosk_name', '').strip()
    if not server_url or not code:
        return jsonify({"ok": False, "error": "server_url and code required"}), 400
    cfg = get_kiosk_config()
    kiosk_id = cfg.get('kiosk_id') or uuid.uuid4().hex
    if not kiosk_name:
        kiosk_name = cfg.get('kiosk_name', 'Kiosk')
    try:
        r = requests.post(
            f"{server_url}/api/pairing/claim",
            json={"code": code, "kiosk_id": kiosk_id, "kiosk_name": kiosk_name},
            timeout=8,
        )
        result = r.json()
        if not result.get('ok'):
            return jsonify({"ok": False, "error": result.get('error', 'Pairing failed')}), 400
        save_kiosk_config({
            "server_url": server_url,
            "kiosk_id": kiosk_id,
            "kiosk_name": kiosk_name,
            "paired": True,
            "auth_token": result.get('auth_token', ''),
        })
        return jsonify({"ok": True, "server_name": result.get('server_name', '')})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/api/pairing/status')
@require_admin
def pairing_status():
    cfg = get_kiosk_config()
    server_url = cfg.get('server_url', '').strip().rstrip('/')
    server_reachable = False
    server_name = ''
    if server_url:
        try:
            r = requests.get(f"{server_url}/api/ping", timeout=3)
            if r.ok:
                server_reachable = True
                server_name = r.json().get('name', '')
        except Exception:
            pass
    return jsonify({
        "paired": cfg.get('paired', False),
        "server_url": server_url,
        "server_reachable": server_reachable,
        "server_name": server_name,
        "kiosk_id": cfg.get('kiosk_id', ''),
        "kiosk_name": cfg.get('kiosk_name', 'Kiosk'),
    })


@app.route('/api/pairing/disconnect', methods=['POST'])
@require_admin
def pairing_disconnect():
    cfg = get_kiosk_config()
    server_url = cfg.get('server_url', '').strip().rstrip('/')
    kiosk_id = cfg.get('kiosk_id', '')
    if server_url and kiosk_id:
        try:
            requests.delete(f"{server_url}/api/kiosks/{kiosk_id}", timeout=5)
        except Exception:
            pass
    save_kiosk_config({"server_url": '', "paired": False, "auth_token": ''})
    return jsonify({"ok": True})


@app.route('/api/kiosks', methods=['GET'])
@require_admin
def kiosks_list():
    kiosks = get_kiosks()
    result = []
    for kid, info in kiosks.items():
        try:
            last_seen_dt = dateutil_parser.parse(info['last_seen'])
            online = (datetime.now(timezone.utc) - last_seen_dt.astimezone(timezone.utc)).total_seconds() < 120
        except Exception:
            online = False
        result.append({
            "id": kid, "name": info.get("name", "Unknown"),
            "url": info.get("url", ""), "ip": info.get("ip", ""),
            "last_seen": info.get("last_seen", ""),
            "paired_at": info.get("paired_at", ""),
            "online": online,
        })
    return jsonify(result)


@app.route('/api/kiosks/<kiosk_id>', methods=['DELETE'])
@require_admin
@_registry_transaction
def kiosk_unpair(kiosk_id):
    kiosks = get_kiosks()
    kiosks.pop(kiosk_id, None)
    save_kiosks(kiosks)
    return jsonify({"ok": True})


@app.route('/api/kiosks/<kiosk_id>/heartbeat', methods=['POST'])
@_registry_transaction
def kiosk_heartbeat(kiosk_id):
    if not _kiosk_token_ok(request, expected_id=kiosk_id):
        return jsonify({'ok': False, 'error': 'Kiosk authentication required'}), 401
    kiosks = get_kiosks()
    if kiosk_id not in kiosks:
        return jsonify({"ok": False, "error": "Unknown kiosk"}), 404
    kiosks[kiosk_id]['last_seen'] = datetime.now(timezone.utc).isoformat()
    kiosks[kiosk_id]['ip'] = request.remote_addr
    data = request.get_json(silent=True) or {}
    if not _valid_pairing_payload(data):
        return jsonify({'ok': False, 'error': 'Heartbeat fields must contain valid text and HTTP(S) URLs'}), 400
    if data.get('kiosk_url'):
        kiosks[kiosk_id]['url'] = data['kiosk_url']
    save_kiosks(kiosks)
    return jsonify({"ok": True})


# ─── UPDATE SYSTEM ───

def _read_version():
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip()
    except Exception:
        return "1.0.0.1"


def _parse_version(v):
    """Parse a version string like 1.0.0.4 or v2.1 into a comparable tuple."""
    v = re.sub(r'^[vV]', '', str(v).strip())
    parts = re.split(r'[.\-]', v)
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    # Pad to 4 parts for consistent comparison
    while len(result) < 4:
        result.append(0)
    return tuple(result)


def _kiosk_token_ok(req, expected_id=None):
    """A public kiosk identifier is not a credential; require the pairing token."""
    token = req.headers.get('X-Kiosk-Token')
    kiosk_id = expected_id or req.headers.get('X-Kiosk-Id')
    kiosks = get_kiosks()
    return bool(token and any((not kiosk_id or key == kiosk_id) and
                              hmac.compare_digest(str(info.get('auth_token', '')).encode('utf-8'), token.encode('utf-8'))
                              for key, info in kiosks.items()))


def _check_remote_version(source_url):
    """
    Fetch version info from source_url.
    Supports:
      - GitHub releases API  (api.github.com/repos/.../releases/latest)
      - Custom JSON endpoint ({ "version": "1.0.0.4", "download_url": "..." })
      - Bare version endpoint (just another scoreboard at /api/update/version)
    Returns (version_str, download_url, error_str).
    """
    source_url = source_url.strip().rstrip('/')
    # Accept a plain GitHub repo URL (e.g. pasted straight from the browser/git remote)
    # and translate it to the releases API endpoint instead of failing on its HTML page.
    gh_match = re.match(r'^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$', source_url)
    if gh_match:
        source_url = f'https://api.github.com/repos/{gh_match.group(1)}/{gh_match.group(2)}/releases/latest'
    try:
        if 'api.github.com' in source_url:
            r = requests.get(source_url,
                             headers={'Accept': 'application/vnd.github.v3+json'},
                             timeout=10)
            r.raise_for_status()
            data = r.json()
            tag = data.get('tag_name', '')
            release_name = data.get('name', '')
            assets = data.get('assets', [])
            dl = next((a['browser_download_url'] for a in assets
                        if a['name'].endswith('.zip')), None)
            if not dl:
                dl = data.get('zipball_url', '')
            # tag_name may be a label ("secondfix") rather than a version number.
            # Extract a dotted version from tag_name first, then release name.
            _ver_re = re.compile(r'\d+\.\d+[\d.]*')
            ver_match = _ver_re.search(tag) or _ver_re.search(release_name)
            version_str = ver_match.group(0) if ver_match else tag
            return version_str, dl, None

        # Try as a scoreboard /api/update/version endpoint
        if source_url.endswith('/api/update/version') or '/api/update' not in source_url:
            probe_url = source_url if source_url.endswith('/api/update/version') \
                        else source_url + '/api/update/version'
            r = requests.get(probe_url, timeout=6)
            if r.ok:
                data = r.json()
                if 'version' in data:
                    base = source_url[:-len('/api/update/version')] if source_url.endswith('/api/update/version') else source_url
                    dl = base.rstrip('/') + '/api/update/package'
                    return data['version'], dl, None

        # Generic JSON endpoint
        r = requests.get(source_url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get('version', ''), data.get('download_url', ''), None
    except Exception as e:
        return None, None, str(e)


def _apply_update_package(download_url, kiosk_token=None, kiosk_id=None):
    """Apply reviewed packages with path validation, backups and file rollback.

    Device configuration, credentials, caches and uploads are never extracted.
    Git checkouts use the documented manual branch upgrade/rollback procedure.
    """
    if os.path.exists(os.path.join(APP_DIR, '.git')):
        return False, 'Git checkout detected; use the reviewed branch installation/rollback guide.'
    source = get_settings().get('update', {}).get('source_url', '')
    if 'auggnation/auggment-scoreboard' in source.lower():
        return False, 'Default upstream updates could replace this fork; configure a reviewed fork release first.'
    try:
        parsed = urlsplit(download_url or '')
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('A trusted HTTP(S) package URL is required')
        # HTTPS keeps public releases verified. Plain HTTP is reserved for local
        # paired scoreboards; do not send a kiosk credential to a release host.
        if parsed.scheme == 'http':
            import ipaddress
            try:
                local = ipaddress.ip_address(parsed.hostname).is_private
            except ValueError:
                local = parsed.hostname == 'localhost' or '.' not in parsed.hostname or parsed.hostname.endswith('.local')
            if not local:
                raise ValueError('Public update downloads require HTTPS')
        headers = {}
        server = urlsplit(get_kiosk_config().get('server_url', ''))
        if server.netloc and (parsed.scheme, parsed.netloc) == (server.scheme, server.netloc):
            if kiosk_token:
                headers['X-Kiosk-Token'] = kiosk_token
            if kiosk_id:
                headers['X-Kiosk-Id'] = kiosk_id
        with tempfile.TemporaryDirectory(prefix='scoreboard-update-') as temporary:
            package = os.path.join(temporary, 'update.zip')
            response = requests.get(download_url, headers=headers, timeout=(10, 60), stream=True,
                                    allow_redirects=not bool(headers))
            try:
                if headers and response.is_redirect:
                    raise ValueError('Authenticated update downloads cannot redirect to another URL')
                response.raise_for_status()
                downloaded = 0
                with open(package, 'wb') as handle:
                    for chunk in response.iter_content(8192):
                        downloaded += len(chunk)
                        if downloaded > 20 * 1024 * 1024:
                            raise ValueError('Update package exceeds 20 MB')
                        handle.write(chunk)
            finally:
                response.close()
            staged = {}
            with zipfile.ZipFile(package) as archive:
                members = archive.infolist()
                if len(members) > 3000 or sum(member.file_size for member in members) > 50 * 1024 * 1024:
                    raise ValueError('Update archive exceeds extraction limits')
                roots = {member.filename.split('/')[0] for member in members}
                prefix = next(iter(roots)) + '/' if len(roots) == 1 and any(
                    member.filename == next(iter(roots)) + '/app.py' for member in members) else ''
                for member in members:
                    raw = member.filename
                    path = PurePosixPath(raw)
                    if path.is_absolute() or '..' in path.parts or '\\' in raw or '\x00' in raw:
                        raise ValueError('Unsafe path in update archive')
                    if stat.S_ISLNK(member.external_attr >> 16):
                        raise ValueError('Symlinks are not allowed in update archives')
                    rel = raw[len(prefix):] if prefix and raw.startswith(prefix) else raw
                    if member.is_dir() or not rel:
                        continue
                    allowed = (rel in ('app.py', 'score_details.py', 'cfb_week.py', 'requirements.txt', 'version.txt', 'LICENSE',
                                       'README.md', 'QC_REPORT.md', 'INSTALL_AND_ROLLBACK.md',
                                       'install.sh', 'start_kiosk.sh', 'setup_kiosk_service.sh', 'init_display.sh') or
                               (rel.startswith('scripts/') and rel.endswith(('.py', '.sh'))) or
                               (rel.startswith('templates/') and rel.endswith('.html')) or
                               (rel.startswith('static/css/') and rel.endswith('.css')) or
                               (rel.startswith('static/js/') and rel.endswith('.js')) or
                               rel == 'static/data/football-teams-2026.json')
                    if not allowed:
                        continue
                    if rel in staged or member.file_size > 10 * 1024 * 1024:
                        raise ValueError('Duplicate or oversized update file')
                    target = os.path.join(APP_DIR, rel)
                    if os.path.commonpath((os.path.realpath(APP_DIR), os.path.realpath(target))) != os.path.realpath(APP_DIR):
                        raise ValueError('Update target escapes application directory')
                    staged[rel] = archive.read(member)
            if 'app.py' not in staged:
                raise ValueError('Update package is missing app.py')
            # Older allowlists silently omitted new root modules and left an
            # application that could no longer import at the next restart.
            program = ast.parse(staged['app.py'], filename='app.py')
            imported = {node.module for node in ast.walk(program)
                        if isinstance(node, ast.ImportFrom) and node.level == 0}
            imported.update(alias.name for node in ast.walk(program)
                            if isinstance(node, ast.Import) for alias in node.names)
            for module in ('score_details', 'cfb_week'):
                if module in imported and module + '.py' not in staged:
                    raise ValueError('Update package is missing required module: ' + module + '.py')
            for rel, data in staged.items():
                if rel.endswith('.py'):
                    ast.parse(data, filename=rel)
            requirements = os.path.join(APP_DIR, 'requirements.txt')
            if 'requirements.txt' in staged and os.path.exists(requirements):
                with open(requirements, 'rb') as handle:
                    if handle.read().strip() != staged['requirements.txt'].strip():
                        raise ValueError('Dependencies changed; use the reviewed installation guide')
            backup_dir = os.path.join(APP_DIR, '.update-backups')
            os.makedirs(backup_dir, mode=0o700, exist_ok=True)
            # Keep only the latest backup; the manual guide also keeps a full
            # pre-upgrade copy including device data before installation.
            backup = tempfile.mkdtemp(prefix='previous-', dir=backup_dir)
            previous = {}
            written = []
            try:
                for rel, data in staged.items():
                    target = os.path.join(APP_DIR, rel)
                    if os.path.exists(target):
                        saved = os.path.join(backup, rel)
                        os.makedirs(os.path.dirname(saved), exist_ok=True)
                        shutil.copy2(target, saved)
                        previous[rel] = saved
                    else:
                        previous[rel] = None
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    fd, staged_path = tempfile.mkstemp(prefix='.update-', dir=os.path.dirname(target))
                    try:
                        os.fchmod(fd, stat.S_IMODE(os.stat(target).st_mode) if os.path.exists(target)
                                  else (0o755 if rel.endswith('.sh') else 0o644))
                        with os.fdopen(fd, 'wb') as handle:
                            handle.write(data)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(staged_path, target)
                        written.append(rel)
                    finally:
                        if os.path.exists(staged_path):
                            os.unlink(staged_path)
            except Exception:
                for rel in reversed(written):
                    target = os.path.join(APP_DIR, rel)
                    if previous[rel]:
                        os.replace(previous[rel], target)
                    else:
                        os.unlink(target)
                raise
            for entry in os.listdir(backup_dir):
                old = os.path.join(backup_dir, entry)
                if old != backup and entry.startswith('previous-') and os.path.isdir(old):
                    shutil.rmtree(old)
            return True, 'Reviewed files installed; previous code retained at ' + backup
    except Exception as error:
        return False, str(error)


# ── Update API endpoints ──

@app.route('/api/update/version')
def update_version_endpoint():
    """Open endpoint — kiosks and remote servers call this to compare versions."""
    return jsonify({"version": _read_version()})


@app.route('/api/update/check')
def update_check():
    if not _valid_admin_session() and not _kiosk_token_ok(request):
        auth = request.authorization
        if not (auth and _authenticate_request(auth.username, auth.password)):
            return jsonify({"error": "Unauthorized"}), 401

    settings = get_settings()
    upd = settings.get('update', {})
    source_url = upd.get('source_url', '').strip()
    force = request.args.get('force') == '1'

    with _update_lock:
        state = dict(_update_state)

    age_h = (time_module.time() - (state.get('checked_at') or 0)) / 3600
    check_hours = float(upd.get('check_hours', 6))
    stale = not state.get('checked_at') or age_h > check_hours

    if source_url and (force or stale):
        rv, dl, err = _check_remote_version(source_url)
        now = time_module.time()
        with _update_lock:
            _update_state['checked_at'] = now
            _update_state['available'] = rv
            _update_state['download_url'] = dl
            if err:
                _update_state['last_result'] = 'error'
                _update_state['last_message'] = err
            else:
                current = _read_version()
                newer = bool(rv) and _parse_version(rv) > _parse_version(current)
                _update_state['last_result'] = 'ok'
                _update_state['last_message'] = (
                    f'Update available: {rv}' if newer else 'Up to date.'
                )
        with _update_lock:
            state = dict(_update_state)

    current = _read_version()
    available = state.get('available')
    update_available = bool(available) and _parse_version(available) > _parse_version(current)
    return jsonify({
        "current": current,
        "available": available,
        "update_available": update_available,
        "download_url": state.get('download_url'),
        "checked_at": state.get('checked_at'),
        "last_result": state.get('last_result'),
        "last_message": state.get('last_message'),
        "applying": state.get('applying', False),
    })


@app.route('/api/update/apply', methods=['POST'])
@require_admin
def update_apply():
    with _update_lock:
        if _update_state.get('applying'):
            return jsonify({"error": "Update already in progress"}), 409
        dl = _update_state.get('download_url', '')
        _update_state['applying'] = True

    cfg = get_kiosk_config()
    kiosk_token = cfg.get('auth_token', '')
    kiosk_id = cfg.get('kiosk_id', '')

    def _do_apply():
        ok, msg = _apply_update_package(dl, kiosk_token or None, kiosk_id or None)
        with _update_lock:
            _update_state['applying'] = False
            _update_state['last_result'] = 'ok' if ok else 'error'
            _update_state['last_message'] = msg
            if ok:
                _update_state['available'] = None  # Clear after successful apply
        if ok:
            subprocess.Popen(['bash', '-c', 'sleep 3 && sudo -n systemctl restart scoreboard.service'])

    threading.Thread(target=_do_apply, daemon=True).start()
    return jsonify({"status": "applying"})


@app.route('/api/update/package')
def update_package():
    """Serve the current app as a zip so kiosks can pull updates from this server."""
    if not _valid_admin_session() and not _kiosk_token_ok(request):
        auth = request.authorization
        if not (auth and _authenticate_request(auth.username, auth.password)):
            return jsonify({"error": "Unauthorized"}), 401

    version = _read_version()
    buf = io.BytesIO()
    include_files = ['app.py', 'score_details.py', 'cfb_week.py', 'version.txt', 'requirements.txt', 'LICENSE', 'README.md',
                     'QC_REPORT.md', 'INSTALL_AND_ROLLBACK.md', 'install.sh', 'start_kiosk.sh',
                     'setup_kiosk_service.sh', 'init_display.sh']
    include_dirs  = ['templates', os.path.join('static', 'css'),
                     os.path.join('static', 'js'), os.path.join('static', 'data'), 'scripts']

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fname in include_files:
            fpath = os.path.join(APP_DIR, fname)
            if os.path.exists(fpath):
                zf.write(fpath, fname)
        for dname in include_dirs:
            dpath = os.path.join(APP_DIR, dname)
            if os.path.isdir(dpath):
                for root, _, files in os.walk(dpath):
                    for fname in files:
                        full = os.path.join(root, fname)
                        rel  = os.path.relpath(full, APP_DIR)
                        if os.path.islink(full) or '__pycache__' in rel or (dname == 'scripts' and not fname.endswith(('.py', '.sh'))):
                            continue
                        zf.write(full, rel)

    buf.seek(0)
    return send_file(buf, mimetype='application/zip',
                     download_name=f'scoreboard-{version}.zip',
                     as_attachment=True)


# ─── BACKGROUND THREADS ───

def _schedule_loop():
    last_fired = {}
    last_heartbeat = 0
    last_update_check = 0
    while True:
        time_module.sleep(30)
        try:
            settings = get_settings()
            sched = settings.get('schedule', {})
            now_str = datetime.now().strftime('%H:%M')
            today = datetime.now().strftime('%Y-%m-%d')
            for action, disp_action in [('shutdown', 'off'), ('startup', 'on')]:
                conf = sched.get(action, {})
                if conf.get('enabled') and conf.get('time') == now_str:
                    fire_key = f"{today}_{now_str}"
                    if last_fired.get(action) != fire_key:
                        last_fired[action] = fire_key
                        _run_display_cmd(disp_action)
        except Exception as e:
            print(f"Schedule loop error: {e}")
        # Kiosk heartbeat
        try:
            settings = get_settings()
            if settings.get('device_mode') == 'kiosk':
                now_ts = time_module.time()
                if now_ts - last_heartbeat >= 60:
                    cfg = get_kiosk_config()
                    server_url = cfg.get('server_url', '').strip().rstrip('/')
                    kiosk_id = cfg.get('kiosk_id', '')
                    if server_url and kiosk_id and cfg.get('paired'):
                        last_heartbeat = now_ts
                        requests.post(f"{server_url}/api/kiosks/{kiosk_id}/heartbeat",
                                      headers={'X-Kiosk-Token': cfg.get('auth_token', ''),
                                               'X-Kiosk-Id': kiosk_id}, timeout=4)
        except Exception:
            pass
        # Auto update check
        try:
            settings = get_settings()
            upd = settings.get('update', {})
            source_url = upd.get('source_url', '').strip()
            if upd.get('auto_check') and source_url:
                check_hours = float(upd.get('check_hours', 6))
                now_ts = time_module.time()
                if now_ts - last_update_check >= check_hours * 3600:
                    last_update_check = now_ts
                    rv, dl, err = _check_remote_version(source_url)
                    with _update_lock:
                        _update_state['checked_at'] = now_ts
                        _update_state['available'] = rv
                        _update_state['download_url'] = dl
                        _update_state['last_result'] = 'error' if err else 'ok'
                        current = _read_version()
                        newer = bool(rv) and not err and _parse_version(rv) > _parse_version(current)
                        _update_state['last_message'] = (
                            err or (f'Update available: {rv}' if newer else 'Up to date.')
                        )
                    if newer and upd.get('auto_apply') and not err:
                        cfg = get_kiosk_config()
                        ok, msg = _apply_update_package(dl, cfg.get('auth_token') or None, cfg.get('kiosk_id') or None)
                        with _update_lock:
                            _update_state['last_result'] = 'ok' if ok else 'error'
                            _update_state['last_message'] = msg
                            if ok:
                                _update_state['available'] = None
                        if ok:
                            subprocess.Popen(['bash', '-c', 'sleep 3 && sudo -n systemctl restart scoreboard.service'])
        except Exception as e:
            print(f"Update check error: {e}")


def _has_live_games():
    with _cache_lock:
        for events in _espn_cache["raw_events"].values():
            for event in events:
                try:
                    if event['status']['type']['state'] == 'in':
                        return True
                except Exception:
                    pass
    return False


def _cache_refresh_loop():
    _load_score_snapshot()
    last_selection = None
    next_refresh = 0.0
    next_details_refresh = 0.0
    while True:
        settings = get_settings()
        with _cache_lock:
            requested = sorted((path, sorted(demand.get('windows', {})), bool(demand.get('complete_week')),
                                min(demand.get('refreshes', {}) or {900: 0})) if isinstance(demand, dict) else (path, [], False, 900)
                               for path, demand in _requested_leagues.items())
        selection = json.dumps([settings.get('leagues'), settings.get('football_priority'),
                                settings.get('date_windows'), settings.get('league_conferences'),
                                settings.get('score_refresh'), settings.get('cfb_coverage'), settings.get('cfb_refresh_seconds'), settings.get('timezone'),
                                _kiosk_server_unreachable, requested], sort_keys=True)
        now = time_module.monotonic()
        if selection != last_selection or now >= next_refresh:
            # A paired kiosk gets server data; its local cache is only needed
            # when no server exists or the data API has observed a server outage.
            refreshed = True
            if settings.get('device_mode') == 'server' or not get_kiosk_config().get('server_url') or _kiosk_server_unreachable:
                refreshed = _refresh_espn_cache()
                if refreshed:
                    _save_score_snapshot(force=selection != last_selection)
            last_selection = selection
            with _cache_lock:
                events = [event for slate in _espn_cache['raw_events'].values() for event in slate]
            delay = _events_refresh_interval(events, _refresh_preferences(settings)) if refreshed else 5
            if (cfb_week.CFB in _espn_cache['raw_events'] and
                    _complete_cfb_requested(settings)):
                delay = min(delay, _cfb_refresh_interval(settings))
            # Inspect failure backoff regularly; individual URLs enforce their
            # own retry time without re-requesting successful cached endpoints.
            if _cache_errors:
                delay = min(delay, 30)
            next_refresh = time_module.monotonic() + delay
        if now >= next_details_refresh:
            if settings.get('device_mode') == 'server' or not get_kiosk_config().get('server_url') or _kiosk_server_unreachable:
                # A global four-requests/minute ceiling supplements per-game
                # cache/backoff. Rendering only queues demand and never waits.
                if _score_details.refresh():
                    _save_score_snapshot()
            next_details_refresh = time_module.monotonic() + 30
        time_module.sleep(5)


if not (os.environ.get('WERKZEUG_RUN_MAIN') == 'false'):
    threading.Thread(target=_schedule_loop, daemon=True).start()
    threading.Thread(target=_cache_refresh_loop, daemon=True).start()


if __name__ == '__main__':
    _port = get_settings().get('port', 5000)
    app.run(host='0.0.0.0', port=_port, debug=False)
