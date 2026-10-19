# Prepared pull request

Base: `improve/pi-scoreboard-reliability`  
Head: `improve/scorecard-details-and-android`

[Open the comparison and create the PR](https://github.com/BtCodex/Auggment-Scoreboard-Fork/compare/improve/pi-scoreboard-reliability...improve/scorecard-details-and-android?expand=1).

The branch and APK were pushed successfully. Automatic PR creation was blocked by
Forbidden responses from both GitHub GraphQL and the repository-scoped REST API in
this cloud environment. No PR is claimed to exist. Use the title and body below.

Title: **Add detailed scorecards, complete football catalogs, and Android viewer**

---

The team picker could become empty during provider failures, records disappeared after kickoff, and scorecards lacked period details. This update adds complete 2026 football baselines, compact period tables and persistent header controls while preserving existing favorites, artwork and display modes. It also provides a small server-connected Android viewer and a compiled sideload test APK.

- Includes all 75 requested ACC/Big Ten/Big 12/SEC/Pac-12 football schools, Notre Dame independently, and all 32 NFL franchises. Metadata is cross-checked against published 2026 ESPN/CFBD snapshots; direct provider reads were blocked by the cloud proxy.
- Corrects SEC/Pac-12 filter IDs with a versioned migration, retains legacy abbreviation aliases, and fixes escaped Texas A&M identity keys in settings.
- Displays supplied records, quarters/halves/innings, overtime and MLB R/H/E. Missing values stay unavailable. Background enrichment is bounded, cached, persisted and scheduled fairly; game totals remain from the scoreboard source.
- Adds Always Show/Always Hide/Automatic header settings, responsive tables and modest logo alignment/size improvements.
- Adds a dependency-free Java WebView APK with URL setup, fullscreen display, bounded initial reconnect, maintenance controls and renderer recovery. The server remains required. Standalone Android and universal automatic boot launch are not implemented; physical Android tests remain required.

Validation: 234 Python tests, 34 JavaScript tests, 28 Android policy checks, both integrated Chromium suites, Python/Bash/Node syntax, targeted Ruff, pip check, actual release packaging, full Android APK build, v1/v2/v3 signing and zip alignment passed locally. Browser checks cover six screen sizes, every header/display-mode choice, team selection, missing/extra periods, outage recovery and repeated renders. Remote CI status is not claimed.

The 96-game/96-period-table cloud benchmark measured 14.325 ms median backend render+JSON and 39,160 KiB RSS high-water; this excludes Chromium, network and SD writes and is not a Pi/soak measurement.

**Upgrade requirement:** use the reviewed manual-copy procedure on a spare/cloned SD card for this transition. The previous installed updater cannot copy the new `score_details.py` and catalog; replacing only app.py can prevent startup. Rollback must restore original settings as well as code because filter IDs migrate. No Raspberry Pi or existing installation was accessed or changed.

See `docs/UPDATE_REPORT.md`, `docs/INSTALL_AND_ROLLBACK.md`, `docs/TEAM_COVERAGE_2026.md`, and `docs/ANDROID_VIEWER.md`. The actual test APK and SHA-256 are in `android/artifacts/`. Physical Pi/Android boot, actual custom-logo appearance, live summary shapes and 24–48 hour soak testing remain outstanding; this is a physical-test candidate, not a production-readiness claim.
