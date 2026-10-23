#!/bin/bash
# install.sh — Gameday Scoreboard Installer
#
# Single installer for server, kiosk, or combined (all-in-one) deployments.
# Creates every folder and file the app needs, installs a browser (preferring
# Google Chrome on x86_64, else a distro-appropriate Chromium), and disables
# whatever desktop manager is currently running so the kiosk boots straight
# into the scoreboard.
#
# OPTIONAL — x86_64 kiosk/combined installs:
#   For Google Chrome, place the .deb next to this script before running:
#     https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
#   If Chrome is not found, the installer falls back to a distro-appropriate
#   Chromium automatically (Debian/Ubuntu/Raspbian use apt; indices that no
#   longer ship Chromium fall back to Google's Chromium .deb on x86_64).
#   ARM systems (Raspberry Pi, etc.) always use Chromium via the distro.
#
# Run with: sudo ./install.sh

set -e

# Rendering a unit is read-only and is used by development tests. It never
# installs packages, touches systemd, or requires root.
render_backend_unit() {
    local app_user="$1" app_dir="$2" app_home="$3"
    [[ "$app_user" =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || return 1
    [[ "$app_dir" == /* && "$app_home" == /* && "$app_dir$app_home" != *$'\n'* && "$app_dir$app_home" != *'"'* && "$app_dir$app_home" != *'\'* ]] || return 1
    # The full installer validates paths; quote systemd values as one argument.
    app_dir="${app_dir//%/%%}"
    app_home="${app_home//%/%%}"
    cat <<EOF
[Unit]
Description=Gameday Scoreboard Backend
After=network.target
# A local/offline display must not wait for Internet connectivity.
StartLimitIntervalSec=0

[Service]
Type=simple
User=$app_user
WorkingDirectory=$app_dir
Environment="HOME=$app_home"
ExecStart=/usr/bin/python3 "$app_dir/app.py"
Restart=always
RestartSec=10
TimeoutStopSec=20
Environment=PYTHONUNBUFFERED=1
Environment=DISPLAY=:0
Environment="XAUTHORITY=$app_home/.Xauthority"
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
}

if [[ "${1:-}" == --render-backend-unit ]]; then
    [[ $# -eq 4 ]] || exit 2
    render_backend_unit "$2" "$3" "$4"
    exit
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# ─── ROOT CHECK ───────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root:  sudo ./install.sh"
    exit 1
fi

# ─── BANNER ──────────────────────────────────────────────────────────────────
echo ""
echo "======================================================="
echo "   Gameday Scoreboard — Installer"
echo "======================================================="
echo ""

# ─── INSTALL MODE ─────────────────────────────────────────────────────────────
echo "  What are you installing on this machine?"
echo ""
echo "  [1] Server   — headless data backend (port 5000, no display)"
echo "                 Other kiosk TVs point to this machine."
echo ""
echo "  [2] Kiosk    — display client (port 5001)"
echo "                 Pairs with a remote server, or runs standalone."
echo ""
echo "  [3] Combined — server + display on one machine (port 5000)"
echo "                 Simplest single-TV all-in-one setup."
echo ""
read -rp "  Enter choice [1/2/3]: " _choice
case "$_choice" in
    1) MODE="server"   ;;
    2) MODE="kiosk"    ;;
    3) MODE="combined" ;;
    *) echo "Invalid choice. Exiting."; exit 1 ;;
esac
echo ""

# ─── USERNAME ────────────────────────────────────────────────────────────────
DEFAULT_APP_USER="${SUDO_USER:-scoreboard}"
[[ "$DEFAULT_APP_USER" != root ]] || DEFAULT_APP_USER=scoreboard
read -rp "Enter the regular username to install under [default: $DEFAULT_APP_USER]: " APP_USER
APP_USER="${APP_USER:-$DEFAULT_APP_USER}"
[[ "$APP_USER" =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || { echo "ERROR: Invalid username."; exit 1; }
if [[ "$APP_USER" == root && "$MODE" != server ]]; then
    echo "ERROR: Chromium must run as a regular desktop user with its sandbox enabled."
    exit 1
fi
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
APP_HOME="${APP_HOME:-/home/$APP_USER}"
APP_DIR="${APP_DIR:-$APP_HOME/scoreboard}"
case "$APP_DIR" in
    /|/home|/root|/usr|/etc|/var|"$APP_HOME") echo "ERROR: Choose a dedicated scoreboard directory."; exit 1 ;;
esac
[[ "$APP_DIR" == /* && "$APP_DIR$APP_HOME" != *$'\n'* && "$APP_DIR$APP_HOME" != *'"'* && "$APP_DIR$APP_HOME" != *'\'* ]] || { echo "ERROR: Invalid installation path."; exit 1; }
for required in app.py score_details.py cfb_week.py start_kiosk.sh setup_kiosk_service.sh templates/index.html templates/login.html templates/settings.html static/css/main.css static/js/clock.js static/js/display.js static/css/display-modes.css static/data/football-teams-2026.json scripts/network_helper.py LICENSE; do
    [[ -f "$SCRIPT_DIR/$required" ]] || { echo "ERROR: Missing required source: $required"; exit 1; }
done

# The app is delivered as a single app.py that detects server vs kiosk from
# settings.json / kiosk.json at runtime, so there is one source file regardless
# of mode. Ports differ only by displayed URL.
if [[ "$MODE" == "kiosk" ]]; then
    APP_SRC="app.py"
    DISPLAY_PORT=5001
else
    APP_SRC="app.py"
    DISPLAY_PORT=5000
fi

echo ""
echo "  Mode        : $MODE"
echo "  User        : $APP_USER"
echo "  Install dir : $APP_DIR"
echo "  Source dir  : $SCRIPT_DIR"
echo "  App file    : $APP_SRC → app.py"
[[ "$MODE" != "server" ]] && echo "  Browser URL : http://localhost:$DISPLAY_PORT"
echo "-------------------------------------------------------"
echo ""

# ─── KIOSK SERVER URL (kiosk mode only) ──────────────────────────────────────
if [[ "$MODE" == "kiosk" ]]; then
    echo "  This kiosk will proxy to a remote scoreboard server."
    read -rp "  Remote server URL [default: http://localhost:5000]: " KIOSK_SERVER_URL
    KIOSK_SERVER_URL="${KIOSK_SERVER_URL:-http://localhost:5000}"
    echo ""
fi

# ─── DETECT DISTRO (all modes) ────────────────────────────────────────────────
# Needed for the system-packages section regardless of mode.
ARCH=$(uname -m)
if [ -r /etc/os-release ]; then
    . /etc/os-release
    DISTRO_ID="${ID:-unknown}"
    DISTRO_FAMILY=""
    case "$DISTRO_ID" in
        debian|ubuntu|raspbian|linuxmint|elementary|pop) DISTRO_FAMILY="debian" ;;
        fedora|centos|rhel|rocky|almalinux)              DISTRO_FAMILY="fedora" ;;
        arch|manjaro|endeavouros)                        DISTRO_FAMILY="arch"   ;;
        opensuse*|suse)                                  DISTRO_FAMILY="suse"   ;;
        *)                                               DISTRO_FAMILY="debian" ;;
    esac
else
    DISTRO_ID="unknown"
    DISTRO_FAMILY="debian"
fi
echo "Architecture : $ARCH"
echo "Distro       : $DISTRO_ID (family: $DISTRO_FAMILY)"
echo ""

# ─── DETECT BROWSER (kiosk/combined only) ─────────────────────────────────────
if [[ "$MODE" == "kiosk" || "$MODE" == "combined" ]]; then
    BROWSER_TYPE=""
    BROWSER_BIN=""
    # x86_64 → prefer Google Chrome (real browser, no sandbox flags needed).
    # Otherwise use the distro Chromium.
    if [[ "$DISTRO_FAMILY" == debian && ( "$ARCH" == x86_64 || "$ARCH" == amd64 ) ]]; then
        BROWSER_TYPE="chrome"
        BROWSER_BIN="google-chrome"
        CHROME_DEB="$SCRIPT_DIR/google-chrome-stable_current_amd64.deb"
    else
        BROWSER_TYPE="chromium"
        BROWSER_BIN=""
    fi
fi

# ─── CREATE USER ─────────────────────────────────────────────────────────────
echo "--- User Setup ---"
if id "$APP_USER" &>/dev/null; then
    echo "User '$APP_USER' already exists — skipping creation."
else
    useradd -m -d "$APP_HOME" -s /bin/bash "$APP_USER"
    echo "Created user '$APP_USER'. Set a password:"
    passwd "$APP_USER"
fi

# Back up an existing application before replacing code. This is a safety net;
# upgrades should still use the selective migration guide on a cloned SD card.
if [[ -f "$APP_DIR/app.py" ]]; then
    BACKUP_PATH="${APP_DIR}.backup-$(date +%Y%m%d%H%M%S).tar.gz"
    tar -czf "$BACKUP_PATH" -C "$APP_DIR" .
    chmod 600 "$BACKUP_PATH"
    echo "Application backup: $BACKUP_PATH"
fi

APP_GROUP="$(id -gn "$APP_USER")"
# Older 32-bit Pi OS images may not define a render group. Add only groups
# that exist, while LightDM/logind supplies normal session/device access.
if [[ "$MODE" == kiosk || "$MODE" == combined ]]; then
    for display_group in video render; do
        if getent group "$display_group" >/dev/null; then
            usermod -aG "$display_group" "$APP_USER"
        fi
    done
fi
echo ""

# ─── SYSTEM PACKAGES ─────────────────────────────────────────────────────────
echo "--- Installing System Packages ---"

case "$DISTRO_FAMILY" in
    debian)
        apt-get update -q
        # Leave unrelated web servers and network configuration intact.
        # Python backend — all modes
        apt-get install -y \
            python3 \
            python3-flask \
            python3-requests \
            python3-pytz \
            python3-dateutil \
            python3-pip \
            curl \
            wget \
            iproute2 \
            wireless-tools \
            wpasupplicant \
            iw

        # Display environment — kiosk and combined only
        if [[ "$MODE" == "kiosk" || "$MODE" == "combined" ]]; then
            apt-get install -y \
                unclutter \
                xorg \
                xserver-xorg \
                x11-xserver-utils \
                lightdm \
                openbox
        fi
        ;;
    fedora)
        dnf install -y \
            python3 python3-flask python3-requests python3-pytz \
            python3-dateutil python3-pip curl wget iproute \
            wireless-tools wpa_supplicant iw 2>/dev/null \
            || yum install -y python3 python3-flask python3-requests \
               python3-pytz python3-dateutil python3-pip curl wget iproute \
               wireless-tools wpa_supplicant iw
        if [[ "$MODE" == "kiosk" || "$MODE" == "combined" ]]; then
            dnf install -y unclutter xorg-x11-server-Xorg \
                xorg-x11-server-utils lightdm openbox 2>/dev/null \
                || yum install -y unclutter xorg-x11-server-Xorg \
                   xorg-x11-server-utils lightdm openbox
        fi
        ;;
    arch)
        pacman -Sy --noconfirm \
            python python-flask python-requests python-pytz \
            python-dateutil python-pip curl wget iproute2 \
            wireless_tools wpa_supplicant iw
        if [[ "$MODE" == "kiosk" || "$MODE" == "combined" ]]; then
            pacman -S --noconfirm unclutter xorg-server xorg-xinit \
                lightdm openbox
        fi
        ;;
    suse)
        zypper --non-interactive install \
            python3 python3-Flask python3-requests python3-pytz \
            python3-dateutil python3-pip curl wget iproute2 \
            wireless-tools wpa_supplicant iw
        if [[ "$MODE" == "kiosk" || "$MODE" == "combined" ]]; then
            zypper --non-interactive install unclutter xorg-x11-server \
                xorg-x11-utils lightdm openbox
        fi
        ;;
    *) echo "WARNING: Unknown distro family '$DISTRO_ID' — using Debian path." ;;
esac
echo ""

# ─── VERIFY PYTHON DEPENDENCIES ──────────────────────────────────────────────
# Use signed distribution packages on the Pi; do not overwrite system Python
# with pip --break-system-packages or silently ignore missing dependencies.
/usr/bin/python3 -c 'import flask, requests, pytz, dateutil' || {
    echo "ERROR: Required Python modules are missing. Review requirements.txt and install distribution packages."
    exit 1
}
echo ""

# ─── INSTALL BROWSER (kiosk/combined) ────────────────────────────────────────
if [[ "$MODE" == "kiosk" || "$MODE" == "combined" ]]; then
    echo "--- Installing Browser ---"

    if [[ "$BROWSER_TYPE" == "chrome" ]]; then
        if have_cmd google-chrome; then
            echo "Google Chrome is already installed — skipping download/install."
            BROWSER_BIN="google-chrome"
        elif [[ -f "$CHROME_DEB" ]]; then
            echo "Installing Google Chrome from: $CHROME_DEB"
            apt-get install -y "$CHROME_DEB" || true
            apt-get install -f -y
            BROWSER_BIN="google-chrome"
        else
            echo ""
            echo "  NOTE: Google Chrome not found and no .deb present at:"
            echo "    $CHROME_DEB"
            echo "  Falling back to a distro-appropriate Chromium..."
            echo ""
            BROWSER_TYPE="chromium"
        fi
    fi

    if [[ "$BROWSER_TYPE" == "chromium" ]]; then
        case "$DISTRO_FAMILY" in
            debian)
                # Older distros ship chromium-browser; newer ones ship chromium.
                if apt-cache policy chromium 2>/dev/null | grep -q "^  Candidate: [0-9]"; then
                    echo "Installing chromium via apt..."
                    apt-get install -y chromium
                    BROWSER_BIN="chromium"
                elif apt-cache policy chromium-browser 2>/dev/null | grep -q "^  Candidate: [0-9]"; then
                    echo "Installing chromium-browser via apt..."
                    apt-get install -y chromium-browser
                    BROWSER_BIN="chromium-browser"
                elif [[ "$ARCH" == "x86_64" || "$ARCH" == "amd64" ]]; then
                    # Debian 12+/no chromium package: fall back to Google Chromium's
                    # .deb (a real browser that works in --kiosk without sandbox hacks).
                    echo "No apt Chromium package found — downloading Google Chromium .deb..."
                    if wget -q -O /tmp/chromium.deb \
                        "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb";
                    then
                        if apt-get install -y /tmp/chromium.deb; then
                            BROWSER_BIN="google-chrome"
                        fi
                    fi
                    if [[ -z "$BROWSER_BIN" ]]; then
                        echo "ERROR: Could not download/install a Chromium binary for this distro."
                        echo "Install Chromium manually, then re-run this script."
                        exit 1
                    fi
                else
                    echo ""
                    echo "ERROR: No chromium package found in apt for this distro."
                    echo "Install chromium manually, then re-run this script."
                    exit 1
                fi
                ;;
            fedora)
                dnf install -y chromium || yum install -y chromium
                BROWSER_BIN="chromium"
                ;;
            arch)
                pacman -S --noconfirm chromium
                BROWSER_BIN="chromium"
                ;;
            suse)
                zypper --non-interactive install chromium
                BROWSER_BIN="chromium"
                ;;
            *)
                echo "WARNING: No known Chromium install path for '$DISTRO_ID'."
                echo "Install a browser manually, then re-run this script."
                exit 1
                ;;
        esac
    fi

    # Verify the browser binary resolves (chrome -> /usr/bin/google-chrome etc.)
    if [[ -n "$BROWSER_BIN" ]] && ! have_cmd "$BROWSER_BIN"; then
        # Some chromium builds name the binary differently; search common names.
        for cand in chromium chromium-browser google-chrome google-chrome-stable; do
            if have_cmd "$cand"; then
                BROWSER_BIN="$cand"
                break
            fi
        done
    fi

    if ! have_cmd "$BROWSER_BIN"; then
        echo ""
        echo "ERROR: Browser binary '$BROWSER_BIN' not found after installation."
        exit 1
    fi
    echo "Browser binary: $(command -v "$BROWSER_BIN")"
    echo ""
fi

# ─── HELPER FUNCTIONS ────────────────────────────────────────────────────────
copy_if_exists() {
    local src="$1" dst="$2" name
    name="$(basename "$dst")"
    if [[ ! -f "$src" ]]; then
        echo "  WARNING: source not found — $src"
        return 1
    fi
    if [[ "$src" -ef "$dst" ]]; then
        echo "  OK: $name (already in place)"
        return 0
    fi
    cp "$src" "$dst" && echo "  Copied: $name"
}

# Find a file in the source tree. Prefers the repo root, then a nested
# 'scoreboard/' staging dir, handling the lowercase vs uppercase 'CSS' quirk.
find_src() {
    local rel="$1"
    if [[ -f "$SCRIPT_DIR/$rel" ]]; then
        echo "$SCRIPT_DIR/$rel"; return
    fi
    if [[ -n "${rel##templates/*}" && -f "$SCRIPT_DIR/templates/$(basename "$rel")" ]]; then
        echo "$SCRIPT_DIR/templates/$(basename "$rel")"; return
    fi
    # static/CSS vs static/css
    if [[ "$rel" == static/css/* && -f "$SCRIPT_DIR/static/CSS/$(basename "$rel")" ]]; then
        echo "$SCRIPT_DIR/static/CSS/$(basename "$rel")"; return
    fi
    if [[ -f "$SCRIPT_DIR/scoreboard/$rel" ]]; then
        echo "$SCRIPT_DIR/scoreboard/$rel"; return
    fi
    echo ""
}

# ─── APPLICATION DIRECTORIES ─────────────────────────────────────────────────
echo "--- Setting Up Application Directories ---"
# Every directory the app touches at runtime, so nothing relies on lazy mkdir.
mkdir -p "$APP_DIR/templates"
mkdir -p "$APP_DIR/static/css" "$APP_DIR/static/js" "$APP_DIR/static/data" "$APP_DIR/scripts"
mkdir -p "$APP_DIR/static/uploads"
mkdir -p "$APP_DIR/static/uploads/specials"
mkdir -p "$APP_DIR/static/uploads/rss_logos"
echo "  Created: $APP_DIR/templates"
echo "  Created: $APP_DIR/static/css"
echo "  Created: $APP_DIR/static/uploads"
echo "  Created: $APP_DIR/static/uploads/specials"
echo "  Created: $APP_DIR/static/uploads/rss_logos"
echo ""

# ─── COPY APPLICATION FILES ──────────────────────────────────────────────────
echo "--- Copying Application Files ---"

# Main application source
copy_if_exists "$SCRIPT_DIR/app.py" "$APP_DIR/app.py"
copy_if_exists "$SCRIPT_DIR/score_details.py" "$APP_DIR/score_details.py"
copy_if_exists "$SCRIPT_DIR/cfb_week.py" "$APP_DIR/cfb_week.py"

# Templates
for tmpl in index.html login.html settings.html; do
    SRC=$(find_src "templates/$tmpl")
    if [[ -n "$SRC" ]]; then
        copy_if_exists "$SRC" "$APP_DIR/templates/$tmpl" || true
    else
        echo "  WARNING: template not found — templates/$tmpl"
    fi
done

# Copy application assets; preserve static/uploads and all user-owned media.
for asset_dir in css js data; do
    for asset in "$SCRIPT_DIR/static/$asset_dir/"*; do
        [[ -f "$asset" ]] || continue
        copy_if_exists "$asset" "$APP_DIR/static/$asset_dir/$(basename "$asset")"
    done
done
copy_if_exists "$SCRIPT_DIR/scripts/network_helper.py" "$APP_DIR/scripts/network_helper.py"

# version.txt — read by the /api/update/version endpoint
copy_if_exists "$SCRIPT_DIR/version.txt" "$APP_DIR/version.txt" || true

# settings.json — preserve existing config if already installed
if [[ ! -f "$APP_DIR/settings.json" ]]; then
    copy_if_exists "$SCRIPT_DIR/settings.json" "$APP_DIR/settings.json" || true
else
    echo "  OK: settings.json (existing config preserved)"
fi

# kiosk.json is a mode marker in legacy installations. Never create/copy it
# for Server/Combined: its mere presence changes legacy backend/launcher ports.
if [[ "$MODE" == kiosk && ! -f "$APP_DIR/kiosk.json" ]]; then
    python3 - "$APP_DIR/kiosk.json" "$KIOSK_SERVER_URL" <<'PYEOF'
import json, sys
from urllib.parse import urlparse
url = urlparse(sys.argv[2])
if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
    raise SystemExit('Remote server URL must be HTTP(S), with no embedded credentials.')
with open(sys.argv[1], 'w', encoding='utf-8') as stream:
    json.dump({'server_url': sys.argv[2]}, stream)
PYEOF
fi
# Preserve existing settings verbatim; initialize only missing mode/port keys.
python3 - "$APP_DIR/settings.json" "$MODE" <<'PYEOF'
import json, os, sys, tempfile
path, mode = sys.argv[1:]
if os.path.exists(path):
    with open(path, encoding='utf-8') as stream:
        settings = json.load(stream)
    if not isinstance(settings, dict):
        raise SystemExit('settings.json must contain an object; restore the backup before installing.')
else:
    settings = {}
changed = 'device_mode' not in settings or 'port' not in settings
settings.setdefault('device_mode', 'kiosk' if mode == 'kiosk' else 'server')
settings.setdefault('port', 5001 if mode == 'kiosk' else 5000)
if changed:
    descriptor, temporary = tempfile.mkstemp(prefix='.settings-', dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(settings, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
PYEOF

# paired_kiosks.json — kiosk registry consumed by the pairing endpoint.
if [[ ! -f "$APP_DIR/paired_kiosks.json" ]]; then
    if [[ -f "$SCRIPT_DIR/paired_kiosks.json" ]]; then
        copy_if_exists "$SCRIPT_DIR/paired_kiosks.json" "$APP_DIR/paired_kiosks.json" || true
    else
        echo "{}" > "$APP_DIR/paired_kiosks.json"
        echo "  Created: paired_kiosks.json (empty registry)"
    fi
else
    echo "  OK: paired_kiosks.json (existing config preserved)"
fi

# Keep the upstream license and operating instructions with installed code.
copy_if_exists "$SCRIPT_DIR/LICENSE" "$APP_DIR/LICENSE"
for documentation in README.md QC_REPORT.md requirements.txt; do
    copy_if_exists "$SCRIPT_DIR/$documentation" "$APP_DIR/$documentation" || true
done

# Optional helper scripts (copied if they exist in the source tree)
for f in debug.py debug2.py init_display.sh setup_kiosk_service.sh start_kiosk.sh; do
    copy_if_exists "$SCRIPT_DIR/$f" "$APP_DIR/$f" || true
done

# Default logo (templates reference /static/uploads/logo.png). If the repo
# carries one, provision it; otherwise flag it so it can be set via Settings.
if [[ -f "$APP_DIR/static/uploads/logo.png" ]]; then
    echo "  OK: existing custom logo preserved"
elif [[ -f "$SCRIPT_DIR/static/uploads/logo.png" ]]; then
    copy_if_exists "$SCRIPT_DIR/static/uploads/logo.png" "$APP_DIR/static/uploads/logo.png" || true
elif [[ -f "$SCRIPT_DIR/logo.png" ]]; then
    copy_if_exists "$SCRIPT_DIR/logo.png" "$APP_DIR/static/uploads/logo.png" || true
else
    echo "  NOTE: no default logo found — set one from the Settings page."
fi
echo ""

# ─── SYSTEMD: SCOREBOARD BACKEND ─────────────────────────────────────────────
echo "--- Creating Scoreboard Service ---"
if [[ -f /etc/systemd/system/scoreboard.service ]]; then
    cp -p /etc/systemd/system/scoreboard.service "/etc/systemd/system/scoreboard.service.backup-$(date +%Y%m%d%H%M%S)"
fi
render_backend_unit "$APP_USER" "$APP_DIR" "$APP_HOME" > /etc/systemd/system/scoreboard.service
echo "Written: /etc/systemd/system/scoreboard.service"
echo ""

# ─── KIOSK DISPLAY (kiosk/combined) ──────────────────────────────────────────
if [[ "$MODE" == "kiosk" || "$MODE" == "combined" ]]; then

    echo "--- Disabling other desktop managers ---"
    # Only one display manager can own the seat. LightDM is what we configure
    # for autologin, so disable anything else (GDM, SDDM, LXDM, SLiM) that
    # might be the active session on a pre-existing desktop install.
    for dm in gdm gdm3 sddm lxdm slim lightdm; do
        if systemctl list-unit-files 2>/dev/null | grep -q "^${dm}.service"; then
            if [[ "$dm" != "lightdm" ]]; then
                systemctl disable "$dm.service" 2>/dev/null || true
                echo "  Disabled: $dm.service"
            fi
        fi
    done
    echo ""

    echo "--- Configuring Auto-Login (LightDM) ---"
    mkdir -p /etc/lightdm/lightdm.conf.d
    cat > /etc/lightdm/lightdm.conf.d/50-scoreboard.conf <<EOF
[Seat:*]
autologin-user=$APP_USER
autologin-user-timeout=0
user-session=openbox
EOF
    # Let systemd resolve its distro-specific unit path and alias. A blind
    # /lib symlink can be broken on /usr/lib-only distributions.
    if [[ -L /etc/systemd/system/display-manager.service || -f /etc/systemd/system/display-manager.service ]]; then
        cp -a /etc/systemd/system/display-manager.service "/etc/systemd/system/display-manager.service.backup-$(date +%Y%m%d%H%M%S)"
    fi
    systemctl enable --force lightdm.service
    if [[ ! -f "$APP_DIR/previous-default-target.txt" ]]; then
        systemctl get-default > "$APP_DIR/previous-default-target.txt"
    fi
    # Pi OS Lite defaults to multi-user.target; merely enabling a graphical
    # service does not boot it unless graphical.target is reached.
    systemctl set-default graphical.target
    echo "Written: /etc/lightdm/lightdm.conf.d/50-scoreboard.conf"
    echo ""

    echo "--- Installing Shared Kiosk Launcher and Service ---"
    # One maintained launcher for manual and installed operation.
    copy_if_exists "$SCRIPT_DIR/start_kiosk.sh" "$APP_DIR/start_kiosk.sh"
    chmod +x "$APP_DIR/start_kiosk.sh"
    if [[ -f /etc/systemd/system/kiosk.service ]]; then
        cp -p /etc/systemd/system/kiosk.service "/etc/systemd/system/kiosk.service.backup-$(date +%Y%m%d%H%M%S)"
    fi
    bash "$APP_DIR/setup_kiosk_service.sh" --render-unit "$APP_USER" "$APP_DIR" "$APP_HOME" > /etc/systemd/system/kiosk.service
    echo "Written: /etc/systemd/system/kiosk.service"
    echo ""

    echo "--- Configuring Openbox ---"
    mkdir -p "$APP_HOME/.config/openbox"
    cat > "$APP_HOME/.config/openbox/autostart" <<EOF
# Display environment setup only — browser is launched by kiosk.service
xset s off
xset -dpms
xset s noblank
unclutter -idle 0 &
EOF
    echo "Written: $APP_HOME/.config/openbox/autostart"
    echo ""

fi

# ─── NARROW PRIVILEGED NETWORK HELPER / SUDOERS ──────────────────────────────
# The privileged helper must be root-owned outside the app user's writable tree.
install -d -m 755 /usr/local/libexec
install -o root -g root -m 755 "$SCRIPT_DIR/scripts/network_helper.py" /usr/local/libexec/scoreboard-network
SYSTEMCTL_PATH=$(command -v systemctl)
SUDO_TMP=$(mktemp)
trap 'rm -f "$SUDO_TMP"' EXIT
cat > "$SUDO_TMP" <<EOF
# Exact service actions only; no arbitrary units or unrestricted root tools.
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH start kiosk.service
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH stop kiosk.service
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH restart kiosk.service
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH restart scoreboard.service
# The root-owned helper validates each network operation and its argument list.
$APP_USER ALL=(root) NOPASSWD: /usr/local/libexec/scoreboard-network
EOF
chmod 440 "$SUDO_TMP"
visudo -c -f "$SUDO_TMP"
if [[ -f /etc/sudoers.d/scoreboard ]]; then
    cp -p /etc/sudoers.d/scoreboard "/etc/sudoers.d/scoreboard.backup-$(date +%Y%m%d%H%M%S)"
fi
install -o root -g root -m 440 "$SUDO_TMP" /etc/sudoers.d/scoreboard
echo "Written: /etc/sudoers.d/scoreboard"
echo ""

# Existing DHCP/Wi-Fi/Ethernet settings are intentionally preserved. Do not
# inject 192.168.1.250, which may conflict with another device on the LAN.

# ─── PERMISSIONS ─────────────────────────────────────────────────────────────
echo "--- Setting Permissions ---"
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
# Set modes only for application files we install; preserve uploaded media and
# unrelated files instead of recursively making everything world-readable.
chmod 755 "$APP_DIR" "$APP_DIR/templates" "$APP_DIR/static" "$APP_DIR/static/css" "$APP_DIR/static/js" "$APP_DIR/static/data" "$APP_DIR/scripts"
for installed in "$APP_DIR/app.py" "$APP_DIR/score_details.py" "$APP_DIR/cfb_week.py" "$APP_DIR/version.txt" "$APP_DIR/requirements.txt" "$APP_DIR/LICENSE" "$APP_DIR/README.md" "$APP_DIR/QC_REPORT.md" "$APP_DIR/templates/"*.html "$APP_DIR/static/css/"* "$APP_DIR/static/js/"* "$APP_DIR/static/data/"*.json "$APP_DIR/scripts/"*.py; do
    [[ ! -f "$installed" ]] || chmod 644 "$installed"
done
for config in settings.json kiosk.json paired_kiosks.json .session-key score_cache.json; do
    [[ ! -f "$APP_DIR/$config" ]] || chmod 600 "$APP_DIR/$config"
done
for launcher in start_kiosk.sh init_display.sh setup_kiosk_service.sh; do
    [[ ! -f "$APP_DIR/$launcher" ]] || chmod 755 "$APP_DIR/$launcher"
done
[[ "$MODE" == "kiosk" || "$MODE" == "combined" ]] && chown -R "$APP_USER:$APP_GROUP" "$APP_HOME/.config" 2>/dev/null || true
echo "Permissions set on $APP_DIR"
echo ""

# ─── ENABLE SERVICES ─────────────────────────────────────────────────────────
echo "--- Enabling Services ---"
systemctl daemon-reload
systemctl enable scoreboard.service 2>/dev/null || true
echo "Enabled: scoreboard.service"
if [[ -f "$APP_DIR/app.py" ]]; then
    systemctl restart scoreboard.service && echo "Started:  scoreboard.service" \
        || echo "WARNING: scoreboard.service failed to start — check journalctl -u scoreboard."
else
    echo "WARNING: $APP_DIR/app.py not found — scoreboard service not started."
fi

if [[ "$MODE" == "kiosk" || "$MODE" == "combined" ]]; then
    systemctl enable lightdm.service 2>/dev/null || true
    echo "Enabled: lightdm.service"
    systemctl enable kiosk.service 2>/dev/null || true
    echo "Enabled: kiosk.service"
fi
echo ""

# ─── DONE ────────────────────────────────────────────────────────────────────
echo "======================================================="
echo "   Installation Complete!"
echo "======================================================="
echo ""
echo "  Mode     : $MODE"
echo "  App dir  : $APP_DIR"
echo "  User     : $APP_USER"
echo ""

REQUIRED_FILES="$APP_DIR/app.py
$APP_DIR/templates/index.html
$APP_DIR/templates/login.html
$APP_DIR/templates/settings.html
$APP_DIR/static/css/main.css
$APP_DIR/version.txt"
WARN=0
for f in $REQUIRED_FILES; do
    [[ ! -f "$f" ]] && echo "  WARNING: Missing — $f" && WARN=1
done

if [[ "$MODE" == "server" ]]; then
    SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "  Backend URL : http://${SERVER_IP:-<this-machine-ip>}:5000"
    echo "  Point your kiosk(s) to this address in their settings."
    echo ""
elif [[ "$MODE" == "kiosk" ]]; then
    echo "  Browser       : $BROWSER_BIN"
    echo "  Display       : http://localhost:$DISPLAY_PORT"
    echo "  Remote server : $KIOSK_SERVER_URL"
    echo "  (Edit $APP_DIR/kiosk.json or use Settings to change the server URL)"
    echo ""
    echo "  Reboot manually after reviewing the service logs."
    echo "  Maintenance: Ctrl+Alt+F2, log in, sudo systemctl stop kiosk.service"
else
    echo "  Browser : $BROWSER_BIN"
    echo "  Display : http://localhost:$DISPLAY_PORT"
    echo ""
    echo "  Reboot manually after reviewing the service logs."
    echo "  Maintenance: Ctrl+Alt+F2, log in, sudo systemctl stop kiosk.service"
fi

[[ $WARN -eq 1 ]] && echo ""
echo "======================================================="

echo "No automatic reboot. When ready on a test installation: sudo reboot"
