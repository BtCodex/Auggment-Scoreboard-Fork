# Auggmented Scoreboard

This development branch adds configurable clock/display modes, safer caching and
startup, mobile settings, and security fixes while retaining the existing sports
scoreboard. See [the QC report](QC_REPORT.md), [installation and rollback guide](docs/INSTALL_AND_ROLLBACK.md),
[physical Pi checklist](docs/PHYSICAL_PI_CHECKLIST.md), and [dual-display plan](docs/DUAL_DISPLAY_PLAN.md).
The candidate is ready for controlled hardware testing, not yet verified for 24/7
operation on a Raspberry Pi.


![Scoreboard](Images/Scoreboard1.png)

## What This Is

Auggmented Scoreboard turns any spare TV into a live, always-on sports ticker for the games you actually care about. Point it at a TV in the kitchen, the garage, the man cave, a break room, a sports bar, a gym, or a church fellowship hall — anywhere people glance up wanting to know the score right now instead of waiting for it.

The problem it solves: national broadcasts and generic score tickers cycle through dozens of games you don't care about before they ever get to yours, and they almost never carry your local high school, college, or rec-league team at all. This app skips all of that. You tell it which leagues and which specific teams matter to you — your NFL team, your kid's high school football team, your alma mater's basketball team, your local NASCAR driver — and it shows *those* scores, live, on a loop, with no waiting and no noise from games or markets that don't mean anything to you.

It pulls real-time scores from ESPN for the major pro and college leagues, plus dedicated leaderboard views for racing (NASCAR, IndyCar, F1) and golf (PGA), and it can also pull in local school schedules directly from your school's athletics page (Thrillshare, MaxPreps, RSS, or iCal calendars) — so the same screen showing the Chiefs score can also show "Auburn HS Football @ Home — Friday 7:00 PM."

## What It Does

* **Live Scores & Tickers** — Real-time scores for NFL, CFL, XFL, MLB, NBA, WNBA, EuroLeague, NHL, NCAA hockey, MLS, NWSL, top European soccer leagues (England, Spain, Germany, Italy, France, Netherlands, Portugal, Scotland, Greece, Turkey) plus Liga MX, Brasileirão, Argentina, UEFA Champions/Europa/Conference League, World Cup & qualifiers, college football/basketball/baseball/softball/volleyball/hockey/lacrosse, MiLB, USL, lacrosse (PLL/NLL), cricket (IPL, BBL, CPL, County), and rugby (Prem Rugby, Top 14, URC, 6 Nations, MLR, World Cup).
* **Racing & Golf** — Dedicated leaderboard cards for NASCAR, IndyCar, F1, and PGA, with your favorite drivers/golfers highlighted even when they're outside the top 10.
* **Local Sports Integration** — Automatically parses your school's or league's calendar (Thrillshare, MaxPreps, RSS, or iCal) to show upcoming local games right alongside the pro and college scores.
* **Kiosk/Server Architecture** — Run one central Server that pulls all the data, and pair as many Kiosk displays (TVs) to it as you want. Each kiosk shares the same live data but can have its own name, colors, orientation, and theme.
* **Fully Customizable Look** — Pick a dark or light theme, a display font, and a color for nearly every element on screen (scores, team names, ticker, racing leaderboards, card backgrounds) from the Settings page — no code required.
* **Smart Automation** — Scheduled display on/off times, automatic Wi-Fi management, and self-updating from GitHub releases or a local update package.

## Requirements

* **Operating System**
  * Raspberry Pi: Raspberry Pi OS (Lite is recommended for Server; Desktop for Kiosk/Combined).
  * Generic PC: Debian or Ubuntu-based Linux distributions.
* **Hardware**: Raspberry Pi 4 with 2GB RAM (single 1080p display recommended initially), or an x86_64 PC, plus a TV or monitor for Kiosk/Combined mode.
* **Environment**: The installer targets a non-graphical (CLI) fresh OS install. For Kiosk/Combined mode it installs and configures its own minimal window manager (Openbox) and display server (X11) — you don't need a desktop environment pre-installed.

## Installation

**1. Prepare the OS**

Start with a fresh install of Raspberry Pi OS or Ubuntu/Debian.

**2. Download Files**

Place `app.py`, `install.sh`, `version.txt`, `requirements.txt`, and the `templates/` and `static/` folders together in a directory (e.g. `/home/pi/scoreboard`).

**3. Run the Installer**

```bash
chmod +x install.sh
sudo ./install.sh
```

**4. Choose Your Mode**

- **Server** — No display, headless data backend other kiosks point to.
- **Kiosk** — Display-only client that points to a server (or runs standalone).
- **Combined** — Server and display together on one machine — the simplest single-TV setup.

## Accessing the Settings Page

Once installed, find the device's IP address (`hostname -I` on the Pi, or check your router's connected-devices list), then open a browser to:

| Mode               | Default Port | Settings URL                          |
|---------------------|:---:|----------------------------------------|
| Server              | `5000` | `http://<device-ip>:5000/settings`  |
| Combined            | `5000` | `http://<device-ip>:5000/settings`  |
| Kiosk               | `5001` | `http://<device-ip>:5001/settings`  |

**Default login is `admin` / `root`** — change this immediately from the Settings page (Admin Credentials section) once you're in.

Use your router's DHCP device list or `hostname -I` to find the device. The revised
installer preserves existing DHCP/Wi-Fi configuration and does not assign a fallback
static address or change network managers.

## Quality control and safe physical testing

