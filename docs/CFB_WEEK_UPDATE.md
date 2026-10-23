# Complete weekly CFB rotation, scorecard filters and update packages

Version **1.5.0-dev**, branch `improve/complete-weekly-cfb-rotation`, based on
`d127602` from `improve/live-game-trackers-and-bars`. Changes are in
`BtCodex/Auggment-Scoreboard-Fork`; the original upstream repository is untouched.
No Raspberry Pi, home-network device, working installation or OS was accessed or
modified. This is a controlled physical-test candidate, not a 24/7 readiness claim.

Implementation commit `3c50eb3` and the runtime ZIP are pushed. A fresh download
from GitHub returned the expected 152,899 bytes and matching SHA-256. Automatic
PR creation returned Forbidden from both GraphQL and REST; no PR was opened.
[The prepared comparison and description](PULL_REQUEST_CFB.md) are available.

## Complete coverage and chronological rotation

**All Power 5 Games** is the new default CFB coverage mode. Every current-week
game involving a 2026 ACC, Big Ten, Big 12, SEC or rebuilt Pac-12 football team,
plus independent Notre Dame, qualifies without selecting favorites. G5/FCS
opponents qualify when the other participant is eligible. Eligibility uses the
audited ESPN team IDs; no guessed conference number or ranking substitutes for
membership. The catalog remains 75 conference schools plus Notre Dame and all
32 NFL franchises; existing team selections are not erased or automatically added.

The backend retrieves FBS group **80**, **limit 1000**, selects the provider's
official season/type/week from calendar metadata, and always requests that exact
week explicitly. It does not trust a potentially featured bootstrap slate as
the whole schedule. Games must match the selected year, season type and week.
No arbitrary rolling date window prunes early completed games or long bowl weeks.
The official metadata is included in the bounded offline snapshot.

Real archived ESPN calendar review caught a misleading `leagues[].season` on
historical requests; selection uses root season metadata. Minute-precision week
end times, overlapping CFP/Bowls entries, January belonging to the previous
football season, invalid metadata and malformed competition containers are covered.
Absent/ambiguous week metadata produces an honest waiting warning, not a guessed
week. Fetch failures retain the previous coherent slate and identify it as saved.

Cards deduplicate by ESPN event ID and sort by actual kickoff timestamp with a
stable event-ID tie break. Status, score, favorites and rankings do not reprioritize
CFB games. Official kickoff corrections can update their chronological position.
Slide identity now uses league + ESPN event ID, so abbreviation changes and score
refreshes preserve the active card. The complete CFB block is inserted once in
custom playlists: favorite entries cannot reorder, omit or duplicate its games.
Rotation completes and wraps last-to-first without a 15/20-game cap.

Favorite highlighting, AP badges, records, period/inning tables, live detail
widgets, custom logo/uploads, colors, dark design, ticker, other sports and kiosk
behavior remain. **Favorites & priority matchups** is available as the legacy
coverage option. CFB full-week selection intentionally overrides narrower manual
conference/date windows; choosing favorites mode restores that selection model.

## Main-scorecard filter

New persisted phone controls:

| Setting | Choices/default |
| --- | --- |
| College football coverage | All Power 5 Games (default), Favorites & priority matchups |
| CFB refresh | 180 seconds default; configurable 30–900 |
| Scorecard display filter | Live, Upcoming, Both (**default Both**) |
| Include completed games | Independent checkbox; **default off** |

Live includes in-progress, halftime and overtime. Upcoming includes scheduled
games. Completed games are added independently of the selected mode when enabled.
Canceled, postponed, delayed and unknown states are not falsely classified as
live/upcoming/final. Filtering is a stable subsequence of the existing kickoff
order and reevaluates from refreshed provider status. **Only team game scorecards
are filtered; bottom ticker data is unchanged by these controls.** Racing/golf
leaderboard views keep their existing behavior.

For the whole eligible weekly schedule, use **Both + Include completed games**.
The latest requested default intentionally shows only live/upcoming games.
When no games match, an explanatory slide remains available even alongside custom
logo/special slides. A clear connection/week warning identifies source failures.

Defaults apply when older settings lack these fields. Saved preferences survive
new Python processes and are validated before atomic writes. Existing CFB/NFL/day
display selection remains independent: NFL-only still hides college football.

## Reliability and source limits

CFB fetches use two shared cached URLs (calendar bootstrap + explicit week), normally
at most once each per 180 seconds, with existing timeouts and failure backoff.
Recent paired displays share the fastest requested permitted interval. Changing
coverage or waiting clients cannot keep expired complete-week demand alive forever.
Provider freshness limits scoring; there is no instantaneous-score claim.

Field/base widgets retain their stricter 90-second actual-fetch expiry. At a
180-second CFB interval they can hide between fetches; select 30 seconds if desired.
No runtime dependency, worker process or heavy rendering library was added.

Paired kiosks retain all game states before applying their own scorecard filter,
so offline Live/Upcoming/completed changes do not discard cached games. An offline
coverage change requiring different discovery is saved and visibly pending until
reconnection; the API retains the actual cached coverage mode. A mixed-mode
backend serving any complete-week display retains that current CFB week, so a
simultaneous Favorites display cannot also fetch games outside that week. Separate
broader CFB date-window caches are deferred; the single-Pi complete-week setup is
not dependent on that capability.

