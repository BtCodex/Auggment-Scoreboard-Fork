# Scorecard details, team coverage and Android viewer update

Candidate branch: `improve/scorecard-details-and-android`, based on `a6ed242` from
`improve/pi-scoreboard-reliability`. Application version: `1.4.0-dev`.

The code and test APK are pushed. Automatic PR creation is blocked by Forbidden
responses from GitHub GraphQL and REST; [the prepared PR](PULL_REQUEST.md) includes
the exact title, body, base/head branches and comparison link. No PR is claimed
to have been opened.

Ready for controlled physical testing after the checks below; **not verified for
unattended 24/7 operation**. No Raspberry Pi, home-network device, services or
working installation was accessed or modified.

## Changes and bugs fixed

- NFL/CFB quarters and overtime, NBA quarters, men's college basketball halves,
  women's college basketball quarters, MLB innings/extra innings and supplied
  runs/hits/errors. Compact tables retain the main total and current game status,
  including inning/top/bottom text supplied by ESPN. Missing values display as
  `—`, not fabricated zeros; absent details omit the table. Records remain visible
  live and final and support three-digit baseball season records.
- Available scoreboard details are immediate. Missing fields queue deduplicated
  summary requests in the existing background worker: at most two requests per
  30-second pass, with 60-second live and six-hour final caching, bounded timeout,
  streamed 2 MiB response cap, exponential failure backoff and a 128-event cache.
  The final-state transition forces a final lookup. Fair scheduling prevents early
  cards from starving later games. With eight games needing summaries, a tested
  simulation updates each every 120 seconds under this budget. Main scores retain
  their existing faster refresh behavior; provider freshness still applies.
- Compact normalized summary data uses the existing throttled atomic offline
  snapshot; no player/commentary payloads or extra worker processes are retained.
- **Header Visibility**: Always Show, Always Hide, Automatic, saved from the phone
  and applied without restart. Automatic retains the prior five-minute cycle and
  full-screen ticker behavior; explicit Hide reclaims the header space. Clock
  formatting/visibility remains independent. Always Show also works in ticker mode.
- Logos enlarged about 10%, lifted slightly, aligned in equal boxes, and kept at
  their own aspect ratios with AP badges preserved. Record slots keep alignment
  when only one record is supplied. Landscape, portrait and narrow layouts tested.
- Complete offline baseline: 75 requested conference schools, independent Notre
  Dame, all 32 current NFL teams; names, ESPN IDs, abbreviations, logo URLs, colors
  and compatibility aliases. Additional provider teams remain selectable. The
  picker retains its last response and backs off after failures instead of blanking.
- Corrected SEC/Pac-12 filter IDs (8/9). Legacy saved SEC 9/Pac-12 21 selections
  migrate without changing favorites; version 2 marks the corrected schema. New
  web/kiosk requests carry that version. Legacy API callers without it retain old
  UI semantics. CFB conference filters now apply to the retained complete FBS slate
  so priority selection cannot silently bypass a conference choice. All 138 FBS
  memberships support the existing conference choices, including Group of Five.
- Fixed `TA&M` becoming `TA&amp;M` inside picker identity keys. HTML display escaping
  remains enabled. Legacy school abbreviations still match both favorites and
  selected picker rows without rewriting stored keys.
- Installer, release ZIP, new updater and manual upgrade guide include the new
  module/catalog. **The old updater cannot install this transition safely**; use
  [the manual procedure on a cloned card](INSTALL_AND_ROLLBACK.md). Rollback must
  restore the original settings as well as code because filter IDs migrate.
- Lightweight server-connected Android viewer and actual signed APK, separate from
  Pi dependencies. Fullscreen, saved URL, bounded initial retry, existing scoreboard
  outage retention, maintenance menu, origin restriction and renderer recovery.
  Boot notification is optional; universal automatic boot launch and a standalone
  Android backend are not implemented. See [Android instructions](ANDROID_VIEWER.md).

Existing clock modes/timezone, football weekday filter, favorites, Texas A&M and
Houston preferences, custom uploaded GameDay artwork, colors, slides, logo options,
traditional/LED/hybrid modes and kiosk services are preserved by the implementation
and regressions. The user's actual artwork is absent here; screenshots use mock
colored logo tiles and must not be interpreted as real games or logos.

