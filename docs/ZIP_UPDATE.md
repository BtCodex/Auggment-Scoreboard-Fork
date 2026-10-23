# Update your existing ZIP installation without reinstalling Raspberry Pi OS

You do **not** need Git or a `.git` directory. Download the dedicated runtime
update ZIP, back up your current application, and replace only the files listed
below. **Do not rerun `install.sh` for this update.** Your service units, kiosk
launcher, desktop, Wi-Fi configuration and boot settings stay in place.

These are commands for you to run later on the Pi; none were run against your
device. An optional cloned SD card provides additional protection, but an OS
reinstall or new card is not required. Keep using the same **Bash terminal** for
all steps. If any check or copy fails, stop at that step.

## 1. Identify the existing installation

```bash
systemctl show scoreboard.service -p User -p WorkingDirectory -p ExecStart
systemctl cat scoreboard.service
systemctl cat kiosk.service
getconf LONG_BIT
```

Use the actual Python executable shown in `ExecStart` below. For example,
`/usr/bin/python3` or `/home/yourname/scoreboard/venv/bin/python`. Enter only the
executable path, not the full command. Do not guess `/home/pi`. If the service
has no WorkingDirectory or uses an unfamiliar wrapper, identify its real paths
before proceeding. Missing `kiosk.service` is normal on a server-only install.

```bash
APP="$(systemctl show scoreboard.service -p WorkingDirectory --value)"
APP_USER="$(systemctl show scoreboard.service -p User --value)"
APP_USER="${APP_USER:-root}"
APP_GROUP="$(id -gn "$APP_USER")"
PYTHON='/replace/with/the/python/executable/from/ExecStart'
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$HOME/scoreboard-update-$STAMP"
BACKUP="$HOME/scoreboard-backups/$STAMP"

printf 'Existing folder: %s\nService user: %s\nPython: %s\n' "$APP" "$APP_USER" "$PYTHON"
test -n "$APP" && test -f "$APP/app.py" && test -x "$PYTHON"
sudo -v
```

**Stop if the last checks fail.** Correct the paths first. Prepare staging and
backup directories outside the installed application:

```bash
mkdir -p "$WORK" "$BACKUP"
chmod 700 "$WORK" "$BACKUP"
APP="$(realpath "$APP")"
WORK="$(realpath "$WORK")"
BACKUP="$(realpath "$BACKUP")"
case "$WORK/" in "$APP/"*) echo 'STOP: staging is inside the app'; false;; esac
case "$BACKUP/" in "$APP/"*) echo 'STOP: backup is inside the app'; false;; esac
df -h "$APP" "$BACKUP"
sudo du -sh "$APP"
```

Allow enough free space for the ZIP, extracted code and complete installed folder.

## 2. Download and validate before stopping the scoreboard

```bash
curl --fail --location --retry 3 --connect-timeout 10 --max-time 180 \
  'https://raw.githubusercontent.com/BtCodex/Auggment-Scoreboard-Fork/improve/complete-weekly-cfb-rotation/artifacts/scoreboard-update-1.5.0-dev.zip' \
  --output "$WORK/scoreboard-update-1.5.0-dev.zip"
curl --fail --location \
  'https://raw.githubusercontent.com/BtCodex/Auggment-Scoreboard-Fork/improve/complete-weekly-cfb-rotation/artifacts/SHA256SUMS' \
  --output "$WORK/SHA256SUMS"
(cd "$WORK" && sha256sum --check SHA256SUMS)
python3 -m zipfile -t "$WORK/scoreboard-update-1.5.0-dev.zip"
python3 -m zipfile -e "$WORK/scoreboard-update-1.5.0-dev.zip" "$WORK/extracted"
CANDIDATE="$WORK/extracted"
test -f "$CANDIDATE/app.py"
```

No `unzip` package is needed. Stop after any download/extraction error. Define
the complete runtime allowlist; it deliberately excludes all device data and
startup scripts:

For compatibility with the web updater, read [the package notes](UPDATE_PACKAGE.md).
The manual route here works around intermediate updaters that omit new modules.
Do not substitute a complete GitHub source ZIP for this runtime-only package.

