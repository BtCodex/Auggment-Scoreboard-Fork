#!/bin/bash
# Shared launcher for installed and manual kiosks. Run as the desktop user.
# install.sh copies this file unchanged so startup fixes cannot drift.
set -u

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

if [ "$(id -u)" -eq 0 ]; then
    echo "Run the kiosk as a regular desktop user; Chromium's sandbox stays enabled." >&2
    exit 1
fi

BROWSER="${SCOREBOARD_BROWSER:-}"
if [ -z "$BROWSER" ]; then
    for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
        if command -v "$candidate" >/dev/null 2>&1; then
            BROWSER="$(command -v "$candidate")"
            break
        fi
    done
fi
if [ -z "$BROWSER" ] || [ ! -x "$BROWSER" ]; then
    echo "No Chromium/Chrome browser found. Install the distribution browser first." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to wait for the scoreboard backend." >&2
    exit 1
fi

# settings.json is authoritative. The legacy kiosk.json fallback is retained
# for older installations that have not saved settings yet.
PORT=5000
[ -f "$APP_DIR/kiosk.json" ] && PORT=5001
if command -v python3 >/dev/null 2>&1 && [ -f "$APP_DIR/settings.json" ]; then
    CONFIG_PORT=$(python3 - "$APP_DIR/settings.json" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as stream:
        port = json.load(stream).get('port')
    if type(port) is int and 1 <= port <= 65535:
        print(port)
except (OSError, ValueError, TypeError, AttributeError):
    pass
PYEOF
)
    [ -n "$CONFIG_PORT" ] && PORT="$CONFIG_PORT"
fi
URL="http://127.0.0.1:${PORT}/"

# A unit being ordered after display-manager.service does not mean that X11
# has finished autologin. Wait for the actual user's display before launch.
if command -v xset >/dev/null 2>&1; then
    echo "Waiting for X11 display ${DISPLAY} ..."
    display_attempt=0
    until xset q >/dev/null 2>&1; do
        display_attempt=$((display_attempt + 1))
        if [ $((display_attempt % 15)) -eq 0 ]; then
            echo "X11 session is still unavailable; check LightDM, DISPLAY and XAUTHORITY."
        fi
        sleep 2
    done
    xset s off >/dev/null 2>&1 || true
    xset -dpms >/dev/null 2>&1 || true
    xset s noblank >/dev/null 2>&1 || true
fi

# Never open a refused-connection page after an arbitrary timeout. Each probe
# is bounded, but late/offline boots can wait indefinitely without restarting.
echo "Waiting for scoreboard at ${URL} ..."
attempt=0
until curl --fail --silent --show-error --connect-timeout 2 --max-time 5 "$URL" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ $((attempt % 15)) -eq 0 ]; then
        echo "Scoreboard is still starting; retrying ${URL} (check scoreboard.service)."
    fi
    sleep 2
done

# Fullscreen geometry on minimal Openbox/X11 installations. No global pkill:
# starting a kiosk must not terminate unrelated browsers or another display.
GEOMETRY=()
if command -v xrandr >/dev/null 2>&1; then
    RESOLUTION=$(xrandr --current 2>/dev/null | awk '/\*/{print $1; exit}')
    if [[ "$RESOLUTION" =~ ^([0-9]+)x([0-9]+)$ ]] &&
       [ "${BASH_REMATCH[1]}" -gt 0 ] && [ "${BASH_REMATCH[2]}" -gt 0 ]; then
        GEOMETRY=("--window-size=${BASH_REMATCH[1]},${BASH_REMATCH[2]}" "--window-position=0,0")
    fi
fi

VERSION=$(cat "$APP_DIR/version.txt" 2>/dev/null || true)
[[ "$VERSION" =~ ^[a-zA-Z0-9._-]+$ ]] || VERSION=local
echo "Opening scoreboard at ${URL}"
exec "$BROWSER" \
    --kiosk \
    --start-fullscreen \
    --no-first-run \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --noerrdialogs \
    --disable-translate \
    "${GEOMETRY[@]}" \
    --user-data-dir="$HOME/.config/browser-kiosk" \
    "${URL}?v=${VERSION}"
