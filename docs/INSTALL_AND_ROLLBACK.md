# Safe installation and rollback

These are instructions for your later physical test. No commands in this guide
were run against your Raspberry Pi. The candidate is not yet proven for unattended
24/7 use on Pi hardware.

## Start with a spare or cloned SD card

Keep the working card untouched. Power down before removing it; keep a complete
image backup somewhere other than the card. Use a spare card for testing. If unsure
which disk an imaging tool will overwrite, stop and check before proceeding.

The branch is `improve/pi-scoreboard-reliability` in
`BtCodex/Auggment-Scoreboard-Fork`. Download/clone that branch into a separate
candidate directory on the test system. Do not copy candidate settings or uploads
over the working application's files.

The code is pure Python plus browser JavaScript. Node, Playwright and Ruff are
**development tools only**. The existing four Python dependencies remain unchanged.
The optional requirements-tested.txt records the tested cloud stack and requires
Python 3.10+ because that Requests version requires it. The ordinary requirements
allow pip to select compatible versions; older supported Pi OS distro packages can
remain in place. Only Python 3.12/x86_64 has been tested locally here; the added CI
matrix is configured for 3.9, 3.11 and 3.12 but is not a physical ARM test.

## Fresh test installation

On a fresh Pi OS test card with a regular user account:

```bash
git clone --branch improve/pi-scoreboard-reliability https://github.com/BtCodex/Auggment-Scoreboard-Fork.git scoreboard-candidate
cd scoreboard-candidate
sudo bash install.sh
```

Read the installer prompts. Select Combined for one Pi running the backend and
HDMI display, Server for a headless data service, or Kiosk for a display client.
Use a regular user for Chromium; do not disable its sandbox or run it as root.
The installer targets X11/Openbox/LightDM. Do not run it over an existing Wayland
session or working installation merely to update application files.

The revised installer preserves device configuration/media, backs up existing code
and units, copies all JS/CSS/helper files, uses distro Python packages, and avoids
network-manager takeover, automatic fallback static IP, automatic reboot, and
removal of unrelated web services. Review logs before rebooting the test card.
It creates/enables backend and applicable kiosk services; actual boot must still
be checked on the device.

## Upgrade an existing installation on the cloned card

If you already have a working X11 installation, use a selective upgrade. These
instructions assume Combined mode; omit kiosk commands for a server-only device.
Do not run the full OS installer for this route.

### 1. Identify the real paths and user

Run these read-only commands locally on the test Pi:

```bash
systemctl show scoreboard.service -p User -p WorkingDirectory -p ExecStart
systemctl cat scoreboard.service kiosk.service
systemctl is-enabled scoreboard.service kiosk.service
getconf LONG_BIT
python3 --version
```

Note the actual service user and WorkingDirectory. If Chromium currently runs as
root, units contain unfamiliar overrides, or the desktop is Wayland, use a fresh
test card or obtain help adapting the configuration. Do not guess a home directory.

Set the following to the **actual paths**. Do not paste placeholder values:

```bash
APP_DIR=/actual/existing/scoreboard
CANDIDATE=/actual/reviewed/candidate
APP_USER=your_regular_service_user
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
test -f "$APP_DIR/app.py" && test -f "$CANDIDATE/app.py" && test -d "$APP_HOME"
```

If that check fails, stop and correct the paths. Ensure the backend service uses
`/usr/bin/python3`, as the rendered unit does. If your installation uses a virtual
environment, retain its actual interpreter in the candidate unit instead of
silently switching interpreters.

### 2. Stop and make a private backup

```bash
backup_dir="$HOME/scoreboard-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
sudo systemctl stop kiosk.service
sudo systemctl stop scoreboard.service
sudo tar --acls --xattrs -cpf "$backup_dir/application.tar" -C "$APP_DIR" .
sudo tar -tf "$backup_dir/application.tar" > "$backup_dir/contents.txt"
sudo cp -p /etc/systemd/system/scoreboard.service "$backup_dir/scoreboard.service"
sudo cp -p /etc/systemd/system/kiosk.service "$backup_dir/kiosk.service"
```

