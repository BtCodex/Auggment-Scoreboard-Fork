# Football team coverage, 2026

The shipped baseline contains **75 schools** in the requested ACC, Big Ten,
Big 12, SEC and rebuilt Pac-12 grouping, plus independent Notre Dame separately.
It also contains **all 32 current NFL franchises**. The current four largest
conferences account for 67 football schools; including the rebuilt Pac-12 adds
eight. Gonzaga is not included because it has no football program.

The team picker supplements successful ESPN results with this baseline and can
use it when team discovery is unavailable. It retains additional provider teams.
Adding these choices does not select them as favorites, enable leagues, or erase
any previously saved teams, custom images, colors or display settings. Existing
Texas A&M (`TA&M`) and Houston (`HOU`) selections remain compatible. Historical
abbreviations are recorded as aliases so team matching can preserve saved values.

In **Settings → Teams**, enable CFB or NFL, search for a school/franchise, add or
remove favorites and save. Football Priority still adds its automatic coverage;
turn it off to limit football scorecards to favorites. The independent football
display selector still controls CFB, NFL, both or the automatic weekly schedule.
Making a team selectable does not guarantee that ESPN provides every historical
game or that every scheduled game falls inside your configured date window.

## What was verified

On **October 19, 2026**, the development environment downloaded and cross-checked
these publicly maintained source snapshots:

- SportsDataverse's **2026 CFB conference membership** table: all 75 requested
  conference members agree between its CFBD and ESPN sources. The 138 FBS
  memberships also support existing Group of Five conference filters.
- SportsDataverse's **2026 ESPN CFB schedule**: exact ESPN IDs, full names and
  abbreviations for all 76 shipped CFB choices, including Notre Dame. This avoids
  assuming that CFBD abbreviations are ESPN abbreviations; for example, ESPN uses
  `MIA`, `NCSU`, `IU`, `OU`, `NU` and `BOIS` in the retrieved snapshot.
- SportsDataverse's **2026 ESPN NFL team snapshot**: exactly 32 current IDs,
  abbreviations and team names, including the Washington Commanders and Las Vegas
  Raiders. Numeric NFL IDs here are ESPN IDs, not nflverse/GSIS identifiers.
- cfbfastR and nflverse team metadata: team colors and ESPN-hosted logo URLs.
  Old conference labels in the cfbfastR metadata were deliberately ignored.
- Published **2026 ESPN conference groups**: ACC `1`, Big 12 `4`, Big Ten `5`,
  SEC `8`, Pac-12 `9`. The old UI incorrectly labeled `9` as SEC and `21` as
  Pac-12; the source identifies `21` as Missouri Valley, an FCS conference.

The exact source URLs, content SHA-256 hashes and retrieval date are included in
[`static/data/football-teams-2026.json`](../static/data/football-teams-2026.json).
Hashes for compressed source snapshots cover the decoded content. This is public
factual team metadata; no team artwork is copied into the repository.

**Limitations:** Direct reads from ESPN and official conference websites were
blocked by this cloud environment's outbound proxy. This verification therefore
uses published 2026 ESPN/CFBD snapshots, not direct official-site checks. Actual
image downloads, current provider availability, live score accuracy for all teams
and future conference changes still need checking with internet access. The
static baseline is a supplement to the provider rather than a replacement for
live sports data. It is intentionally labeled with its season.

## Checks to repeat before installing

Run the complete Python suite, including the offline coverage checks:

```bash
python -m unittest discover -s tests -v
```

On the spare/cloned Pi installation, open Settings from a phone and search for
each newly realigned school. Verify that a selected team's saved abbreviation is
retained after saving and rebooting. Test CFB and NFL discovery while disconnected
from the internet, then reconnect and check that provider additions remain
available. Confirm SEC and Pac-12 filters return the intended conferences.

The tables below enumerate the shipped choices. Additional teams returned by ESPN
remain available, including existing favorites outside these conferences.

## ACC (17)

| School | ESPN abbreviation | ESPN ID |
| --- | --- | --- |
| Boston College Eagles | `BC` | `103` |
| California Golden Bears | `CAL` | `25` |
| Clemson Tigers | `CLEM` | `228` |
| Duke Blue Devils | `DUKE` | `150` |
| Florida State Seminoles | `FSU` | `52` |
| Georgia Tech Yellow Jackets | `GT` | `59` |
| Louisville Cardinals | `LOU` | `97` |
| Miami Hurricanes | `MIA` | `2390` |
| NC State Wolfpack | `NCSU` | `152` |
| North Carolina Tar Heels | `UNC` | `153` |
| Pittsburgh Panthers | `PITT` | `221` |
| SMU Mustangs | `SMU` | `2567` |
| Stanford Cardinal | `STAN` | `24` |
| Syracuse Orange | `SYR` | `183` |
| Virginia Cavaliers | `UVA` | `258` |
| Virginia Tech Hokies | `VT` | `259` |
| Wake Forest Demon Deacons | `WAKE` | `154` |

## Big Ten (18)

