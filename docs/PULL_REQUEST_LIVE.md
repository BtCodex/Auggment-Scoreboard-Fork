# Prepared pull request: live trackers and independent bars

Base: `improve/scorecard-details-and-android`

Head: `improve/live-game-trackers-and-bars`

[Compare and create the PR](https://github.com/BtCodex/Auggment-Scoreboard-Fork/compare/improve/scorecard-details-and-android...improve/live-game-trackers-and-bars?expand=1).

Title: **Add compact live field/base trackers and independent top-bar switches**

---

Live football/MLB scorecards lacked current field/base state, and the name/clock
could only be controlled together. This change adds compact source-backed widgets
and independent persistent mobile switches while retaining the existing records,
period tables, catalogs, favorites, artwork and display modes.

- Strict current scoreboard-only parsing: football possession/down/yard line and
  real game clock, plus MLB explicit base occupancy/inning/outs/current score.
  Field direction is normalized offense-right, not guessed stadium direction.
  Missing/inconsistent/inactive state hides the widget only.
- Actual-fetch timestamps/signatures, 90-second expiry, kiosk transit deduction,
  outage clearing and browser expiry prevent retained scores becoming stale live
  field/base claims. No new provider requests, dependencies or worker processes.
- Separate time and title/weather controls, preserved clock format and timing
  choices, actual CSS visibility fixes and collapsed empty headers in ticker mode.
- Tests and packaging/install documentation include all assets. The prior complete
  2026 college/NFL catalog and server-connected Android APK are unchanged.

Validation: 275 Python tests, 53 JavaScript tests, 28 Android policy checks, three
integrated Chromium suites, syntax/targeted lint/dependency checks and real release
packaging passed locally. Browser coverage includes six sizes, 36 bar/clock/mode
cases, outages/expiry and existing favorites/rotation/details regressions.

96-game cloud cached-render benchmark: 18.481 ms median, 27.433 ms p95, 44,648 KiB
process RSS high-water; this excludes Chromium and is not a Pi/soak measurement.

Direct current ESPN live verification is blocked by HTTP 403. Positive live
fixtures are mocked. Physical Pi/Android tests and a 24–48 hour soak remain
required; this is a physical-test candidate. No Pi or working installation was
accessed or changed. Follow `docs/INSTALL_AND_ROLLBACK.md`, not the old pre-module
updater. See `docs/LIVE_WIDGETS_UPDATE.md` and `docs/LIVE_DATA_SOURCES.md`.
