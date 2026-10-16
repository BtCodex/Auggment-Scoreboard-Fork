#!/bin/bash
# Run once with sudo only on a fresh/test installation. --render-unit is safe:
# it prints the generated unit without writing files or invoking systemctl.
set -e

systemd_quote() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//%/%%}"
    printf '"%s"' "$value"
}

render_kiosk_unit() {
    local app_user="$1" app_dir="$2" app_home="$3"
    [[ "$app_user" =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || { echo "Invalid service user" >&2; return 1; }
    [[ "$app_user" != root ]] || { echo "Use a regular desktop user for Chromium." >&2; return 1; }
    [[ "$app_dir" == /* && "$app_home" == /* && "$app_dir$app_home" != *$'\n'* ]] || return 1
    cat <<EOF
[Unit]
Description=Scoreboard Kiosk Browser
After=display-manager.service scoreboard.service
Wants=scoreboard.service
# Keep retrying after a late display/backend, at a bounded 15-second cadence.
StartLimitIntervalSec=0

[Service]
Type=simple
User=$app_user
WorkingDirectory=${app_dir//%/%%}
Environment=DISPLAY=:0
Environment=$(systemd_quote "HOME=$app_home")
Environment=$(systemd_quote "XAUTHORITY=$app_home/.Xauthority")
ExecStart=/bin/bash $(systemd_quote "$app_dir/start_kiosk.sh")
Restart=always
RestartSec=15
TimeoutStopSec=15
KillMode=control-group
UMask=0077

[Install]
WantedBy=graphical.target
EOF
}

if [[ "${1:-}" == --render-unit ]]; then
    [[ $# -eq 4 ]] || { echo "Usage: $0 --render-unit USER APP_DIR USER_HOME" >&2; exit 2; }
    render_kiosk_unit "$2" "$3" "$4"
    exit
fi

[[ "$EUID" -eq 0 ]] || { echo "Run with sudo bash setup_kiosk_service.sh" >&2; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$SCRIPT_DIR}"
APP_USER="${APP_USER:-${SUDO_USER:-$(stat -c '%U' "$APP_DIR")}}"
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
[[ -n "$APP_HOME" && -f "$APP_DIR/start_kiosk.sh" ]] || { echo "User home or kiosk launcher missing." >&2; exit 1; }

# Render before replacing anything, and preserve existing units for rollback.
UNIT_TMP=$(mktemp)
trap 'rm -f "$UNIT_TMP"' EXIT
render_kiosk_unit "$APP_USER" "$APP_DIR" "$APP_HOME" > "$UNIT_TMP"
if [[ -f /etc/systemd/system/kiosk.service ]]; then
    cp -p /etc/systemd/system/kiosk.service "/etc/systemd/system/kiosk.service.backup-$(date +%Y%m%d%H%M%S)"
fi
install -m 644 "$UNIT_TMP" /etc/systemd/system/kiosk.service

# This helper updates only kiosk controls. Leave Wi-Fi and backend grants from
# install.sh in place instead of overwriting all existing sudoers configuration.
SYSTEMCTL_PATH=$(command -v systemctl)
SUDO_TMP=$(mktemp)
trap 'rm -f "$UNIT_TMP" "$SUDO_TMP"' EXIT
cat > "$SUDO_TMP" <<EOF
# Scoreboard kiosk controls only
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH start kiosk.service
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH stop kiosk.service
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_PATH restart kiosk.service
EOF
chmod 440 "$SUDO_TMP"
visudo -c -f "$SUDO_TMP"
install -m 440 "$SUDO_TMP" /etc/sudoers.d/scoreboard-kiosk
systemctl daemon-reload
systemctl enable kiosk.service
printf '%s\n' "Kiosk service installed for $APP_USER (X11/Openbox)." \
    "Start: sudo systemctl start kiosk.service" \
    "Maintenance: Ctrl+Alt+F2, log in, then sudo systemctl stop kiosk.service" \
    "Resume: sudo systemctl start kiosk.service"
