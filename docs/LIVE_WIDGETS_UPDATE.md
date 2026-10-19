# Live trackers and independent bars — 1.4.1-dev

Candidate: `improve/live-game-trackers-and-bars`, based on
`improve/scorecard-details-and-android` at `a8b1e45`.
No Raspberry Pi or existing installation was accessed, changed or deployed to.
This is a candidate for controlled physical testing, not a 24/7 readiness claim.

## What changed

- Compact live NFL/CFB field below the score: possession, normalized ball
  position/direction, down/distance, yard line, period/clock and red-zone/goal-to-go.
  MLB gets a compact diamond, explicit occupied bases, inning/half, outs and score.
  These are static source snapshots, without animation loops or per-game requests.
- Missing, conflicting, malformed, inactive or stale data hides only its widget.
  Actual-fetch timestamps/signatures prevent cache hits, offline snapshots,
  settings changes or kiosk forwarding from reviving old ball/runner state.
  Widgets expire within 90 seconds of fetch even when browser requests hang.
- Separate **Show top time bar** and **Show top name/title bar** phone switches.
  Preferences persist atomically and work without restarting in every display
  mode. Title also controls weather. Disabling both reclaims header space.
  Existing 12-hour/24-hour/hidden clock and timezone remain independent.
  Changing either switch selects Always Show, preventing the old timed hiding;
  Automatic and Always Hide remain available explicitly. Existing saved timing
  choices are preserved until changed.
- Fixed CSS overriding hidden title elements and ticker-specific styling leaving
  an invisible header gap. Browser regressions now assert actual visibility and
  dimensions, not only attributes.
- Review fixed accidental goal-to-go detection from words such as “field goal,”
  impossible distances, conflicting/malformed clocks, and absent MLB scores.
- Isolated helper modules, deterministic tests, browser tests, release/manual-copy
  asset checks, reproducible benchmark, screenshots and updated installation guide.
  Version bump prompts connected displays to reload the changed assets.

Existing records, quarter/half/inning/overtime tables, enlarged/raised logos,
AP badges, live scoring, favorite selection/deduplication, weekday football
filters, logo slides/uploads, colors, rotations, three display modes, kiosk
services and the Android viewer are retained. No runtime dependency was added;
installation scripts/systemd units and the user's uploaded logo were not changed.

## Team coverage and platforms

The existing audited catalog still contains **all 32 NFL franchises**, plus
**75 football schools** in the requested 2026 grouping: ACC 17, Big Ten 18,
Big 12 16, SEC 16, rebuilt Pac-12 8; Notre Dame is separate (76 CFB choices).
All 138 FBS memberships support the conference filters. The already completed
expansion is preserved; schools/favorites were not removed or silently enabled.
See [the full names/ESPN IDs, membership sources and limits](TEAM_COVERAGE_2026.md).

The existing [test APK and Android instructions](ANDROID_VIEWER.md) remain valid:
the native viewer displays these updated assets from the Flask server. It is a
**server-connected WebView**, requiring the Pi or another server. Android phones,
Android TV/Shield and Android-based Fire OS are feasible sideload targets with a
modern WebView; actual devices are untested. Vega OS Fire TV does not run APKs.
No standalone Android data/backend port or universal automatic boot launch is
claimed. No Android code/build change was needed for this server-side update.

## Validation

| Executed locally | Result |
| --- | --- |
| Python unittest discovery, Python 3.12/x86_64 | 275 passed, 0 failed/skipped |
| JavaScript unit tests, Node 24 | 53 passed, 0 failed/skipped |
| Android pure Java URL/retry policy | 28 passed; existing APK unchanged |
| Existing Chromium baseline suite | Passed; rotation, scores, outages, logo/empty state, mobile controls and 100 repeated refreshes |
| Existing Chromium details/team suite | Passed; 76 CFB/32 NFL choices, SMU/A&M selection, 18 header timing/mode cases and four sport tables at six sizes |
| New Chromium live suite | Passed; phone persistence, 36 bar/clock/mode cases, actual visibility/empty header dimensions, NFL/CFB/MLB widgets at six sizes, inactive/malformed cases, outage retention/recovery and timer expiry |
| Browser JavaScript exceptions | Zero uncaught errors |
| Syntax/dependencies | Python compileall, targeted Ruff, Bash/Node checks and pip check passed |
| Actual release packaging/manual-copy file checks | Passed; both new widget assets included, device state excluded |
| Real current ESPN live state | Blocked by outbound HTTP 403; not verified |
| Physical Pi, Android devices/emulator, extended soak | Not run |

Initial tests found compatibility expectations for older kiosk payloads and two
CSS visibility issues; those were corrected and relevant tests rerun. Current
checks above have no unresolved failures. Remote CI/ARM/32-bit results are not
claimed. Archived final-game observations are documented separately from mocks
in [data sources and tradeoffs](LIVE_DATA_SOURCES.md).

Reproduce the offline checks from the checkout with the installed Python runtime:

```bash
python -m unittest discover -s tests -v
node tests/clock.test.js
node tests/display.test.js
node tests/rank_badges.test.js
node tests/scorecard_details.test.js
node tests/live_widgets.test.js
```

For browser checks, install the development-only Playwright package and Chromium,
start `python tests/serve_qc.py`, then run the three `tests/browser_*.cjs` scripts
with `NODE_PATH` pointing to Playwright. The fixture uses temporary settings and
mock images; it does not read a real Pi. Exact commands are in the CI workflow.

## Measured performance and estimates

[The reproducible benchmark](benchmarks-live-widgets.json) uses 96 synthetic cached
live games, 96 period tables, 48 football trackers and 24 MLB trackers; 300 backend
builds plus compact JSON: **18.481 ms median, 27.433 ms p95, 30.384 ms maximum**.
Response: 121,722 bytes. Process RSS high-water: 44,392 → 44,648 KiB. Retained
traced heap after 50 further builds: 72,831 bytes. Zero external requests.

These are cloud x86_64 figures, excluding Chromium, network, image loading and SD
writes; the short benchmark cannot establish leak-free 24/7 behavior. For planning
only, estimate 60–150 MB backend RAM and 300–800 MB Chromium RAM for one 1080p
display, plus OS memory. Actual ARM/32-bit memory/CPU/thermal behavior must be
measured; avoid many browser tabs or two independent heavy displays initially.

## Previews and later installation

These screenshots use synthetic games and colored logo tiles, not the user's
artwork or actual sports results:

- [CFB field, desktop](screenshots/scoreboard-live-cfb-1920.png)
- [MLB diamond/innings, phone](screenshots/scoreboard-live-mlb-390.png)
- [NFL field, ultrawide](screenshots/scoreboard-live-nfl-2560.png)

Use [installation and rollback](INSTALL_AND_ROLLBACK.md) on a spare/cloned card.
It identifies the candidate branch, backs up private state, copies all runtime
files including the two new widget assets, preserves settings/uploads/session
key, verifies startup and restores code **and settings** on rollback. Do not use
the old pre-module one-click updater for this transition.

Before unattended use, follow [the physical checklist](PHYSICAL_PI_CHECKLIST.md):
cold boot online/offline, real ESPN fields/base changes, bar persistence/reboot,
actual custom logo, outage recovery, phone/HDMI layout and a 24–48 hour soak with
RSS/CPU/temperature/restart measurements. See [the prepared PR](PULL_REQUEST_LIVE.md).
