# Complete weekly CFB rotation, main-card filters and safe update options

Base: `improve/live-game-trackers-and-bars`

Head: `improve/complete-weekly-cfb-rotation`

[Compare and create the PR](https://github.com/BtCodex/Auggment-Scoreboard-Fork/compare/improve/live-game-trackers-and-bars...improve/complete-weekly-cfb-rotation?expand=1).

---

CFB scorecards could omit unranked/unselected games, prioritize favorites ahead
of kickoff order, and duplicate/reorder games through custom playlists. This
change adds complete provider-week Power 5/Notre Dame coverage and stable
chronological rotation, plus independent main-scorecard state filters.

- Explicit full FBS season/type/week fetch with groups=80/limit=1000; verified
  calendar selection, ID deduplication, complete-week offline retention, stable
  timestamp ties and configurable 180-second source caching. Favorites highlight
  games without restricting full coverage.
- Live/Upcoming/Both (Both default) plus separate completed-games option (off
  default); saved/validated preferences, source-driven transitions, useful empty
  slide, ticker unaffected. Paired kiosks retain all states for local filtering.
- Stable ESPN slide identity and one complete chronological CFB block regardless
  of favorite playlist order. Existing artwork/theme/records/widgets remain.
- Actual runtime-only ZIP, manifest/checksum, reproducible builder and original
  upstream 1.3/current updater extraction tests. Required-module validation rejects
  incomplete packages before writes. Device/startup files are excluded.
- Beginner existing-ZIP backup/manual install/restart/rollback instructions and
  a clean 32-bit Pi OS git-clone/install/git-pull alternative. No OS deployment
  or Raspberry Pi changes were performed.

Validation: 325 Python tests, 66 JavaScript tests and all four Chromium suites
passed locally. Coverage includes 45-game full traversal, duplicate/omission
prevention, refresh position, filter persistence/ticker independence, failures,
mobile layouts, installed-runtime ZIP smoke checks and data/startup preservation.
Targeted lint, syntax, dependency and release-package checks also passed.

Real October 24 ESPN event IDs/count equality and the two requested matchups
remain unverified: current provider access is blocked by HTTP 403 and the available
2026 archive ends October 18. Positive schedule fixtures are explicitly synthetic.
Physical ARM/32-bit Pi boot, live provider comparison and 24–48 hour soak tests
remain required. No production-readiness claim is made.

See `docs/CFB_WEEK_UPDATE.md`, `docs/UPDATE_PACKAGE.md`, `docs/ZIP_UPDATE.md`,
`docs/FRESH_PI_INSTALL.md` and `docs/CFB_WEEK_SOURCE_AUDIT.md`.
