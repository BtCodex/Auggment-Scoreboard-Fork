# Fresh Raspberry Pi installation from your GitHub fork

Target: Raspberry Pi 4, 2 GB RAM, **32-bit Raspberry Pi OS**, one HDMI display.
Use a new/test microSD card and keep the current working card safe. No commands
in this guide have been run on your Pi. Cloud checks do not verify ARM boot,
HDMI/GPU behavior or unattended 24/7 operation.

The application will run directly from its Git checkout at `$HOME/scoreboard`.
That makes future `git pull --ff-only` update the actual running application,
rather than a separate source directory. No Git knowledge or `.git` directory is
required on the old ZIP-installed card.

## 1. Prepare the fresh card

In Raspberry Pi Imager choose Raspberry Pi 4 and **Raspberry Pi OS Lite (32-bit)**.
Lite is appropriate because this installer adds its own X11, LightDM/Openbox and
Chromium kiosk. Do not install it over an existing customized Wayland desktop.
Create your regular username/password, enable SSH if desired, and configure Wi-Fi
and locale/timezone (America/Chicago). Connect the Pi to a monitor and network.

Boot, log in, then run:

```bash
getconf LONG_BIT
python3 --version
sudo apt-get update
sudo apt-get install -y git ca-certificates curl
```

`LONG_BIT` should print `32`. Python 3.9 or newer is required. Do not use an old
unsupported OS merely to obtain 32-bit userland. The code uses the same four
runtime dependencies (Flask, Requests, pytz, python-dateutil); no Node, Playwright,
Java or Android SDK is needed on the Pi. Installer package availability still
needs verification on your selected Pi OS image.

## 2. Clone the development candidate into the runtime directory

Run as your regular login user, not inside a root shell:

```bash
git clone --branch improve/complete-weekly-cfb-rotation \
  https://github.com/BtCodex/Auggment-Scoreboard-Fork.git "$HOME/scoreboard"
cd "$HOME/scoreboard"
git status --short --branch
git rev-parse --short HEAD
sudo bash install.sh
```

At the installer prompts choose **3 — Combined** for one Pi running the server
and HDMI kiosk. Accept **your current regular username**. This installs under
that user's home at `scoreboard`, the same directory just cloned. Do not enter
`root` for a kiosk. The installer safely skips copying files already in place.

Combined installs distro Python dependencies, Chromium and a minimal X11 desktop;
creates backend/kiosk services with bounded crash retries; installs the reviewed
privileged helper; and configures graphical login. These changes are intended
only on this fresh card. They have not been executed against your working card.

## 3. Check the backend, then boot the kiosk

```bash
systemctl is-enabled scoreboard.service kiosk.service
sudo systemctl status scoreboard.service --no-pager
curl --fail http://127.0.0.1:5000/api/ping
hostname -I
```

The health response must contain `"ok": true`. If it fails, inspect the error
before rebooting:

```bash
sudo journalctl -u scoreboard.service -n 80 --no-pager
```

From your phone on the same home network, visit `http://PI_IP:5000/settings`, using
the address printed by `hostname -I`. Default login is `admin` / `root`; change
it in Account settings. Do not configure internet-facing port forwarding.

When the backend is healthy:

```bash
sudo reboot
```

After boot, verify the kiosk and backend rather than assuming enablement proves
startup succeeded:

```bash
systemctl is-active scoreboard.service kiosk.service
sudo journalctl -u scoreboard.service -u kiosk.service -b --no-pager
```

The launcher waits for X11 and the backend, and retries after interruptions.
To leave kiosk for maintenance, SSH in or press Ctrl+Alt+F2, log in, and run
`sudo systemctl stop kiosk.service`. Resume with `sudo systemctl start kiosk.service`.

## 4. Configure complete CFB coverage and scorecard filtering

In phone settings:

- Enable college football and choose **All Power 5 Games** (the default).
  This covers all games in the provider's official current football week involving
  a 2026 ACC, Big Ten, Big 12, SEC or rebuilt Pac-12 football team, plus Notre Dame,
  including Group of Five/FCS opponents. Favorites only control highlighting.
- Choose the CFB/Both football display option as desired. A saved NFL-only/day
  filter can still hide CFB; complete coverage does not override that choice.
- Choose **Live**, **Upcoming**, or **Both** in Scorecard games. **Both** is the
  default. Live includes halftime/overtime. Enable **Include completed games**
  separately if you want finals in the rotation; it defaults off.
- For every eligible game in the entire week, use **Both + Include completed
  games**. The filter automatically reevaluates on score refresh and does not
  filter the bottom ticker. Canceled/unknown/delayed states are not asserted to
  be live/upcoming. No matching games produces an explanatory slide.
- The CFB source refresh defaults to **180 seconds**; use 30–900 seconds in
  settings. Source latency still applies. Transient field/base widgets retain
  their stricter freshness expiry and may hide between slower fetches.
- Set America/Chicago, your clock format, title/time switches, theme, colors,
  slide durations and custom logo. Saving preferences needs no code editing.