See [QC_REPORT.md](QC_REPORT.md) for the exact changes, automated/browser/live-feed
results, Raspberry Pi validation checklist, and selective installation/rollback
instructions. This candidate is ready for physical testing; a 24–48 hour test on
the target 32-bit Raspberry Pi 4 is still required before unattended use.

## Clock settings and testing before installation

In Settings, next to Timezone, choose **Clock** → **12-hour**, **24-hour**, or
**Hidden**, then save. Midnight is `12:00 AM` / `00:00`; noon is `12:00 PM` /
`12:00`. Hidden removes both the clock and its separator, leaving the display name
and weather visible. Existing configurations default to 12-hour time. The clock
uses the selected timezone; paired kiosks use their own clock and timezone settings.
Changes apply on the next normal feed refresh (up to 30 seconds), or immediately
when the display page is reloaded.

The clock adds no Python packages, browser libraries, services, or build step.
It uses Chromium's built-in JavaScript APIs and caches its timezone formatter.
It is intended for Raspberry Pi 4 with 2GB RAM and 32-bit Raspberry Pi OS, but
hardware/OS-specific validation must be performed on that target. Node.js is only
needed to run development tests, not to run the scoreboard or kiosk.

Before installing on a Pi, test in a separate development checkout on a computer:

```bash
python3 -m venv /tmp/scoreboard-test-venv
/tmp/scoreboard-test-venv/bin/python -m pip install -r requirements.txt
/tmp/scoreboard-test-venv/bin/python -m unittest discover -s tests -v
node tests/clock.test.js
/tmp/scoreboard-test-venv/bin/python app.py
```

Run these commands from the project directory. Use Node.js 18 or newer for the
JavaScript tests. The Python tests use temporary configuration files and mock
external requests; they do not contact or modify a Pi. Formatting tests cover
midnight, noon, minute boundaries, hidden/display transitions, timezone conversion,
and daylight saving time. Integration tests cover persistence, legacy defaults,
retention of other settings, and paired-kiosk overrides.

For a manual check, open the development server on port 5000, sign in to Settings,
and save each clock option. Reload the display and confirm each format, hidden
clock/separator behavior, and persistence after restarting the development server.
Confirm favorite teams, live scores, logo slides, and slide rotation still behave
as expected. Live-feed checks require ESPN access; passing offline tests alone does
not validate live feeds. Kiosk startup scripts are unchanged. Do not run the host
installer or copy these changes onto an existing Pi until you have reviewed and
tested them. No Pi installation is modified by these development checks.

## Google Chrome Troubleshooting (x86_64)

On PC-based Linux (x86_64), the script prefers Google Chrome for kiosk stability, while Raspberry Pi (ARM) always uses Chromium.

**If Chrome fails to install:**

**Manual Download** — If the installer can't find the `.deb` file, download it yourself:

```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
```

**Placement** — Put the `.deb` file in the same folder as `install.sh` before running it.

**Dependency Fix** — If you see "broken packages," run:

```bash
sudo apt --fix-broken install
```

**Fallback** — If Chrome still isn't found, `install.sh` automatically falls back to `chromium-browser`.

## Service Management

```bash
# Check status
sudo systemctl status scoreboard.service

# Restart after config changes
sudo systemctl restart scoreboard.service

# View live logs
sudo journalctl -u scoreboard.service -f

# Stop the service
sudo systemctl stop scoreboard.service
```

On Kiosk/Combined installs, the browser itself is managed separately:

```bash
# Check kiosk browser status
sudo systemctl status kiosk.service

# Restart the kiosk browser
sudo systemctl restart kiosk.service

# View kiosk browser logs
sudo journalctl -u kiosk.service -f
```

## How It Works & Tips

### Pairing Kiosks

On the Server's Settings page, generate a one-time "Pairing Code" (valid for 10 minutes). Enter the Server's URL and that code on the Kiosk's Settings page to securely link it to the Server's data feed.

### Local Schedules

Go to Settings → Local Schedule and paste the URL of your school's or league's athletics page (or a MaxPreps link). The app automatically detects the feed type (Thrillshare, MaxPreps, iCal, or RSS) and pulls in upcoming games.

### Display Control

The app uses `xset` to control the TV over DPMS/HDMI-CEC for the scheduled "Power On/Off" feature, and `unclutter` to keep the mouse cursor hidden on kiosk displays.

## Troubleshooting

* **Apache2 "It Works!" Default Page Instead of the Scoreboard** — That page belongs to Apache2, not this app. The scoreboard listens on port `5000` (Server/Combined) or `5001` (Kiosk), not port 80 — browse to `http://<device-ip>:5000/` instead of the bare IP. If Apache2 isn't needed on that machine, remove it with `sudo systemctl disable --now apache2 && sudo apt purge -y apache2`.
* **Black Screen on Boot** — Check `systemctl status kiosk.service`. Make sure graphics drivers are installed if it can't open the display.
* **Unstyled / Broken-Looking Page** — Confirm `static/css/main.css` exists under the install directory; re-run `install.sh` if it's missing.
* **Data Not Updating** — Check backend logs with `journalctl -u scoreboard -f` and verify the machine has internet access to reach ESPN's APIs.
* **Sudo Errors** — The app needs specific `NOPASSWD` entries in `/etc/sudoers.d/scoreboard` to control the display and services from the web UI. These are created automatically by the installer.

## Screenshots

| | |
|---|---|
| ![Scoreboard](Images/scoreboard.png) | ![Scoreboard](Images/scoreboard%202.png) |
| ![Scoreboard](Images/scoreboard%203.png) | ![Scoreboard](Images/scoreboard4.png) |
| ![Scoreboard](Images/scoreboard6.png) | ![Scoreboard](Images/scoreboard7.png) |