```bash
FILES=(
  app.py
  score_details.py
  cfb_week.py
  version.txt
  requirements.txt
  LICENSE
  templates/index.html
  templates/settings.html
  templates/login.html
  static/css/main.css
  static/css/display-modes.css
  static/css/live-widgets.css
  static/js/clock.js
  static/js/display.js
  static/js/live-widgets.js
  static/data/football-teams-2026.json
  scripts/network_helper.py
)
```

```bash
(
  set -e
  for relative_path in "${FILES[@]}"; do test -f "$CANDIDATE/$relative_path"; done
  "$PYTHON" -m py_compile "$CANDIDATE/app.py" "$CANDIDATE/score_details.py" "$CANDIDATE/cfb_week.py"
  cd "$APP"
  sudo -u "$APP_USER" "$PYTHON" -c 'import sys, flask, requests, pytz, dateutil; assert sys.version_info >= (3, 9), "Python 3.9+ required"; print("Runtime checks passed")'
)
```

This update adds **no runtime dependencies**. If imports pass, skip dependency
installation. Node, Playwright, Java and Android SDK are not needed on the Pi.

Only if imports fail, use the installation's existing dependency method:

- Distro-managed `/usr/bin/python3`:

  ```bash
  sudo apt-get update
  sudo apt-get install python3-flask python3-requests python3-tz python3-dateutil
  ```

- An existing virtual environment, using its actual Python path:

  ```bash
  sudo -u "$APP_USER" "$PYTHON" -m pip install -r "$CANDIDATE/requirements.txt"
  ```

Repeat the import check. Do not use system `sudo pip`, `--break-system-packages`,
replace the interpreter, or run a full OS upgrade for this application update.
Python older than 3.9 needs a separate compatibility review; do not change a
working OS/interpreter as part of this procedure.

Read the configured port without printing private settings:

```bash
PORT="$(sudo -u "$APP_USER" "$PYTHON" - "$APP" <<'PY'
import json, os, sys
directory = sys.argv[1]
path = os.path.join(directory, 'settings.json')
with open(path, encoding='utf-8') as handle:
    settings = json.load(handle)
port = settings.get('port', 5001 if os.path.exists(os.path.join(directory, 'kiosk.json')) else 5000)
if type(port) is not int or not 1 <= port <= 65535:
    raise SystemExit('Invalid saved port; stop and review the existing configuration')
print(port)
PY
)"
printf 'Existing backend port: %s\n' "$PORT"
```

If settings.json is missing or this fails, identify the service's actual settings
path before continuing. The update must not start a new blank configuration.

## 3. Stop services and back up everything

```bash
KIOSK_WAS_ACTIVE="$(systemctl is-active kiosk.service 2>/dev/null || true)"
printf 'APP=%q\nBACKUP=%q\nPYTHON=%q\nPORT=%q\nKIOSK_WAS_ACTIVE=%q\n' \
  "$APP" "$BACKUP" "$PYTHON" "$PORT" "$KIOSK_WAS_ACTIVE" > "$BACKUP/update-paths.sh"
systemctl cat scoreboard.service > "$BACKUP/scoreboard-unit.txt"
systemctl cat kiosk.service > "$BACKUP/kiosk-unit.txt" 2>/dev/null || true
if [ "$KIOSK_WAS_ACTIVE" = active ]; then sudo systemctl stop kiosk.service; fi
sudo systemctl stop scoreboard.service
sudo tar --acls --xattrs -cpf "$BACKUP/application.tar" -C "$APP" .
sudo tar -tf "$BACKUP/application.tar" > "$BACKUP/archive-contents.txt"
printf 'KEEP THIS BACKUP LOCATION: %s\n' "$BACKUP"
if sudo test -f "$APP/static/uploads/logo.png"; then
  sudo sha256sum "$APP/static/uploads/logo.png" > "$BACKUP/logo.sha256"
fi
```

**Do not copy files unless tar completed successfully.** The private archive
contains settings, uploads, favorite teams, theme preferences, pairing, session
key, cache, permissions and old code. Copy it to another computer if possible;
do not upload it to GitHub/chat. Unit listings are reference copies only.

## 4. Replace only the reviewed runtime files

