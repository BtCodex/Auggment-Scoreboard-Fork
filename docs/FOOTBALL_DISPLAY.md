# Football display and AP rankings

In **Settings → Football display → Show football games**, choose:

| Option | Football shown |
| --- | --- |
| CFB and NFL | Both leagues every day; the compatible default |
| College football only | CFB every day |
| NFL only | NFL every day |
| Automatic | CFB on Saturday, NFL on Sunday, both Monday–Friday |

Tap **Save**. Changes apply on the next display refresh without restarting the
server or kiosk. Automatic mode checks the calendar in the configured timezone
(default America/Chicago), including daylight-saving changes. A midnight switch
appears on the next browser refresh, normally within about 30 seconds.

This setting filters both rotating scorecards and ticker games in all three display
modes. Other enabled sports, uploaded artwork, favorite teams, league selections,
date windows and playlist preferences remain saved. It does not enable an otherwise
disabled league: select CFB/NFL under leagues or enable football priority. Both
leagues continue using the shared source cache so switching back is immediate when
cached games are available. A paired kiosk retains both leagues and can change its
filter while disconnected from the server; saved data remains marked stale.

Ranked CFB teams show a **#1–#25 badge beside their logo** in scorecards and the
ticker. Rankings come from ESPN's explicitly identified **AP Top 25** poll, matched
by team ID and season. These are the latest available AP rankings, including on
recent final-game cards; they are not historical rankings at kickoff. The existing
curated rankings still help prioritize games, but are never relabeled as AP.

The background AP lookup normally runs at most hourly when CFB is enabled or
requested. Timeouts or malformed replies retain the last verified poll and retry
after 5, 10, 20, 40, then 60 minutes; numeric provider Retry-After instructions can
extend that delay. Valid polls are included in the existing atomic score snapshot
for offline restarts. An unranked team, missing poll, unknown season or mismatched
season gets no badge. Rankings requests do not run during page rendering or block
successful score updates. No additional runtime dependencies are required.

## Test before installation

In the development checkout with Python dependencies installed:

```bash
python -m unittest discover -s tests -v
node tests/clock.test.js
node tests/display.test.js
node tests/rank_badges.test.js
```

Optional Chromium suite (isolated mock scores/settings, no Pi or real sports calls):

```bash
python tests/serve_qc.py
# In a second terminal after installing development-only Playwright:
NODE_PATH=/tmp/scoreboard-qc/node_modules node tests/browser_qc.cjs
```

The test fixture uses colored raster logo tiles and a mock #7 AP ranking. It never
replaces your actual artwork. See [installation and rollback](INSTALL_AND_ROLLBACK.md)
before using a cloned or spare Pi SD card for physical tests. No installation or
deployment was performed as part of these changes.

On the test Pi, verify each manual filter, automatic switching across local midnight,
AP badges with actual team logos, persistence after reboot, and an internet outage.
Actual Pi boot, ARM performance and extended 24/7 operation still require hardware
testing.
