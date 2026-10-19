# Auggmented Scoreboard improvement and quality-control report

Branch: `improve/scorecard-details-and-android` (based on `improve/pi-scoreboard-reliability`).

The latest implementation and exact validation results are in
[the scorecard/coverage/Android update report](docs/UPDATE_REPORT.md): 234 Python
tests, 34 JavaScript tests, 28 Android Java policy checks, both Chromium suites,
and an actual signed server-connected APK. Read its manual-upgrade requirement
before installation; the older updater cannot copy the newly added module/catalog.

**Ready for controlled physical testing; not verified for unattended 24/7 use.**
All work was done in the development repository. No access, deployment, uninstall,
service change or modification of the actual Raspberry Pi occurred.

## Latest additions: football display and AP rankings

- Phone-accessible CFB/NFL/both selector plus automatic Saturday CFB, Sunday NFL,
  weekdays both. Uses the configured timezone and DST; preferences persist.
- Filters cards and ticker without deleting favorites, other sports or artwork.
  Paired kiosks retain both leagues so offline settings/midnight switches work.
- Verified AP Top 25 badges beside ranked CFB team logos in cards and ticker.
  An explicit AP poll lookup replaces unidentified curated ranks for these badges;
  existing curated rankings remain available for game prioritization. Poll requests
  are normally hourly, with bounded retry/backoff and retained snapshot recovery.
- Badges show the latest available AP poll for the matching season, including on
  final-game cards. They do not claim historical rankings at kickoff. Missing AP
  data/season or unranked teams produce no badge. No extra runtime dependencies.
- Added 16 football-display tests, 14 AP tests, 3 JS rank tests and browser checks
  for phone saves, filtering and logo-adjacent rank bounds. See
  [football controls and testing](docs/FOOTBALL_DISPLAY.md).

## Improvements and confirmed bugs fixed

### Clock and schedules

- Default 12-hour AM/PM and America/Chicago, selectable 24-hour/hidden clock.
- Intl.DateTimeFormat uses explicit en-US h12/h23 cycles; no manual hour arithmetic.
  Midnight is12:00 AM/00:00 and noon12:00 PM/12:00. Game clocks are kept separate.
- Proper timezone/DST conversion for scores, manual schedules, RSS and iCal TZID.
  Date-only items stay calendar dates; unknown times are not invented. Ambiguous
  or nonexistent local schedule times are rejected rather than guessed.
- Stored preferences survive a fresh Python process/restart. Native phone schedule
  input widgets follow browser locale. RSS publication times are labeled Published.

### Scores, caching and recovery

- Configurable live/upcoming/idle/final defaults 30/300/900/3600 seconds. Browser
  updates at a bounded cadence after a completed request. Provider source cadence
  still determines freshness; scores are not claimed to be instantaneous.
- Shared bounded 512-entry response cache, per-league date windows, requested-kiosk
  window union, connection/read timeouts, exponential 30–900 second failure backoff,
  and Retry-After handling. Live request floors are 30 seconds.
- Good cached days can update while failed days retain prior events; malformed or
  failed responses do not erase a successful slate. Pruned/bounded league state.
- A private atomic sports snapshot restores marked-stale scores after offline boot.
  Writes are throttled to five minutes and unchanged scores do not rewrite the SD.
- Local calendars/RSS are parsed by at most 2 background workers, with 64 cached
  source/timezone combinations,50 items/source,5-minute TTL and error backoff. Slow
  calendars no longer block sports responses; manual events remain immediate.
- Correct scheduled/live/halftime/overtime/final/canceled/postponed/delayed/unknown
  states. Missing scores use an em dash. No synthetic zeros, missing kickoff times,
  or fake NASCAR race dates. NASCAR events retain stable identity for saved caches.
- Game/event deduplication avoids repeated cards/ticker entries when both favorites
  match. Changed kickoff times use stable event identity. PGA multi-day/weekend and
  final-event retention corrected; canceled golf/racing is not mislabeled final.
- A&M, SEC, Top 25 and NFL priority is optional. Existing favorites/leagues remain;
  new installs include A&M/Texans/Astros/Rockets and the prioritized league set.
  More than 200 legacy favorites no longer vanish on read. Actual supplied ranks,
  records and team logos remain. Custom playlist order takes precedence.

### Display and mobile management

- Traditional full-screen scorecards, horizontal LED ticker, and existing hybrid
  layout. Modes, clock, colors and timing apply without a whole-page/app restart.
- Continuous logo/score/rank/status ticker, bounded score-history state, efficient
  resize/font handling, optional font loading that cannot block the display, long-name truncation, fitted landscape score columns, paused hidden-card/background animations and no ticker RAF
  in scoreboard mode. The established dark sports appearance remains.
- Optional custom logo slide, validated upload/replace/remove, independent logo
  duration, slide order, transitions and animation speed. No external white default
  placeholder; missing/invalid logo and image slides do not create blank slots.
