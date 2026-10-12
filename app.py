import os, json, requests, subprocess, pytz, threading, time as time_module, uuid, random, string
import zipfile, io, shutil, tempfile
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, make_response
from datetime import datetime, timedelta, timezone
from functools import wraps
from dateutil import parser as dateutil_parser


app = Flask(__name__)
app.secret_key = 'scoreboard_internal_secure_key'
app.permanent_session_lifetime = timedelta(hours=1)

SETTINGS_FILE = 'settings.json'
KIOSK_CONFIG_FILE = 'kiosk.json'
KIOSKS_FILE = 'paired_kiosks.json'
APP_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(APP_DIR, 'version.txt')

_pairing_codes = {}  # code -> expiry (time.time())
_cache_lock = threading.Lock()
_espn_cache = {"raw_events": {}, "updated_at": None}  # raw_events: path -> [event, ...]
_update_lock = threading.Lock()
_update_state = {
    "available": None,
    "download_url": None,
    "checked_at": None,
    "applying": False,
    "last_result": None,
    "last_message": "",
}

UPLOAD_FOLDER = 'static/uploads'
SPECIALS_FOLDER = 'static/uploads/specials'
RSS_LOGOS_FOLDER = 'static/uploads/rss_logos'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SPECIALS_FOLDER, exist_ok=True)
os.makedirs(RSS_LOGOS_FOLDER, exist_ok=True)

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

