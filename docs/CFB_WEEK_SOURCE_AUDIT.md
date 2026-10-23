# CFB weekly coverage: source verification

Checked October 23, 2026. This audit distinguishes observed ESPN payloads,
published ESPN-derived snapshots, deterministic fixtures and checks that could
not run. No requests were made to a Raspberry Pi or home-network device.

## Current provider access

The following read-only requests failed at this cloud's outbound proxy with
`ProxyError` / HTTP 403 during the HTTPS CONNECT tunnel:

- `https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=1000`
- The same endpoint with `&dates=20261024`.
- `https://www.espn.com/college-football/schedule/_/week/8/year/2026/seasontype/2`

TLS verification was not disabled. A query URL and passing mocked test do not
prove that the current provider accepts the query or returns a complete slate.
An internet-enabled test must still compare current event IDs and game counts.

## Observed official-calendar structure

The public [sportsdataverse archived ESPN CFB scoreboard](https://raw.githubusercontent.com/sportsdataverse/sportsdataverse-py/master/tests/fixtures/espn/scoreboard_cfb.json)
was successfully retrieved (267,787 bytes). SHA-256:
`d3ccc4bd4d411a0968ec033afe6025be86d2ba4b76fce352157ec233e014a388`.
It contains 17 final games in the **2024 regular season, week 7**; it is not a
capture of October 24, 2026.

Observed fields:

- Root `season` is `{ "type": 2, "year": 2024 }`; root `week` is
  `{ "number": 7 }`. Individual events carry matching `season.year`,
  `season.type` and `week.number`.
- `leagues[0].calendar` is a list of season-type blocks with string `value`,
  `startDate`, `endDate` and `entries`. Entries carry `value`, `label`,
  `startDate` and `endDate`.
- Regular-season week 7 starts `2024-10-07T07:00Z` and ends
  `2024-10-14T06:59Z`; it is an explicit provider interval, not a host-local
  Monday/Sunday calculation.
- The league-level `season.type` says **Postseason**, despite the historical
  root/event selection being regular-season week 7. That league-level field
  must not override a historical query's root/event season type.
- Postseason block 3 contains overlapping **Bowls** entry 1 and **CFP** entry
  999. This confirms the need for deliberate canonical selection instead of
  choosing the last date match. This capture has no postseason events, so their
  actual event-week values remain unverified here.
- Offseason block 4 contains All-Star entry 1, separate from the requested
  college football competition coverage.

## Verified 2026 conference identifiers

The public [ESPN group snapshot](https://raw.githubusercontent.com/sportsdataverse/sdv-reference-data/main/raw/cfb/espn_groups.json.gz)
was retrieved successfully. It contains 2026 entries as well as older seasons;
the table below specifically uses its **2026** records. Decoded-content SHA-256:
`7235bb430be64e1f2a785b6bc37006364b291126a35204f59500b116b1c6e654`.

| Group | ESPN ID | Parent | Conference? |
| --- | --- | --- | --- |
| FBS | 80 | 90 | No |
| ACC | 1 | 80 | Yes |
| Big Ten | 5 | 80 | Yes |
| Big 12 | 4 | 80 | Yes |
| SEC | 8 | 80 | Yes |
| Pac-12 | 9 | 80 | Yes |

The project's existing [2026 membership audit](TEAM_COVERAGE_2026.md) verifies
75 schools in these requested conferences plus independent Notre Dame. A game
qualifies when either competitor is eligible; an opponent need not be in FBS
or in the five conferences. Conference discovery must not reduce eligibility
to favorites or AP-ranked teams.

## October 24 comparison: not yet verified

The published [2026 ESPN-derived schedule CSV](https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_schedules/cfb_schedule_2026.csv)
was retrieved successfully (82,523 bytes). SHA-256:
`2d86ab1bef97ab4f465670f9280683dbad2c3ef1960f6967b59de94d5980732c`.

It has **510 rows, weeks 1–7 only**, from `2026-08-29T16:00Z` through
`2026-10-18T03:00Z`. It does not contain October 24. Therefore it cannot prove
the requested Texas A&M–Alabama or Ole Miss–Texas event IDs, kickoff times, full
eligible count or equality against ESPN's October 24 slate. Those facts are not
invented, inferred from previous weeks or supplied as a fabricated real fixture.

Before installing, or on the controlled test installation with internet access:

1. Fetch the official current calendar and identify the selected season type
   and week. For the historical acceptance check, request the actual October 24,
   2026 week explicitly rather than whichever week is current when the test runs.
2. Request FBS group 80 with a high limit and that exact season/type/week.
3. Filter using verified team IDs, including Notre Dame, then deduplicate by ESPN
   event ID. Compare this full eligible ID set and count with the API's CFB cards.
4. Confirm the two requested matchups using actual source events; do not add them
   by hand if the source differs. Investigate discrepancies in schedule data.
5. Compare kickoff ordering using timestamps and stable event-ID tie breaks.
6. Repeat across refreshes, a kickoff/final-state transition and an outage.

Deterministic tests cover missing unranked/favorite-independent coverage, weekly
boundaries, mixed opponents, ordering, duplicates and rotation mechanics. They
must remain labeled mocked; they do not replace this blocked live-source check.
