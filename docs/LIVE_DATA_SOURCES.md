# Live field and base state

The widgets use the **existing shared ESPN scoreboard response**, not new
per-browser/gamecast requests. Records and period tables retain their existing
scoreboard/summary enrichment path. Source latency still limits score freshness.

## Football

Endpoints are `https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard`
and the corresponding `football/college-football/scoreboard`. CFB retains the
existing complete FBS fetch and local conference/favorite filters.

The parser reads `events[].competitions[0].situation`:

- `possession` must identify one of the two competitor team IDs.
- `possessionText`, such as `LSU 34`, must match a competitor abbreviation and
  a yard line. A recognizable midfield value is also accepted.
- `down` and `distance` must be valid. Goal-to-go requires explicit matching-down
  text such as `1st & Goal` in `downDistanceText`/`shortDownDistanceText`.
- The current status supplies the actual `period` and `displayClock`. The widget
  does not count down or extrapolate a game clock between provider updates.

The schematic **normalizes offense toward the right**: own goal is 0, the
opponent's goal is 100. It does not claim actual stadium/compass direction or
guess direction from the quarter. Red zone means the validated ball position is
at/beyond the opponent's 20. `yardLine` alone is deliberately insufficient:
provider contexts can encode it differently. Historical drive/play data is not
used as current possession, even when a final summary contains the last play.

## Baseball

Endpoint: `https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard`.
The current competition's `situation.onFirst`, `onSecond`, `onThird` must each
be explicit booleans. `outs` must be 0, 1 or 2. Status `period` is the inning;
`type.detail`/`shortDetail` must identify a matching Top/Bottom/Bot inning.
Current scores come from the same scoreboard competitors.

Only current live state is shown. Missing bases are **unknown**, not assumed
empty. End-of-inning, halftime, delayed/suspended, canceled and completed states
hide widgets. Final games retain their records and inning/R/H/E table, without
pretending their last runners are current or reconstructing base-state history.

## Freshness and outages

Only successful actual score fetches record a bounded in-memory timestamp and
signature of the matching situation/status/scores. Cache hits and settings saves
cannot renew it. It expires after 90 seconds, never survives a server restart,
and is suppressed immediately when that league reports a fetch failure. Offline
score snapshots remain useful but cannot make a field or runner state look live.

The API returns the remaining lifetime. A paired kiosk subtracts request transit
time and strips live widgets from retained offline responses. The browser also
subtracts request time, expires widgets with one shared timer, checks on tab
visibility changes, and removes them when its API request fails. Main scores,
records, period tables, slides and ticker survive these widget removals.

No provider requests or background threads were added. Default live polling is
30 seconds, shared and cached with existing rate limiting/backoff. If you choose
a live interval longer than 90 seconds, a widget intentionally disappears
between fresh fetches. A recent fetch is not proof the provider updated its data.

## Verification and remaining source gap

Direct ESPN scoreboard/CDN requests returned HTTP 403 through this cloud's
outbound proxy. No real in-progress football/MLB capture was obtained in this
update. Positive live cases are deterministic mock tests; the exact current
provider shapes and real refresh cadence still require an internet-enabled
physical test. Unknown/changed shapes intentionally hide just the detail widget.

Public [sportsdataverse archived ESPN fixtures](https://github.com/sportsdataverse/sportsdataverse-py/tree/master/tests/fixtures/espn)
were inspected. All these games are final and have no current `situation`, which
supports hiding final widgets but **does not validate live occupancy/possession**.
SHA-256 fingerprints of the retrieved files:

| File | Observed games | SHA-256 |
| --- | --- | --- |
| scoreboard_nfl.json | 15 final | `5f5870636160521bb1e35e79521ffc204bd5c065bd036a092dbd21bfcc0c5112` |
| scoreboard_cfb.json | 17 final | `d3ccc4bd4d411a0968ec033afe6025be86d2ba4b76fce352157ec233e014a388` |
| scoreboard_mlb.json | 1 final, 10 innings | `d020f77b3add22b18397baef80dc51f36c942566b7bb6b813786b8720dfdf212` |

No third-party fixture package or raw game archives are bundled as dependencies.
On the test Pi, compare the current provider situation with the normalized
`football_tracker`/`baseball_tracker` in `/api/data`; confirm real possession
changes, empty/occupied bases, outs, inning changes and final-state removal.