HARDCODED_CONFERENCES = {
    "football/college-football": [
        {"id": "9",   "name": "SEC"},
        {"id": "1",   "name": "ACC"},
        {"id": "5",   "name": "Big Ten"},
        {"id": "4",   "name": "Big 12"},
        {"id": "21",  "name": "Pac-12"},
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

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized", "status": "unauthorized"}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user' in session:
            return f(*args, **kwargs)
        auth = request.authorization
        if auth and authenticate_linux_user(auth.username, auth.password):
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return wrapper


def authenticate_linux_user(username, password):
    settings = get_settings()
    creds = settings.get('admin_credentials', {})
    if creds.get('username') == username and creds.get('password') == password:
        return True
    try:
        process = subprocess.run(
            ['sudo', '-S', '-u', username, 'true'],
            input=f"{password}\n", text=True, capture_output=True, timeout=5,
        )
        return process.returncode == 0
    except Exception:
        return False


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


def get_settings():
    default = {
        "city": "Auburn, NE",
        "display_name": "Scoreboard",
        "header_color": "#F5A800",
        "leagues": ["football/nfl"],
        "teams": [],
        "league_conferences": {},
        "timezone": "America/Chicago",
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
        merged = {**default, **loaded}
        # Deep merge nested dicts so missing sub-keys fall back to defaults
        for key in ('update', 'colors', 'schedule', 'date_windows', 'local_schedule'):
            if key in default and isinstance(default[key], dict):
                merged[key] = {**default[key], **loaded.get(key, {})}
        return merged
    except Exception:
        return default


def save_settings(data):
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
    merged = {**existing, **data}
    # Deep-merge nested dicts — incoming data wins for any key it provides
    for key in ('update', 'colors', 'schedule', 'date_windows', 'local_schedule'):
        if isinstance(existing.get(key), dict) and isinstance(data.get(key), dict):
            merged[key] = {**existing[key], **data[key]}
    merged['last_saved'] = datetime.now(timezone.utc).isoformat()
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(merged, f, indent=2)


# ─── KIOSK CONFIG ───

def get_kiosk_config():
    default = {"server_url": "", "kiosk_id": "", "kiosk_name": "Kiosk", "paired": False, "auth_token": ""}
    if not os.path.exists(KIOSK_CONFIG_FILE):
        default['kiosk_id'] = uuid.uuid4().hex
        try:
            with open(KIOSK_CONFIG_FILE, 'w') as f:
                json.dump(default, f, indent=2)
        except Exception:
            pass
        return default
    try:
        cfg = {**default, **json.load(open(KIOSK_CONFIG_FILE))}
        if not cfg.get('kiosk_id'):
            cfg['kiosk_id'] = uuid.uuid4().hex
            save_kiosk_config(cfg)
        return cfg
    except Exception:
        return default


def save_kiosk_config(updates):
    try:
        existing = json.load(open(KIOSK_CONFIG_FILE)) if os.path.exists(KIOSK_CONFIG_FILE) else {}
    except Exception:
        existing = {}
    merged = {**existing, **updates}
    allowed = ('server_url', 'kiosk_id', 'kiosk_name', 'paired', 'auth_token')
    with open(KIOSK_CONFIG_FILE, 'w') as f:
        json.dump({k: merged[k] for k in allowed if k in merged}, f, indent=2)


# ─── KIOSK REGISTRY ───

def get_kiosks():
    if not os.path.exists(KIOSKS_FILE):
        return {}
    try:
        with open(KIOSKS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_kiosks(kiosks):
    with open(KIOSKS_FILE, 'w') as f:
        json.dump(kiosks, f, indent=2)


# ─── ESPN CACHE ───

_NASCAR_SCHEDULE_CACHE = {}  # year -> {race_id -> {race_name, race_date}}

def _fetch_nascar_com_events():
    """Fetch live NASCAR Cup race data from NASCAR.com and return ESPN-compatible event list."""
    live = requests.get('https://cf.nascar.com/cacher/live/live-feed.json', timeout=6,
                        headers={'User-Agent': 'Mozilla/5.0'}).json()
    vehicles = live.get('vehicles', [])
    if not vehicles:
        return []

    flag_state = live.get('flag_state', 0)
    lap = live.get('lap_number', 0)
    laps_in_race = live.get('laps_in_race', 0)
    race_id = live.get('race_id')

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
            sched = requests.get(f'https://cf.nascar.com/cacher/{year}/1/race_list_basic.json',
                                 timeout=5, headers={'User-Agent': 'Mozilla/5.0'}).json()
            _NASCAR_SCHEDULE_CACHE[year] = {
                r['race_id']: {'name': r.get('race_name', 'NASCAR Cup Race'),
                               'date': r.get('race_date') or r.get('date_scheduled', '')}
                for r in sched if 'race_id' in r
            }
        except Exception:
            _NASCAR_SCHEDULE_CACHE[year] = {}

    race_info = _NASCAR_SCHEDULE_CACHE.get(year, {}).get(race_id, {})
    race_name = race_info.get('name', 'NASCAR Cup Race')
    race_date_str = race_info.get('date', '') or datetime.now(timezone.utc).isoformat()

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
        'date': race_date_str,  # actual race date so date-window filtering works
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


def _fetch_league_raw(path, league_conferences, days_back=0, days_ahead=14):
    if path == "cricket/current":
        return _fetch_discovered_events("cricket", _discover_espn_series("cricket"))
    sport, league = ESPN_API_PATHS.get(path, (path.split('/')[0], path.split('/')[-1]))
    now = datetime.now()
    start = now - timedelta(days=days_back)
    end = now + timedelta(days=max(days_ahead, 1))
    base_host = "site.web.api.espn.com" if path in ESPN_WEB_API_LEAGUES else "site.api.espn.com"
    base_url = f"https://{base_host}/apis/site/v2/sports/{sport}/{league}/scoreboard"

    def _groups_param():
        conf_val = league_conferences.get(path, '')
        conf_id = ','.join(conf_val) if isinstance(conf_val, list) else conf_val
        return f"groups={conf_id}" if conf_id else ''

    def _to_events(resp):
        if not resp.ok:
            return []
        try:
            raw = resp.json().get('events', [])
        except Exception:
            raw = []
        return [e for e in raw
                if isinstance(e, dict) and e.get('competitions') and e.get('id')]

    events = []
    if path in ESPN_NO_DATE_LEAGUES:
        url = base_url
        qs = _groups_param()
        if qs:
            url += f"?{qs}"
        events = _to_events(requests.get(url, timeout=8))
        if not events and qs:
            events = _to_events(requests.get(base_url, timeout=8))
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
                    try:
                        resp = s.get(url, timeout=8)
                    except requests.RequestException:
                        day += timedelta(days=1)
                        continue
                    for e in _to_events(resp):
                        if e.get('id') not in seen:
                            seen.add(e.get('id'))
                            fetched.append(e)
                    day += timedelta(days=1)
            return fetched

        events = _fetch_range(True)
        if not events and _groups_param():
            # A stale/empty conference group filter can make ESPN return nothing
            # (or stray empty events); fall back to the unfiltered slate.
            events = _fetch_range(False)

    # Fall back to NASCAR.com live feed if ESPN has no data
    if not events and path == 'racing/nascar-cup':
        try:
            events = _fetch_nascar_com_events()
        except Exception as e:
            print(f"[cache] nascar.com fallback: {e}")

    try:
        return sorted(events, key=lambda e: e.get('date', ''))
    except Exception:
        return events


def _refresh_espn_cache():
    settings = get_settings()
    lc = settings.get('league_conferences', {})
    leagues = settings.get('leagues', [])
    dw = settings.get('date_windows', {})
    all_backs  = [v.get('days_back',  1) for v in dw.values() if isinstance(v, dict)]
    all_aheads = [v.get('days_ahead', 7) for v in dw.values() if isinstance(v, dict)]
    fetch_days_back  = max(all_backs,  default=1)
    fetch_days_ahead = max(all_aheads, default=7)
    refreshed = {}
    for path in leagues:
        try:
            refreshed[path] = _fetch_league_raw(path, lc, days_back=fetch_days_back, days_ahead=fetch_days_ahead)
        except Exception as e:
            print(f"[cache] {path}: {e}")
            with _cache_lock:
                old = _espn_cache["raw_events"].get(path)
            if old is not None:
                refreshed[path] = old
    with _cache_lock:
        _espn_cache["raw_events"].update(refreshed)
        _espn_cache["updated_at"] = datetime.now().isoformat()
    print(f"[cache] Refreshed {len(refreshed)} leagues")


def _get_league_events(path, league_conferences):
    with _cache_lock:
        cached = _espn_cache["raw_events"].get(path)
    if cached is not None:
        return cached
    try:
        events = _fetch_league_raw(path, league_conferences)
        with _cache_lock:
            _espn_cache["raw_events"][path] = events
        return events
    except Exception:
        return []


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
        local_dt = dateutil_parser.parse(utc_str).astimezone(tz)
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


def get_weather(city):
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


def _build_local_schedule_items(settings, tz_str):
    items = []
    ls = settings.get('local_schedule', {})
    global_keywords = _home_keywords(settings)
    for entry in ls.get('items', []):
        if not entry.get('enabled', True):
            continue
        date_raw = entry.get('date', '')
        time_raw = entry.get('time', '')
        event_iso = ''
        if date_raw:
            try:
                parsed = dateutil_parser.parse(f"{date_raw} {time_raw}".strip())
                event_iso = parsed.isoformat()
            except Exception:
                pass
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
            'date': date_raw,
            'time': time_raw,
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
        pre_count = len(items)
        try:
            resolved_url, feed_type = _resolve_feed(rss_url)
            if feed_type == 'thrillshare':
                _parse_thrillshare_feed(resolved_url, rss_label, rss_logo, items, tz_str)
            elif feed_type == 'rss':
                _parse_rss_feed(resolved_url, rss_label, rss_logo, items)
            elif feed_type == 'ical':
                _parse_ical_feed(resolved_url, rss_label, rss_logo, items, tz_str)
            elif feed_type == 'maxpreps':
                _parse_maxpreps_feed(resolved_url, rss_label, rss_logo, items, tz_str)
            else:
                print(f"[schedule] Could not detect feed type for: {rss_url}")
        except Exception as e:
            print(f"[schedule] Feed error ({rss_label}): {e}")
        for item in items[pre_count:]:
            item['tag'] = rss_tag
            _apply_matchup_split(item, feed_keywords)
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


def _parse_rss_feed(url, label, logo, out):
    res = requests.get(url, timeout=5)
    root = _ET.fromstring(res.content)
    channel = root.find('channel') or root
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
                date_str = dt.strftime('%a %b %-d')
                time_str = dt.strftime('%-I:%M %p')
                event_iso = dt.isoformat()
            except Exception:
                pass
        out.append({'type': 'rss', 'label': label, 'logo': logo,
                    'title': title, 'body': description[:120], 'date': date_str, 'time': time_str,
                    'event_iso': event_iso})


def _parse_ical_feed(url, label, logo, out, tz_str='America/Chicago'):
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.utc
    now_local = datetime.now(tz)
    # Show today's events (or yesterday's if before 11 AM), up to 7 days out
    if now_local.hour < 11:
        min_dt = tz.localize(datetime(now_local.year, now_local.month, now_local.day)) - timedelta(days=1)
    else:
        min_dt = tz.localize(datetime(now_local.year, now_local.month, now_local.day))
    max_dt = min_dt + timedelta(days=3)

    res = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
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
                            event_dt = tz.localize(naive) if not dtstart.endswith('Z') else pytz.utc.localize(naive).astimezone(tz)
                        else:
                            naive = datetime.strptime(dtstart, '%Y%m%d')
                            event_dt = tz.localize(naive)
                        date_str = event_dt.strftime('%a %b %-d')
                        if 'T' in dtstart:
                            time_str = event_dt.strftime('%-I:%M %p')
                    except Exception:
                        pass
                # Skip events outside the window
                if event_dt is not None and not (min_dt <= event_dt < max_dt):
                    event = {}
                    continue
                out.append({'type': 'rss', 'label': label, 'logo': logo,
                            'title': title, 'body': event.get('location', ''),
                            'date': date_str, 'time': time_str,
                            'event_iso': event_dt.isoformat() if event_dt else ''})
                count += 1
                if count >= 20:
                    break
            event = {}
        elif ':' in line:
            key, _, val = line.partition(':')
            key_base = key.split(';')[0].lower().strip()
            if key_base in ('summary', 'dtstart', 'location', 'description'):
                # Preserve the full key (including TZID params) for dtstart
                store_key = 'dtstart' if key_base == 'dtstart' else key_base
                event[store_key] = (key.strip() + ':' + val).partition(':')[2].strip().replace('\\n', ' ').replace('\\,', ',')


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
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>({.*?})</script', res.text, re.S)
    if not m:
        print(f"[maxpreps] No __NEXT_DATA__ found at {url}")
        return
    data = json.loads(m.group(1))
    contests = data.get('props', {}).get('pageProps', {}).get('initSchoolContests', [])

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
        except Exception:
            pass
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
    data = res.json()
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

    now = datetime.now()
    try:
        local_now = now.astimezone(pytz.timezone(tz_str))
        today_local = local_now.date()
    except Exception:
        today_local = now.date()

    dw = settings.get('date_windows', {})

    def _get_window(path):
        entry = dw.get(path, {})
        if path in MOTORSPORTS_LEAGUES:
            return entry.get('days_back', 1), entry.get('days_ahead', 2)
        if path in GOLF_LEAGUES:
            return entry.get('days_back', 1), entry.get('days_ahead', 7)
        return entry.get('days_back', 1), entry.get('days_ahead', 7)

    for path in active_leagues:
        try:
            events = _get_league_events(path, active_lc)
            sport, league = ESPN_API_PATHS.get(path, (path.split('/')[0], path.split('/')[-1]))

            # ── Motorsports (NASCAR / IndyCar / F1) — leaderboard + ticker on race day ──
            if path in MOTORSPORTS_LEAGUES:
                fav_key = MOTORSPORTS_FAV_KEY.get(path, 'nascar_favorites')
                motor_favs = [n.strip().lower() for n in settings.get(fav_key, []) if n.strip()]
                league_label = LEAGUE_LABELS.get(path, 'RACING')
                for event in events:
                    try:
                        state = event['status']['type']['state']
                        status_detail = event['status']['type']['shortDetail']
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
                        state = event['status']['type']['state']
                        status_detail = event['status']['type']['shortDetail']
                        try:
                            event_local_date = dateutil_parser.parse(event['date']).astimezone(pytz.timezone(tz_str)).date()
                            g_back, g_ahead = _get_window(path)
                            golf_min = today_local - timedelta(days=g_back)
                            golf_max = today_local + timedelta(days=g_ahead)
                            in_window = (golf_min <= event_local_date <= golf_max)
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

            for event in events:
                try:
                    comp_list = event.get('competitions') or []
                    if not comp_list or not comp_list[0].get('competitors'):
                        continue
                    comp = comp_list[0]
                    competitors = comp['competitors']
                    home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
                    away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[-1])
                    h_abbr = home['team'].get('abbreviation') or home['team'].get('shortDisplayName') or home['team'].get('displayName', '?')
                    a_abbr = away['team'].get('abbreviation') or away['team'].get('shortDisplayName') or away['team'].get('displayName', '?')
                    h_score = home.get('score', '0') or '0'
                    a_score = away.get('score', '0') or '0'
                    state = event['status']['type']['state']
                    status_detail = event['status']['type']['shortDetail']
                    dt_info = format_local_datetime(event['date'], tz_str)
                    l_time_str = f"{dt_info['date']}  {dt_info['time']}".strip()

                    try:
                        event_local_date = dateutil_parser.parse(event['date']).astimezone(pytz.timezone(tz_str)).date()
                        is_today = (event_local_date == today_local)
                    except Exception:
                        is_today = True

                    if state == 'pre':
                        tick_text = f"{a_abbr} @ {h_abbr} | {l_time_str or status_detail}"
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
                        tick_text = f"{a_abbr} {a_score}  {h_abbr} {h_score}  F"
                        color_state = 'final'
                        try:
                            as_int, hs_int = int(a_score), int(h_score)
                            winner = 'away' if as_int > hs_int else ('home' if hs_int > as_int else 'tie')
                        except Exception:
                            winner = None

                    if is_today:
                        league_games.append({
                            "text": tick_text, "color_state": color_state,
                            "away": a_abbr, "home": h_abbr,
                            "away_score": a_score, "home_score": h_score, "winner": winner,
                        })

                    away_is_fav = f"{path.lower()}:{a_abbr.upper()}" in fav_set
                    home_is_fav = f"{path.lower()}:{h_abbr.upper()}" in fav_set
                    is_fav = away_is_fav or home_is_fav
                    game_key = f"{path}:{a_abbr}@{h_abbr}"
                    t_back, t_ahead = _get_window(path)
                    team_min = today_local - timedelta(days=t_back)
                    team_max = today_local + timedelta(days=t_ahead)
                    if is_fav and (team_min <= event_local_date <= team_max) and game_key not in fav_card_keys:
                        fav_card_keys.add(game_key)
                        fav_cards.append({
                            "league_path": path,
                            "league_label": LEAGUE_LABELS.get(path, league.upper()),
                            "home_name": h_abbr, "away_name": a_abbr,
                            "home_score": h_score, "away_score": a_score,
                            "home_logo": home['team'].get('logo', ''),
                            "away_logo": away['team'].get('logo', ''),
                            "status": status_detail, "local_time": l_time_str,
                            "is_pre": state == 'pre', "color_state": color_state,
                            "winner": winner,
                            "away_record": (_espn_record(away) if state == 'pre' else ''),
                            "home_record": (_espn_record(home) if state == 'pre' else ''),
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

    specials = [
        s for s in settings.get('specials', [])
        if s.get('enabled') and (s.get('title') or s.get('image')) and _special_active_today(s, tz_str)
    ]

    colors, header_color = resolve_palette(settings)

    return {
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
        "slide_playlist": settings.get('slide_playlist', []),
        "slide_duration": settings.get('slide_duration', 8),
        "slide_transition": settings.get('slide_transition', 'slide-right'),
        "ticker_speed": settings.get('ticker_speed', 120),
        "cache_updated_at": _espn_cache.get("updated_at"),
        "settings_updated_at": settings.get('last_saved', ''),
        "app_version": _read_version(),
    }


# ─── ROUTES: WEB UI ───

@app.route('/')
def index():
    settings = get_settings()
    if settings.get('device_mode') == 'server' and not settings.get('server_enable_display', True):
        return redirect(url_for('settings_page'))
    resp = make_response(render_template('index.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.after_request
def _no_cache_headers(resp):
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if authenticate_linux_user(username, password):
            session.permanent = True
            session['user'] = username
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
    if authenticate_linux_user(data.get('username', ''), data.get('password', '')):
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 401


@app.route('/api/settings', methods=['GET', 'POST'])
def settings_api():
    if request.method == 'POST':
        if 'user' not in session:
            auth = request.authorization
            if not auth or not authenticate_linux_user(auth.username, auth.password):
                return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        kiosk_updates = {}
        for field in ('server_url', 'kiosk_name', 'auth_token'):
            if field in data:
                kiosk_updates[field] = data.pop(field)
        if kiosk_updates:
            save_kiosk_config(kiosk_updates)
        save_settings(data)
        return jsonify({"status": "ok"})
    s = get_settings()
    cfg = get_kiosk_config()
    s['server_url'] = cfg.get('server_url', '')
    s['kiosk_name'] = cfg.get('kiosk_name', 'Kiosk')
    s['paired'] = cfg.get('paired', False)
    s['kiosk_id'] = cfg.get('kiosk_id', '')
    return jsonify(s)


@app.route('/api/upload_special_image', methods=['POST'])
@require_admin
def upload_special_image():
    if 'image' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files['image']
    if not file.filename:
        return jsonify({"error": "No file"}), 400
    ext = os.path.splitext(file.filename)[1] or '.png'
    filename = f"{uuid.uuid4().hex}{ext}"
    file.save(os.path.join(SPECIALS_FOLDER, filename))
    return jsonify({"url": f"/static/uploads/specials/{filename}"})


@app.route('/api/upload_rss_logo', methods=['POST'])
@require_admin
def upload_rss_logo():
    if 'logo' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files['logo']
    if not file.filename:
        return jsonify({"error": "No file"}), 400
    ext = os.path.splitext(file.filename)[1] or '.png'
    filename = f"{uuid.uuid4().hex}{ext}"
    file.save(os.path.join(RSS_LOGOS_FOLDER, filename))
    return jsonify({"url": f"/static/uploads/rss_logos/{filename}"})


@app.route('/api/upload_logo', methods=['POST'])
@require_admin
def upload_logo():
    if 'logo' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files['logo']
    if file.filename:
        file.save(os.path.join(UPLOAD_FOLDER, 'logo.png'))
    return jsonify({"status": "ok"})


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
                    return jsonify(r.json())
            except Exception:
                pass

    sport, league = ESPN_API_PATHS.get(league_path, (
        league_path.split('/')[0], league_path.split('/')[-1],
    ))
    base_host = "site.web.api.espn.com" if league_path in ESPN_WEB_API_LEAGUES else "site.api.espn.com"
    try:
        res = requests.get(
            f"https://{base_host}/apis/site/v2/sports/{sport}/{league}/teams?limit=500",
            timeout=5,
        ).json()
        teams = res['sports'][0]['leagues'][0]['teams']
        return jsonify([
            {
                "abbr":  t['team']['abbreviation'],
                "name":  t['team']['displayName'],
                "logo":  (t['team'].get('logos') or [{}])[0].get('href', ''),
                "color": t['team'].get('color', ''),
            }
            for t in teams
            if t['team'].get('abbreviation') and t['team'].get('displayName')
        ])
    except Exception:
        return jsonify([])


@app.route('/api/conferences/<path:league_path>')
def conferences_api(league_path):
    if league_path in HARDCODED_CONFERENCES:
        return jsonify(HARDCODED_CONFERENCES[league_path])
    return jsonify([])


@app.route('/api/data', methods=['GET', 'POST'])
def data_api():
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
                }
                r = requests.post(f"{server_url}/api/data", json=payload, timeout=10)
                if r.ok:
                    data = r.json()
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
                    data['specials']         = [
                        s for s in settings.get('specials', [])
                        if s.get('enabled') and (s.get('title') or s.get('image'))
                        and _special_active_today(s, tz_str)
                    ]
                    if settings.get('city'):
                        data['weather'] = get_weather(settings['city'])
                    data['local_schedule_items'] = _build_local_schedule_items(settings, tz_str)
                    return jsonify(data)
            except Exception:
                pass
        # Fall through to standalone if server is unreachable

    # Server mode (or kiosk fallback to direct ESPN)
    req_data = {}
    if request.method == 'POST':
        req_data = request.get_json(silent=True) or {}

    active_leagues = req_data['leagues'] if req_data.get('leagues') is not None else settings.get('leagues', [])
    active_teams   = req_data['teams']   if req_data.get('teams')   is not None else settings.get('teams', [])
    active_lc      = req_data.get('league_conferences') or settings.get('league_conferences', {})
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
        subprocess.Popen(['bash', '-c', 'sleep 1 && sudo systemctl restart scoreboard.service'])
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


# Run a command, retrying with sudo when it fails without privileges.
def _run(cmd, timeout=20):
    last = None
    for prefix in ([], ['sudo']):
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
            # control socket. Requires NOPASSWD sudoers entry for wpa_cli.
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
    ssid = data.get('ssid', '').strip()
    password = data.get('password', '').strip()
    if not ssid:
        return jsonify({'ok': False, 'error': 'SSID required'}), 400
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
            def _wpa(args, **kw):
                # Try without sudo first (works if user is in netdev group),
                # then fall back to sudo using the existing sudoers entry.
                for prefix in ([], ['sudo']):
                    r = subprocess.run(prefix + ['wpa_cli', '-i', iface] + args,
                                       capture_output=True, text=True, timeout=10, **kw)
                    if r.returncode == 0:
                        return r
                return r  # return last attempt even if failed

            # Add a new network slot
            r = _wpa(['add_network'])
            net_id = r.stdout.strip().split('\n')[-1].strip()
            if not net_id.isdigit():
                return jsonify({'ok': False, 'error': f'wpa_cli add_network failed: {r.stderr.strip() or r.stdout.strip()}'})

            # Configure the network
            _wpa(['set_network', net_id, 'ssid', f'"{ssid}"'])
            if password:
                _wpa(['set_network', net_id, 'psk', f'"{password}"'])
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
            for prefix in ([], ['sudo']):
                r = subprocess.run(prefix + ['wpa_cli', '-i', iface] + args,
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    return r
            return r

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
    for prefix in ([], ['sudo']):
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
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    _pairing_codes[code] = now + 600
    return jsonify({"code": code, "expires_in": 600})


@app.route('/api/pairing/claim', methods=['POST'])
def pairing_claim():
    data = request.get_json(silent=True) or {}
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
def kiosk_unpair(kiosk_id):
    kiosks = get_kiosks()
    kiosks.pop(kiosk_id, None)
    save_kiosks(kiosks)
    return jsonify({"ok": True})


@app.route('/api/kiosks/<kiosk_id>/heartbeat', methods=['POST'])
def kiosk_heartbeat(kiosk_id):
    kiosks = get_kiosks()
    if kiosk_id not in kiosks:
        return jsonify({"ok": False, "error": "Unknown kiosk"}), 404
    kiosks[kiosk_id]['last_seen'] = datetime.now(timezone.utc).isoformat()
    kiosks[kiosk_id]['ip'] = request.remote_addr
    data = request.get_json(silent=True) or {}
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


def _kiosk_token_ok(req):
    """Return True if the request carries a valid kiosk auth token or paired kiosk ID."""
    token = req.headers.get('X-Kiosk-Token') or req.args.get('kiosk_token')
    kiosk_id = req.headers.get('X-Kiosk-Id') or req.args.get('kiosk_id')
    kiosks = get_kiosks()
    if token and any(k.get('auth_token') == token for k in kiosks.values()):
        return True
    if kiosk_id and kiosk_id in kiosks:
        return True
    return False


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
                    dl = source_url.rstrip('/api/update/version').rstrip('/') + '/api/update/package'
                    return data['version'], dl, None

        # Generic JSON endpoint
        r = requests.get(source_url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get('version', ''), data.get('download_url', ''), None
    except Exception as e:
        return None, None, str(e)


def _apply_update_package(download_url, kiosk_token=None, kiosk_id=None):
    """
    Apply an update from download_url (a zip file).
    Falls back to git pull if the app lives in a git repo.
    Returns (ok: bool, message: str).
    """
    # Try git pull first when a .git directory exists
    if os.path.isdir(os.path.join(APP_DIR, '.git')):
        try:
            result = subprocess.run(
                ['git', '-C', APP_DIR, 'pull', '--rebase'],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                return True, 'git pull succeeded: ' + result.stdout.strip()
        except Exception:
            pass  # Fall through to package download

    if not download_url:
        return False, 'No download URL provided and git pull is unavailable.'

    try:
        headers = {}
        if kiosk_token:
            headers['X-Kiosk-Token'] = kiosk_token
        if kiosk_id:
            headers['X-Kiosk-Id'] = kiosk_id
        r = requests.get(download_url, headers=headers, timeout=120, stream=True)
        r.raise_for_status()

        tmp = tempfile.mkdtemp()
        try:
            pkg = os.path.join(tmp, 'update.zip')
            with open(pkg, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)

            # Snapshot user-data files before extraction so they survive no matter what
            _PRESERVE_FILES = ['settings.json', 'kiosk.json', 'paired_kiosks.json']
            _snapshots = {}
            for fname in _PRESERVE_FILES:
                fpath = os.path.join(APP_DIR, fname)
                if os.path.exists(fpath):
                    with open(fpath, 'rb') as _f:
                        _snapshots[fname] = _f.read()

            with zipfile.ZipFile(pkg) as zf:
                names = zf.namelist()
                # Strip common top-level folder (GitHub zips include one)
                prefix = os.path.commonprefix(names).rstrip('/')
                for member in zf.infolist():
                    rel = member.filename
                    if prefix and rel.startswith(prefix + '/'):
                        rel = rel[len(prefix) + 1:]
                    if not rel:
                        continue
                    # Skip uploaded assets — never replace user media
                    if rel.startswith('static/uploads/'):
                        continue
                    target = os.path.join(APP_DIR, rel)
                    if member.is_dir():
                        os.makedirs(target, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(member) as src, open(target, 'wb') as dst:
                            shutil.copyfileobj(src, dst)

            # Restore user-data files unconditionally — overrides anything extracted
            for fname, data in _snapshots.items():
                fpath = os.path.join(APP_DIR, fname)
                with open(fpath, 'wb') as _f:
                    _f.write(data)

            return True, 'Package extracted successfully.'
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        return False, str(e)


# ── Update API endpoints ──

@app.route('/api/update/version')
def update_version_endpoint():
    """Open endpoint — kiosks and remote servers call this to compare versions."""
    return jsonify({"version": _read_version()})


@app.route('/api/update/check')
def update_check():
    if 'user' not in session and not _kiosk_token_ok(request):
        auth = request.authorization
        if not (auth and authenticate_linux_user(auth.username, auth.password)):
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
            subprocess.Popen(['bash', '-c', 'sleep 3 && sudo systemctl reboot'])

    threading.Thread(target=_do_apply, daemon=True).start()
    return jsonify({"status": "applying"})


@app.route('/api/update/package')
def update_package():
    """Serve the current app as a zip so kiosks can pull updates from this server."""
    if 'user' not in session and not _kiosk_token_ok(request):
        auth = request.authorization
        if not (auth and authenticate_linux_user(auth.username, auth.password)):
            return jsonify({"error": "Unauthorized"}), 401

    version = _read_version()
    buf = io.BytesIO()
    include_files = ['app.py', 'version.txt', 'requirements.txt']
    include_dirs  = ['templates', os.path.join('static', 'css'),
                     os.path.join('static', 'js')]

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
                        requests.post(f"{server_url}/api/kiosks/{kiosk_id}/heartbeat", timeout=4)
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
                            subprocess.Popen(['bash', '-c', 'sleep 3 && sudo systemctl reboot'])
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
    # Initial fetch on startup
    try:
        settings = get_settings()
        if settings.get('device_mode') == 'server':
            _refresh_espn_cache()
    except Exception as e:
        print(f"Initial cache refresh error: {e}")
    while True:
        # 30 s when games are live, 5 min otherwise
        interval = 30 if _has_live_games() else 5 * 60
        time_module.sleep(interval)
        try:
            settings = get_settings()
            if settings.get('device_mode') == 'server':
                _refresh_espn_cache()
        except Exception as e:
            print(f"Cache refresh loop error: {e}")


if not (os.environ.get('WERKZEUG_RUN_MAIN') == 'false'):
    threading.Thread(target=_schedule_loop, daemon=True).start()
    threading.Thread(target=_cache_refresh_loop, daemon=True).start()


if __name__ == '__main__':
    _port = get_settings().get('port', 5000)
    app.run(host='0.0.0.0', port=_port, debug=False)