CFB games remain ordered by actual kickoff timestamp with stable event-ID ties.
An official kickoff correction updates the timestamp; a live/final transition
does not move the game by status or rank. Custom favorite playlist order cannot
truncate, duplicate or reorder the complete CFB block. Other slide categories
continue to work.

## 5. Preserve your existing custom image, colors and favorites

A fresh card cannot contain artwork/settings from the old card automatically.
Keep the old card intact. Before replacing it, privately back up the old app
directory (its real path is shown by `systemctl show scoreboard.service -p
WorkingDirectory`) to another computer. This does not require Git.

You can upload your original College GameDay image and set colors through the
phone interface. To transfer saved configuration, extract the old private backup
into a separate staging folder, stop the new kiosk/backend, and copy **only** its
`settings.json` and `static/uploads` into the new checkout, keeping ownership with
your new service user. Keep a backup of the fresh settings first. Do not replace
new code, `.git`, installed service units, startup files or the whole directory.
Copy pairing/kiosk files only if intentionally migrating that same device role.

After restoring old settings, check Device Mode/server display and the new CFB
coverage/filter settings. Existing settings without these new fields receive
the defaults above. Password/conference schema migration may occur on save/login;
keep the original private archive for rollback. Uploaded media/configuration are
ignored by Git and never need committing or uploading to GitHub.

## 6. Future updates with git pull

Stay on the reviewed development branch unless a later release explicitly tells
you to switch. Do not run the full OS installer again merely for code updates.

First inspect changes while the display is still running:

```bash
cd "$HOME/scoreboard"
git status --short --branch
git fetch origin
git log --oneline HEAD..'@{u}'
```

If tracked files show local modifications, stop and preserve/merge them. Do not
use `git reset --hard` or `git clean` to force an update. Saved settings/uploads
are ignored files; they should not appear as tracked modifications.

Back up consistently before pulling. Keep this terminal open:

```bash
APP_DIR="$HOME/scoreboard"
UPDATE_STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$HOME/scoreboard-backups/$UPDATE_STAMP"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
git -C "$APP_DIR" rev-parse HEAD > "$BACKUP_DIR/commit.txt"
printf 'APP_DIR=%q\nBACKUP_DIR=%q\nUPDATE_STAMP=%q\n' \
  "$APP_DIR" "$BACKUP_DIR" "$UPDATE_STAMP" > "$BACKUP_DIR/paths.sh"
sudo systemctl stop kiosk.service
sudo systemctl stop scoreboard.service
sudo tar --acls --xattrs -cpf "$BACKUP_DIR/application.tar" -C "$APP_DIR" .
sudo tar -tf "$BACKUP_DIR/application.tar" > "$BACKUP_DIR/contents.txt"
```

Proceed only if the archive succeeded; it includes `.git`, private data and the
old code. Keep it private. Then:

```bash
cd "$APP_DIR"
git pull --ff-only
python3 -m py_compile app.py score_details.py cfb_week.py
python3 -c 'import flask, requests, pytz, dateutil; print("Dependencies available")'
sudo systemctl start scoreboard.service
sudo systemctl status scoreboard.service --no-pager
curl --fail http://127.0.0.1:5000/api/ping
```

Continue only after the backend is healthy:

```bash
sudo systemctl start kiosk.service
```

No runtime dependencies were added for this change, so do not run pip/OS upgrades
unnecessarily. Future releases that change dependencies/services need their
specific migration instructions. Use the configured port if you changed 5000.
These commands assume the fresh Combined setup above; omit kiosk commands on a
server-only installation.

## Roll back a failed update

Restore the entire backup, including settings and code, without deleting the
failed installation. If this is a new terminal, source `paths.sh` from your exact
backup directory first. Then:

```bash
cd "$HOME"
sudo systemctl stop kiosk.service
sudo systemctl stop scoreboard.service
sudo tar -tf "$BACKUP_DIR/application.tar" > /dev/null
FAILED_DIR="${APP_DIR}.failed-${UPDATE_STAMP}"
test ! -e "$FAILED_DIR"
sudo mv "$APP_DIR" "$FAILED_DIR"
sudo mkdir "$APP_DIR"
sudo tar --acls --xattrs -xpf "$BACKUP_DIR/application.tar" -C "$APP_DIR"
sudo systemctl start scoreboard.service
curl --fail http://127.0.0.1:5000/api/ping
```

Stop on any failure. Once the restored backend works, run
`sudo systemctl start kiosk.service`. The original repository/data are restored
at the same service path; the failed directory remains available for diagnosis.
Do not delete either copy until recovery is confirmed.

## Physical acceptance before 24/7 use

Verify cold boot online/offline, actual custom logo/colors, phone controls,
CFB/week eligibility and complete final-to-first rotation, live filter transitions,
unchanged ticker and internet reconnection. Compare real ESPN event IDs/counts
and the requested October 24 games using [the source audit](CFB_WEEK_SOURCE_AUDIT.md).
That source comparison could not run in the cloud. Measure backend/Chromium RAM,
CPU, temperature and restart counts during a 24–48 hour soak on the Pi before
unattended use.