Omit copies/stop commands for absent services. Also copy any existing
`/etc/sudoers.d/scoreboard`, `/etc/sudoers.d/scoreboard-kiosk`, and
`/usr/local/libexec/scoreboard-network` into the private backup if present. Record
service enablement and leave any unit drop-ins unchanged for review. Do not
continue until the archive is readable and includes all device data.

The archive must contain settings.json, kiosk.json/paired_kiosks.json if present,
static/uploads, .session-key if present, and score_cache.json if present. It
contains private configuration: do not upload it to GitHub or chat.

If your custom logo exists, record a checksum:

```bash
sudo sha256sum "$APP_DIR/static/uploads/logo.png" > "$backup_dir/logo.sha256"
```

### 3. Copy reviewed runtime files only

Copy these paths from CANDIDATE to the same paths under APP_DIR, preserving service
user readability. Create static/js and scripts directories if needed:

- app.py
- templates/index.html, templates/settings.html, templates/login.html
- static/css/main.css, static/css/display-modes.css
- static/js/clock.js, static/js/display.js
- start_kiosk.sh, setup_kiosk_service.sh, install.sh
- scripts/network_helper.py
- LICENSE and the guides, if desired

For the reviewed paths above, this Bash block copies only code (not device data):

```bash
APP_GROUP="$(id -gn "$APP_USER")"
while IFS= read -r relative_path; do
    sudo install -D -o "$APP_USER" -g "$APP_GROUP" -m 644 "$CANDIDATE/$relative_path" "$APP_DIR/$relative_path"
done <<'FILES'
app.py
templates/index.html
templates/settings.html
templates/login.html
static/css/main.css
static/css/display-modes.css
static/js/clock.js
static/js/display.js
start_kiosk.sh
setup_kiosk_service.sh
install.sh
scripts/network_helper.py
LICENSE
FILES
sudo chmod 755 "$APP_DIR/start_kiosk.sh" "$APP_DIR/setup_kiosk_service.sh" "$APP_DIR/install.sh"
```

**Do not replace** settings.json, kiosk.json, paired_kiosks.json, .session-key,
score_cache.json, or anything in static/uploads. Ensure APP_USER owns the application
directory and writable device-data directories. Private state should be mode 0600,
not world-readable or executable. Keep source files readable and the launcher
executable. Do not recursively chmod every file to 755.

Existing favorites, enabled leagues, colors, slides, timezone and uploads are
preserved. New options receive defaults on read. Legacy admin passwords migrate
to a private hash after login. Blank password fields retain the password. Change
the default admin/root account through Account settings. Hash migration cannot be
read by the old application; rollback must restore the backed-up settings too.
Existing paired server/kiosk devices should be upgraded together: heartbeat and
privileged update requests now require their existing pairing token.

### 4. Review startup units and optional network helper

Generate candidate units into the backup/review directory without installing them:

```bash
mkdir -p "$backup_dir/units"
bash "$CANDIDATE/install.sh" --render-backend-unit "$APP_USER" "$APP_DIR" "$APP_HOME" > "$backup_dir/units/scoreboard.service"
bash "$CANDIDATE/setup_kiosk_service.sh" --render-unit "$APP_USER" "$APP_DIR" "$APP_HOME" > "$backup_dir/units/kiosk.service"
systemd-analyze verify --man=no "$backup_dir/units/scoreboard.service" "$backup_dir/units/kiosk.service"
```

The generated units use their actual service names so dependency validation can
resolve them. Review any validation errors before proceeding. Keep existing custom
interpreter or display authorization changes that your installation requires.

When reviewed, install the units (omit kiosk on a headless device):

```bash
sudo install -m 644 "$backup_dir/units/scoreboard.service" /etc/systemd/system/scoreboard.service
sudo install -m 644 "$backup_dir/units/kiosk.service" /etc/systemd/system/kiosk.service
sudo systemctl daemon-reload
```