| School | ESPN abbreviation | ESPN ID |
| --- | --- | --- |
| Illinois Fighting Illini | `ILL` | `356` |
| Indiana Hoosiers | `IU` | `84` |
| Iowa Hawkeyes | `IOWA` | `2294` |
| Maryland Terrapins | `MD` | `120` |
| Michigan State Spartans | `MSU` | `127` |
| Michigan Wolverines | `MICH` | `130` |
| Minnesota Golden Gophers | `MINN` | `135` |
| Nebraska Cornhuskers | `NEB` | `158` |
| Northwestern Wildcats | `NU` | `77` |
| Ohio State Buckeyes | `OSU` | `194` |
| Oregon Ducks | `ORE` | `2483` |
| Penn State Nittany Lions | `PSU` | `213` |
| Purdue Boilermakers | `PUR` | `2509` |
| Rutgers Scarlet Knights | `RUTG` | `164` |
| UCLA Bruins | `UCLA` | `26` |
| USC Trojans | `USC` | `30` |
| Washington Huskies | `WASH` | `264` |
| Wisconsin Badgers | `WIS` | `275` |

## Big 12 (16)

| School | ESPN abbreviation | ESPN ID |
| --- | --- | --- |
| Arizona State Sun Devils | `ASU` | `9` |
| Arizona Wildcats | `ARIZ` | `12` |
| BYU Cougars | `BYU` | `252` |
| Baylor Bears | `BAY` | `239` |
| Cincinnati Bearcats | `CIN` | `2132` |
| Colorado Buffaloes | `COLO` | `38` |
| Houston Cougars | `HOU` | `248` |
| Iowa State Cyclones | `ISU` | `66` |
| Kansas Jayhawks | `KU` | `2305` |
| Kansas State Wildcats | `KSU` | `2306` |
| Oklahoma State Cowboys | `OKST` | `197` |
| TCU Horned Frogs | `TCU` | `2628` |
| Texas Tech Red Raiders | `TTU` | `2641` |
| UCF Knights | `UCF` | `2116` |
| Utah Utes | `UTAH` | `254` |
| West Virginia Mountaineers | `WVU` | `277` |

## SEC (16)

| School | ESPN abbreviation | ESPN ID |
| --- | --- | --- |
| Alabama Crimson Tide | `ALA` | `333` |
| Arkansas Razorbacks | `ARK` | `8` |
| Auburn Tigers | `AUB` | `2` |
| Florida Gators | `FLA` | `57` |
| Georgia Bulldogs | `UGA` | `61` |
| Kentucky Wildcats | `UK` | `96` |
| LSU Tigers | `LSU` | `99` |
| Mississippi State Bulldogs | `MSST` | `344` |
| Missouri Tigers | `MIZ` | `142` |
| Oklahoma Sooners | `OU` | `201` |
| Ole Miss Rebels | `MISS` | `145` |
| South Carolina Gamecocks | `SC` | `2579` |
| Tennessee Volunteers | `TENN` | `2633` |
| Texas A&M Aggies | `TA&M` | `245` |
| Texas Longhorns | `TEX` | `251` |
| Vanderbilt Commodores | `VAN` | `238` |

## Pac-12 (8)

| School | ESPN abbreviation | ESPN ID |
| --- | --- | --- |
| Boise State Broncos | `BOIS` | `68` |
| Colorado State Rams | `CSU` | `36` |
| Fresno State Bulldogs | `FRES` | `278` |
| Oregon State Beavers | `ORST` | `204` |
| San Diego State Aztecs | `SDSU` | `21` |
| Texas State Bobcats | `TXST` | `326` |
| Utah State Aggies | `USU` | `328` |
| Washington State Cougars | `WSU` | `265` |

## Independents (1)

| School | ESPN abbreviation | ESPN ID |
| --- | --- | --- |
| Notre Dame Fighting Irish | `ND` | `87` |

## NFL (32)

| Franchise | ESPN abbreviation | ESPN ID |
| --- | --- | --- |
| Arizona Cardinals | `ARI` | `22` |
| Atlanta Falcons | `ATL` | `1` |
| Baltimore Ravens | `BAL` | `33` |
| Buffalo Bills | `BUF` | `2` |
| Carolina Panthers | `CAR` | `29` |
| Chicago Bears | `CHI` | `3` |
| Cincinnati Bengals | `CIN` | `4` |
| Cleveland Browns | `CLE` | `5` |
| Dallas Cowboys | `DAL` | `6` |
| Denver Broncos | `DEN` | `7` |
| Detroit Lions | `DET` | `8` |
| Green Bay Packers | `GB` | `9` |
| Houston Texans | `HOU` | `34` |
| Indianapolis Colts | `IND` | `11` |
| Jacksonville Jaguars | `JAX` | `30` |
| Kansas City Chiefs | `KC` | `12` |
| Las Vegas Raiders | `LV` | `13` |
| Los Angeles Chargers | `LAC` | `24` |
| Los Angeles Rams | `LAR` | `14` |
| Miami Dolphins | `MIA` | `15` |
| Minnesota Vikings | `MIN` | `16` |
| New England Patriots | `NE` | `17` |
| New Orleans Saints | `NO` | `18` |
| New York Giants | `NYG` | `19` |
| New York Jets | `NYJ` | `20` |
| Philadelphia Eagles | `PHI` | `21` |
| Pittsburgh Steelers | `PIT` | `23` |
| San Francisco 49ers | `SF` | `25` |
| Seattle Seahawks | `SEA` | `26` |
| Tampa Bay Buccaneers | `TB` | `27` |
| Tennessee Titans | `TEN` | `10` |
| Washington Commanders | `WSH` | `28` |