**October 24, 2026 provider comparison remains unverified.** Current ESPN API/web
requests are blocked by the cloud proxy with HTTP 403. The accessible published
2026 ESPN-derived schedule contains only weeks 1–7 through October 18. It cannot
prove the two requested Texas A&M–Alabama/Ole Miss–Texas event IDs, actual kickoff
times or full eligible count. Positive October 24 rotation fixtures are explicitly
synthetic; no real schedule or scores were invented. See the exact source URLs,
hashes and required later comparison in [the source audit](CFB_WEEK_SOURCE_AUDIT.md).

## Exact local validation

| Executed | Result |
| --- | --- |
| Python unittest discovery, Python 3.12/x86_64 | **325 passed**, zero failed/skipped |
| JavaScript unit tests, Node 24 | **66 passed**, zero failed/skipped |
| Baseline Chromium suite | Passed: six settings sizes, five display sizes, normal rotation, 100 refreshes, score flashes, outages, logos/empty slate, clock, modes and escaping |
| Existing details/team Chromium suite | Passed: 76 CFB/32 NFL choices, phone selection, 18 header cases, four sports' tables at six sizes |
| Existing live-widget Chromium suite | Passed: 36 bar/clock/mode cases, six sizes, NFL/CFB/MLB widgets, outages and expiry |
| New CFB Chromium suite | Passed: phone coverage/filter/completed persistence, all 45 synthetic games exactly once, kickoff/tie order, full traversal with 12 mid-rotation refreshes, stable DOM/key, failure/recovery, genuine timer wrap and empty main cards with visible ticker |
| Browser uncaught JavaScript exceptions | Zero |
| Manual ZIP copy block | Executed with unprivileged command stubs: no `.git`, settings/media/startup files unchanged |
| ZIP installation compatibility | Actual original upstream 1.3 extraction and current updater installed all files and preserved seeded private/startup data; installed Flask runtime/API/page/static smoke checks passed |
| Package integrity | Reproducible ZIP, source-byte identity, manifest recognition and checksum checks passed |
| Other checks | Python compilation, targeted Ruff undefined-name checks, Bash/Node syntax, pip dependency check, real release packaging/manual-runtime-file tests passed |
| Actual current ESPN full-week list/count equality | Could not run: HTTP 403 |
| Physical Pi/ARM/32-bit, Android devices, boot and 24–48 hour soak | Not run |

Regression tests exposed and fixed real settings overflow at 844×390; sections,
pairing controls and kiosk forms now wrap without hiding overflow. Kiosk forms
were additionally checked at 681px and 844px. Other fixes include raw Texas A&M
playlist identity, invalid shared week retention and misleading offline coverage.
All local failures were resolved. Remote CI and hardware compatibility are not
inferred from these local results. The unchanged server-connected Android viewer
continues to use the server's assets; no Android rebuild/device test is claimed.

Reproduce with `python -m unittest discover -s tests -v` and each `tests/*.test.js`
using Node. Start `python tests/serve_qc.py` for the four Playwright browser scripts;
the CI workflow contains the exact commands. The fixture uses temporary private
settings/uploads, mocked sports data and blocked external requests.

## Files and installation deliverables

- `app.py`, new `cfb_week.py`: official-week retrieval, eligibility/caching/offline
  metadata, state filters, kiosk behavior and required-module update validation.
- `static/js/display.js`, `templates/index.html`: stable identity and complete
  chronological playlist block, filtered empty messages and source warnings.
- `templates/settings.html`, `static/css/main.css`: saved mobile controls and
  layout corrections, preserving the existing display design.
- `install.sh`, release/CI workflows: include the new module and regression suites.
- `scripts/build_update_package.py`, `artifacts/`: actual runtime-only update ZIP,
  manifest, checksum and reproducible builder. `requirements.txt` is unchanged.
- New week/coverage/filter/distribution/install tests plus compatibility updates
  to existing fixtures, guides and synthetic previews.

**Try the ZIP update first:** [download and compatibility notes](UPDATE_PACKAGE.md)
and [beginner terminal backup/copy/restart/rollback commands](ZIP_UPDATE.md).
The 17-file package is **152,899 bytes**, SHA-256:

`b167c4c0a0792b19b8e1409700fe82044d3f7f3af7b03e058b1fd53f17e56ebd`

It omits device data, images, installer/launcher scripts, units and desktop files.
The original upstream 1.3 extractor and new updater are tested. Unknown/intermediate
filtered updaters need the safe manual route once; universal compatibility is not
claimed. No dependencies need upgrading when the existing imports succeed.

**Clean backup option:** [fresh 32-bit Pi OS + git clone/install and future git pull](FRESH_PI_INSTALL.md).
Both routes document full private backups and restoration of settings with code.
Do not rerun the OS installer over the working installation for a file update.

Synthetic previews: [rotation](screenshots/cfb-week-rotation.png) and
[phone settings](screenshots/cfb-week-phone.png). They do not show the user's real
logo or assert real October 24 results. Before unattended operation, complete the
physical checks and provider comparison in the guides.