- Responsive phone navigation/forms, visible status/errors, safe save initialization,
  native input validation and tap-accessible playlist/favorite/special reordering.
- Restore safe timings resets only clock format/mode/operating timings, retaining
  timezone, favorites, leagues, colors, slides, account, pairing and all media.
- Paired kiosks apply their own presentation/date/favorite settings and explicitly
  mark retained data stale when their server cannot be reached.

### Configuration, security, installation and startup

- Atomic private settings/kiosk/registry saves; malformed nested settings rejected.
  State/media paths are anchored to the application directory, not shell CWD.
- Fixed public credential exposure, forgeable hardcoded session signing key, and
  unsafe sudo-as-password authentication. Persistent private session key; PBKDF2
  password migration; blank password retention; failed-login rate limiting;
  same-origin mutation checks; credential changes revoke other old sessions.
- Settings redact passwords/hashes/tokens and require authentication. Sensitive
  pairing/registry/update functions use admin auth or existing scoped kiosk tokens.
  Display scores remain public for LAN displays. No router/public port forwarding.
- Passive raster upload validation, dimensions/size limits, atomic file replacement,
  escaped feed/settings text and safe URLs; SVG/HTML executable uploads rejected.
- Unreviewed upstream/in-place Git auto-updates are refused. Reviewed ZIP paths,
  sizes, files and compatibility are staged; failure rolls code back, preserving
  settings/media/session/sports cache. No full-host reboot for an application update.
- Installer now copies all JS/CSS/helper/license assets, preserves user data and
  explicit mode/port, avoids world-executable settings, and backs up code/units.
  Release packaging includes the new helper/assets. Existing GPLv3 license retained.
- Backend starts independently of internet; kiosk waits for X11 and backend readiness
  beyond the previous 60-second limit. No global browser pkill or ARM --no-sandbox.
  Service ordering avoids a graphical.target cycle; restart delays 10/15 seconds
  prevent rapid loops and keep retrying late starts. Maintenance stop is documented.
- Removed risky automatic static-IP/network-manager takeover/unrelated-service
  removal/reboot behavior. Reviewed root-owned Wi-Fi helper replaces broad root
  nmcli/iw/wpa_cli privileges. Scripts support distro ARM 32/64 selection in code.

## Tests actually executed

| Check | Final result |
| --- | --- |
| Python unittest discovery |234 passed, 0 failed, 0 skipped |
| JavaScript clock tests |15 passed, 0 failed |
| JavaScript display-helper tests |7 passed, 0 failed |
| JavaScript ranking badge tests |3 passed, 0 failed |
| JavaScript scorecard/header tests |9 passed, 0 failed |
| Android Java policy checks |28 passed; signed APK compiled and verified; no device tests |
| Chromium integrated suite |All assertions passed; no uncaught JS errors |
| Phone/settings sizes |360×800,390×844,844×390,1080×1920,1920×1080,2560×1080 passed |
| Scorecard bounds/modes |Phone, portrait, landscape, ultrawide; traditional/LED/hybrid passed |
| Browser functions |Saving, football selector persistence/filtering, AP badges beside logos, all reorder controls, live settings/modes, full timing range, rotation, card/ticker highlights, logo removal, empty states, stored text escaping, unavailable fonts, and three-digit score bounds passed |
| Browser failures |HTTP 503, malformed JSON, network failure, retained display and recovery passed |
| Repeated renders |100 browser refreshes with stable slide count/bounded score history passed |
| Targeted Ruff lint |F821/F822/F823 undefined-name/control-flow checks passed |
| Syntax/dependencies |Python compileall, helper and rendered-template JS parsing, individual Bash syntax checks and pip check passed |
| Service generation |Mock launcher/helper/Server/Kiosk/Combined tests and systemd-analyze verify passed |
| Prior baseline provider reads |Previously NCAA 25 events, NFL 14, NBA 2, MLB 1, PGA 1; the latest update's direct provider reads are blocked by proxy 403 |
| Prior AP provider check |Previously HTTP 200, explicit AP poll dated 2026-10-18, season 2026, 25 ranked teams; not rerun successfully for this update |
| Physical Pi and 24–48 hour soak |Not run; required before unattended use |
| Real custom College GameDay logo |Not supplied in checkout; file preservation tested with fixtures, appearance/checksum needs Pi check |
| Actual team-logo CDN reads |Returned 403 in this environment; screenshots use colored raster fixtures, not real team/custom artwork |

The 268 deterministic Python/JavaScript tests and 28 Android checks are separate
from browser assertions.
Expected failure-injection tests log corrupt-cache/disk-full/offline messages; these
are not unresolved failures. Earlier test/implementation failures were investigated,
corrected and rerun. One useful systemd validation caught and fixed an invalid
quoted WorkingDirectory. There are no final failing required automated checks.

The GitHub CI workflow is configured for Python 3.9/3.11/3.12 and Node 20, with browser
checks on 3.12. A workflow file is not evidence those remote jobs have passed; only
the local Python 3.12/x86_64 results above are asserted here. Requirements remain
pure Python/browser-side; no new runtime package is introduced. Development lint
and browser packages stay outside Pi runtime dependencies.