This updates startup definitions without changing the desktop or network manager.
Enable only services that should start at boot; preserve intentionally disabled
services. A Combined test device normally uses `sudo systemctl enable
scoreboard.service kiosk.service` and already has a working graphical login.

Privileged Wi-Fi controls require the new reviewed root-owned helper. To install
it without running the OS installer:

```bash
sudo install -d -m 755 /usr/local/libexec
sudo install -o root -g root -m 755 "$CANDIDATE/scripts/network_helper.py" /usr/local/libexec/scoreboard-network
```

The old unrestricted nmcli/iw/wpa_cli sudo grants are unsafe. Back up the existing
scoreboard-specific file first as described above. This block prepares and validates
its replacement; it does not touch unrelated sudoers files:

```bash
scoreboard_systemctl="$(command -v systemctl)"
cat > "$backup_dir/new-scoreboard-sudoers" <<EOF_RULES
$APP_USER ALL=(root) NOPASSWD: $scoreboard_systemctl start kiosk.service
$APP_USER ALL=(root) NOPASSWD: $scoreboard_systemctl stop kiosk.service
$APP_USER ALL=(root) NOPASSWD: $scoreboard_systemctl restart kiosk.service
$APP_USER ALL=(root) NOPASSWD: $scoreboard_systemctl restart scoreboard.service
$APP_USER ALL=(root) NOPASSWD: /usr/local/libexec/scoreboard-network
EOF_RULES
sudo visudo -c -f "$backup_dir/new-scoreboard-sudoers"
```

Only after it reports that syntax parsed successfully:

```bash
sudo install -o root -g root -m 440 "$backup_dir/new-scoreboard-sudoers" /etc/sudoers.d/scoreboard
```

Keep a second terminal open until tested. If unfamiliar with sudoers, get help or
use the fresh test installation route. Do not add unrestricted root tool grants.
Without the helper, unprivileged network status can still work, while privileged
Wi-Fi changes report a clear setup error; sports access uses your existing network.

### 5. Start and check before reboot

```bash
sudo systemctl start scoreboard.service
curl --fail http://127.0.0.1:5000/api/ping
sudo systemctl start kiosk.service
systemctl status scoreboard.service kiosk.service
journalctl -u scoreboard.service -u kiosk.service -b --no-pager
sudo sha256sum -c "$backup_dir/logo.sha256"
```

Use the configured port (5000 normally; kiosk-only commonly 5001). Skip the checksum
if no logo was recorded. Visit settings from your phone. Clock/mode/colors/timing
changes apply live without restarting the app. A listening-port change requires
restarting backend and kiosk; do that explicitly after saving it.

Reboot only the test card after the physical checklist passes its initial checks.

## Roll back

The simplest rollback is to power down and reinstall the untouched original card.
For rollback on the test card:

1. Stop kiosk and backend services.
2. Save a separate copy of any settings/images changed since backup if wanted.
3. Restore the full application archive, not just app.py:

   ```bash
   sudo tar --acls --xattrs -xpf "$backup_dir/application.tar" -C "$APP_DIR"
   ```

4. Restore the original service units, scoreboard-specific sudoers files and
   privileged helper from the private backup. If those files did not exist before,
   remove only the newly created files recorded in your migration notes. Validate
   restored sudoers with visudo. Preserve unrelated system configuration.
5. Run `sudo systemctl daemon-reload`, restore original enablement, start the old
   services and reload the browser. Verify favorites, configuration and logo checksum.

An extra unreferenced JS/CSS file left by overlay restore is harmless to the old
application. Do not use git clean/reset to recover ignored uploads or credentials.
Restoring the backup reverts settings to the backup time, including the legacy
password representation. The original SD card avoids all partial rollback risks.

## Exit kiosk for maintenance

On an X11 Pi, press Ctrl+Alt+F2, log in, and run `sudo systemctl stop kiosk.service`.
Resume with `sudo systemctl start kiosk.service`. Closing Chromium alone causes
systemd to reopen it. Settings also provides authenticated kiosk stop/start controls.