<!-- BEGIN TESTED RUNTIME COPY -->
```bash
(
  set -e
  for relative_path in "${FILES[@]}"; do
    sudo install -D -m 644 -o "$APP_USER" -g "$APP_GROUP" \
      "$CANDIDATE/$relative_path" "$APP/$relative_path"
  done
  echo 'Application files copied successfully'
)
```
<!-- END TESTED RUNTIME COPY -->

This preserves settings.json, kiosk.json, paired_kiosks.json, .session-key,
score_cache.json and **all static/uploads**. It does not replace install.sh,
start_kiosk.sh, setup_kiosk_service.sh, service units, desktop startup or sudoers.
Saved colors/themes are preserved. Manual edits inside replaced CSS/templates
remain in the backup; they cannot be automatically merged with new source.
Do not recursively chmod/chown the application directory.

The network-helper source is copied, but no privileged helper is installed or
replaced. Old installations may need a separate review for privileged Wi-Fi or
web service-control buttons. Existing connectivity and terminal systemctl
commands keep using the current setup. No network change is needed for scoring.

## 5. Restart the backend, then the kiosk

```bash
sudo systemctl restart scoreboard.service
sudo systemctl status scoreboard.service --no-pager
READY=0
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error "http://127.0.0.1:$PORT/api/ping"; then
    READY=1
    break
  fi
  sleep 1
done
printf '\nBackend health: %s (must be 1 with ok=true)\n' "$READY"
```

Proceed only when `READY=1` and the response contains `"ok": true`. If it fails:

```bash
sudo journalctl -u scoreboard.service -n 80 --no-pager
```

Use rollback below rather than repeatedly changing packages. When healthy:

```bash
if [ "$KIOSK_WAS_ACTIVE" = active ]; then
  sudo systemctl restart kiosk.service
  sudo systemctl status kiosk.service --no-pager
fi
if [ -f "$BACKUP/logo.sha256" ]; then sudo sha256sum -c "$BACKUP/logo.sha256"; fi
```

There is no `daemon-reload` or immediate reboot because units did not change.
Update paired Server/Kiosk application versions together, keeping each device's
own settings/pairing. Reopen the usual scoreboard URL from your phone.

In **Settings → College football coverage**, choose **All Power 5 Games**
(the default). Favorite selections highlight teams rather than limit this mode.
The default CFB provider refresh is 180 seconds and is configurable. A saved
football display choice of NFL-only still hides CFB; select CFB/Both as desired.
The main scorecard filter defaults to Both (live/upcoming), with completed games
off. Enable Include completed games for the entire weekly rotation. This filter
does not remove games from the bottom ticker.

Verify the official week label, complete chronological CFB rotation, kickoff
times, favorite highlights, real logo, colors, clock, other sports and live
refreshes. After initial checks, schedule a controlled reboot to confirm your
existing boot configuration still works; then perform a 24–48 hour soak. Pi
hardware/live-provider verification is not implied by passing cloud tests.

## Rollback without reinstalling the OS

Restore **settings and code together**: passwords/conference representations
can migrate after a save/login, so restoring only app.py is insufficient. If you
closed the terminal, first use the exact printed backup directory:

```bash
source "$HOME/scoreboard-backups/REPLACE_WITH_YOUR_BACKUP_TIMESTAMP/update-paths.sh"
```

```bash
if [ "$KIOSK_WAS_ACTIVE" = active ]; then sudo systemctl stop kiosk.service; fi
sudo systemctl stop scoreboard.service
sudo tar -tf "$BACKUP/application.tar" > /dev/null
sudo tar --acls --xattrs -xpf "$BACKUP/application.tar" -C "$APP"
sudo systemctl start scoreboard.service
sudo systemctl status scoreboard.service --no-pager
curl --fail --silent --show-error "http://127.0.0.1:$PORT/api/ping"
```

For an old version lacking `/api/ping`, check its normal page and service logs
instead. Once the old backend works:

```bash
if [ "$KIOSK_WAS_ACTIVE" = active ]; then sudo systemctl start kiosk.service; fi
```

No directory deletion is needed. Unused new modules/assets can remain; the
restored old application does not reference them. Services and startup files
were never changed, so no unit edits are required to roll back. Keep the archive.

For an optional separate fresh installation later, use the complete ZIP on a
fresh supported test OS and run its install.sh as documented in
[the general installation guide](INSTALL_AND_ROLLBACK.md). That is a separate
route, not a requirement for this in-place update.