Real source checks returned scheduled/final events, not an observed live scoring
play. Live/halftime/OT/canceled transitions and provider failures are deterministic
fixtures. Provider cadence/availability can still delay scores.

## Measured performance and resource estimates

These measurements were obtained before the latest football-filter/AP additions;
they are retained as the prior baseline, rather than claimed as a new benchmark.

[benchmarks.json](docs/benchmarks.json) records a reproducible offline benchmark:
96 synthetic games across 4 leagues, 96 cards, 300 measured render+JSON iterations after
20 warmups, 94,487-byte payload, zero external requests. On the cloud x86_64 host:

- Median 9.063 ms; p95 12.243 ms; max 23.210 ms per backend render+JSON operation.
- Process RSS high-water 38,640 KiB before and after the timed batch.
- Retained traced Python heap increased 6,664 bytes after 50 additional renders;
  traced peak 288,524 bytes for that separate tracing phase.

These figures exclude Chromium, provider latency, snapshot writes and SD I/O. They
are not a leak proof, a Pi benchmark, or a multi-day soak. Run
`python tests/benchmark_scoreboard.py` to reproduce; timing will vary.

**Estimates only:** allow roughly 100–250 MB for backend/cache and 300–900 MB for a
single Chromium 1080p display, plus OS/GPU/headroom. Many logos/custom images/leagues
or two browser windows can exceed this. A 2 GB Pi may be practical for one 1080p
screen, but RAM/CPU/heat must be measured on the actual device. No Pi CPU percentage,
GPU/temperature/power/SD endurance measurements were made. Keep only leagues and
custom slides you use; begin with one display and avoid giant uploaded images.

## Remaining limitations and practical boundaries

- ARM 32/64, HDMI/X11 authorization, Wi-Fi helper, real iPhone touch and actual boot
  service enablement need physical testing. Existing Wayland sessions need a separate
  migration review. Syntax/mock tests are not a physical installation.
- Independent dual-HDMI profiles are deferred. The tested data-filter foundation
  and safe plan are in [DUAL_DISPLAY_PLAN.md](docs/DUAL_DISPLAY_PLAN.md). Conference
  fetching remains centrally configured; independent kiosk conference-source variants
  are not yet implemented.
- AP-style rankings rely on ESPN curatedRank metadata; there is no separate AP poll
  verification API. Unknown ranks/times/scores are never filled with invented data.
- Optional legacy discovery/NASCAR fallback requests have provider-specific behavior;
  exhaustive live validation of every inherited league is not claimed. Normal
  selected-league refreshes remain bounded by the shared background cadence.
- Local-feed cache/workers are bounded, but inherited parsers still read full HTTP
  bodies before parsing; hostile or enormous feeds can consume more memory. Use
  trusted calendar URLs. Parsed local cache is RAM-only and initially fills in the
  background; ESPN sports snapshots persist across reboot.
- The default account remains compatible for first login and must be changed.
  HTTP LAN settings are not end-to-end encrypted; use a trusted LAN or a properly
  configured HTTPS/VPN boundary. No internet-facing hosting was configured.
- Snapshot/state writes are atomic and throttled, but reliable power, SD hardware,
  backups and a real endurance test still matter. A service port change needs an
  explicit backend/kiosk restart; ordinary display settings apply live.

## Reproduction, screenshots and installation

```bash
python3 -m unittest discover -s tests -v
node tests/clock.test.js
node tests/display.test.js
python3 -m compileall -q app.py scripts tests
ruff check --select F821,F822,F823 app.py scripts tests
bash -n install.sh
bash -n start_kiosk.sh
bash -n setup_kiosk_service.sh
```

Optional browser development setup: install Playwright 1.62.1 under `/tmp/scoreboard-qc`,
run `python3 tests/serve_qc.py`, then in another terminal run
`NODE_PATH=/tmp/scoreboard-qc/node_modules node tests/browser_qc.cjs`.
Set QC_CHROMIUM for the installed Chromium path if different. The fixture server
uses temporary private configuration, mock scores and mock raster logos, never a Pi.
Stop it with Ctrl+C. Screenshots are in docs/screenshots and were taken from fixtures; [landscape](docs/screenshots/scoreboard-qc-landscape.png), [portrait](docs/screenshots/scoreboard-qc-portrait.png), [phone](docs/screenshots/scoreboard-qc-phone.png), and [LED ticker](docs/screenshots/scoreboard-qc-led-ticker.png).

Follow [INSTALL_AND_ROLLBACK.md](docs/INSTALL_AND_ROLLBACK.md), then the
[physical acceptance checklist](docs/PHYSICAL_PI_CHECKLIST.md). Use a cloned SD card,
preserve the complete device state and custom artwork, and rehearse rollback.
Do not treat this candidate as production-ready until that checklist and soak pass.