## Validation

| Check | Result |
| --- | --- |
| Python unittest discovery | 234 passed; zero failed/skipped |
| JavaScript clock/display/rank/detail tests | 34 passed; zero failed/skipped |
| Android Java URL/origin/retry policy | 28 checks passed |
| Full Android Java/resources/D8 build | Passed |
| APK signatures/alignment/content | v1/v2/v3 signatures, zipalign, manifest/license verified |
| Existing integrated Chromium suite | Passed, including outage recovery and 100 refreshes |
| New integrated Chromium suite | Passed: phone header save/reload, 76 CFB/32 NFL choices, SMU add/remove, raw A&M selection, 18 header/mode/phase combinations, four sport period formats at six viewport sizes |
| JavaScript runtime errors in browser suites | Zero uncaught errors |
| Syntax/lint/dependencies | compileall, Bash/Node parsing, targeted Ruff and pip check passed |
| Packaging | Actual release build and manual-runtime-file regression passed |
| Real-time provider reads in this update | Blocked by cloud outbound proxy; not claimed tested |
| Physical Pi / Android devices / extended soak | Not run |

Commands are reproducible in CI and the repository's test scripts. This report
asserts local Python 3.12/x86_64 and Chromium results; configured remote CI runs
are not independently verified. Native Android lifecycle/reconnect/boot behavior
is implemented and reviewed but has not been exercised on an emulator or device.

## Source verification and limits

[The coverage audit](TEAM_COVERAGE_2026.md) lists every school/franchise and exact
retrieved source hashes. Memberships and identifiers were cross-checked against
published 2026 ESPN/CFBD snapshots and nflverse metadata. Direct ESPN and official
conference-site reads returned proxy 403, so this is secondary snapshot verification.
Actual logo downloads, current live scores across all 32 NFL franchises and real
ESPN summary shapes require an internet-enabled test environment or physical test.
Mocked live, upcoming, halftime, overtime, final and missing-data cases passed;
that does not prove the source is currently returning those states.

The APK is 37,477 bytes, SHA-256
`e6c5dbbdc4fed3123211b133a54d71a2a88bafa11c9bec031c0c4fe3e3aab0fc`.
This is package size, not RAM usage. It requires the Flask server and a sufficiently
modern System WebView. Android-based Fire OS devices are candidates; Vega OS Fire
TV devices cannot run APKs. Android/Fire OS startup restrictions require a tested
kiosk launcher/device-owner setup for unattended app launch.

## Performance

[Measured cloud benchmark](benchmarks-scorecard-details.json): 96 synthetic games,
96 period tables, four leagues, 300 measured render-plus-JSON iterations after 20
warmups, 117,831-byte response and zero external requests. Median **14.325 ms**,
p95 **19.718 ms**, max **47.466 ms**. Process RSS high-water **39,160 KiB** before
and after the measured batch. A separate 50-render tracing phase retained 13,292
additional Python heap bytes. This short measurement excludes Chromium, provider
latency, SD writes and real summary fetches, and is not a memory-leak/24-hour proof.

**Pi estimates, not measurements:** allow roughly 100–250 MB for the Python server,
300–900 MB for Chromium plus Pi OS, with one 1080p display initially. This leaves
practical headroom on a 2GB Pi depending on OS, browser version and slate size;
measure actual RSS, CPU, temperature and swap on the test card. No ARM32/ARM64 or
Android RAM/thermal benchmark has been run.

## Physical acceptance checks

Use the unchanged working SD card as rollback and test on a spare/clone. Follow
[installation and rollback](INSTALL_AND_ROLLBACK.md), not the old one-click updater.
Then verify phone selections/settings persistence, automatic boot and delayed-server
recovery, real custom logo, all display modes and orientations, 12-hour/noon/midnight,
SEC/Pac-12 filters, AP badges, actual live/final period data and outage recovery.
Run a 24–48 hour Pi soak before unattended use. For Android, separately test each
phone/Fire TV/Shield model, D-pad controls, WebView age, Wi-Fi loss, server late start,
sleep/wake, renderer recovery and the chosen boot-launch strategy.
