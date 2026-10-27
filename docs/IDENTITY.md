# Player identity resolution

CricDex keys every player on the canonical Cricsheet `identifier` and
carries the cross-source IDs the rest of the ecosystem uses (ESPNcricinfo,
BCCI, CricHeroes, …) straight from Cricsheet's People Register. That's
what lets a Cricsheet ball-by-ball record link out to an ESPNcricinfo
profile or join the one-time Wikidata enrichment by ID.

## v1: lean on Cricsheet's People Register

Cricsheet publishes a curated cross-ID register at
[cricsheet.org/register/](https://cricsheet.org/register/) — two CSVs:

- `people.csv` — one row per player with columns:
  `identifier, name, unique_name, key_bcci, key_bcci_2, key_bigbash,
  key_cricbuzz, key_cricheroes, key_crichq, key_cricinfo,
  key_cricinfo_2, key_cricinfo_3, key_cricingif, key_cricketarchive,
  key_cricketarchive_2, key_cricketworld, key_nvplay, key_nvplay_2,
  key_opta, key_opta_2, key_pulse, key_pulse_2`
- `names.csv` — name variants per identifier.

**Why we use this:** writing our own name-disambiguator over millions
of deliveries is a project in itself. Cricsheet has already done it,
with 99.8% Cricinfo coverage (18,606 / 18,651 players in the current register). Leaning on
their register costs us one HTTPS GET and gives us a free ID bridge.

## Implementation

```python
from cricdex.scout.ingest import people_register

people_register.ingest()        # downloads → DuckDB tables in cricsheet.duckdb
```

CLI: `make docker-ingest-people` (or
`uv run python scripts/ingest_people.py`).

After ingest, two DuckDB tables exist:

```sql
people(identifier, name, unique_name, key_bcci, …, key_cricinfo, …)
people_names(identifier, name)
```

Join examples:

```sql
-- Cricsheet ball-by-ball → Cricsheet id (via the match registry) → ESPNcricinfo profile ID
SELECT DISTINCT b.batter, r.identifier AS cricsheet_id, p.key_cricinfo
FROM balls_ipl b
JOIN players_ipl r ON r.match_id = b.match_id AND r.name = b.batter
JOIN people p ON p.identifier = r.identifier;

-- Resolve "V Kohli" / "Virat Kohli" / "V. Kohli" → same identifier
SELECT identifier, name FROM people_names WHERE name ILIKE 'v%kohli%';
```

## Coverage today

| Source | Players bridged | % |
|---|---|---|
| ESPNcricinfo | 18,606 | 99.8 |
| BBL | 296 | 1.6 |
| CricHeroes | 111 | 0.6 |
| Cricbuzz | 50 | 0.3 |

The Cricbuzz / CricHeroes register layers are thin, but CricDex is
**Cricsheet-only** — it relies on the register's existing bridges and
does not scrape these sources.

## Enrichment on top of the register

Two on-disk caches extend the register by `cricsheet_id`, both committed:

1. **Wikidata** (`data/curated/wikidata_enrichment.json`) — dob / photo /
   socials for 342 players, 331 with a DOB (one-time pull via the Wikidata
   entity API).
2. **LLM taxonomy** (`data/curated/player_taxonomy.json`) — role /
   seam-spin / batting slot / country for 2,525 players, built by an LLM
   via LiteLLM (configured with `LLM_MODEL` in `.env`) and shown as
   "AI-classified".

## The player master

`scripts/build_player_master.py` (`make player-master`; code in
`src/cricdex/scout/identity/`) builds one identity record per player of every exported league
and writes `data/curated/player_master.json`, which `scripts/export_site.py` reads. It reads the
DuckDB file read-only, so it can run at any time; every source is cached on disk and fetched in
polite batches (rerun = only what's missing; `--force` refetches, `--no-fetch` works offline).

| Field | Source, in order of precedence |
|---|---|
| `display_name` | overrides → LLM check of the candidate → Wikidata English label (by ESPNcricinfo id, P2697) → shortest full-word People Register variant → scorecard name |
| `full_name` | overrides → Wikipedia infobox `full_name` → Wikidata birth name (P1477) → longest register variant |
| `aliases` | every name we know: scorecard names in each league, register variants, Wikidata label and aliases, full name |
| `capped`, `first_international` | Cricsheet men's T20I (ingested), ODI and Test archives (downloaded, only `info.players` read, never exported); Cricsheet withholds every match featuring Afghanistan (since Nov 2024), so those come from `withheld.py`: Cricsheet's archive as kept by the Wayback Machine (to Feb 2023) and the revision history of Wikipedia's Afghanistan cap lists (METHODOLOGY §1) |
| `primary_role` | overrides → the ball data when it is decisive (overs per match and batting position across every exported league; a keeper needs 2 stumpings in the last 3 years of T20s, `RECENT_YEARS`) → Wikipedia infobox role → LLM taxonomy. An infobox "occasional(ly) wicket-keeper" or "part-time keeper" is not a keeper (Ruturaj Gaikwad's made CSK look like it had five). A keeper claim from Wikipedia or the LLM stands for a player the data can't see keeping, unless his last 3 years hold 40+ T20 matches without a stumping (`KEEPER_UNSEEN_MATCHES`: keepers stump about every 14 matches, so a real keeper goes 40 without one about 6% of the time). Until 2026-10-27 stumpings were counted over the whole career, so Ben Duckett (last stumping 2018) and Glenn Phillips (2022) were keepers |
| `batting_position` | his last 30 T20 innings in the last 3 years, from 8 innings up: "opener" when he walked out at 1 or 2 in at least half of them, pooled over every T20 league or in any one league where he has 8+ of them (Narine opens for KKR but bats lower elsewhere); otherwise the LLM taxonomy's slot, unless that is "opener" or missing, when his median slot gives no3 / middle / finisher / lower / tailender (`batting_slot`; source in `batting_position_source`). Fewer innings: the LLM taxonomy. Until 2026-10-27 it was the LLM taxonomy alone, which had Kohli, Samson, Marsh, Markram and Prabhsimran Singh away from the top and Padikkal and Ishan Kishan still opening. `recent_stats` keeps the window's numbers (matches, balls bowled, stumpings, opener share) |
| `bowling_style` / `bowling_arm` / `bowling_category` | overrides → Wikipedia infobox bowling → LLM taxonomy |
| `batting_hand` | overrides → Wikipedia infobox batting → Wikidata playing hand → LLM taxonomy |
| `country` | overrides → latest international side (Cricsheet) → Wikidata country for sport → infobox → the linked article's title ("Imran Khan (Trinidad and Tobago cricketer)" → WIN, `countries.title_country`; since 2026-10-27, so the LLM never wins over an article that names the nation) → LLM, normalised to ISO alpha-3 (ENG / SCO / WIN for the non-ISO sides) by `countries.normalise` |
| `active` | played any exported league or a men's international in the last 18 months (`master.ACTIVE_MONTHS`) of the data |
| `retired` | `data/curated/ipl_availability.json` (announced retirements, each with dated sources; since 2026-10-23, when the three in the overrides file moved there) or an override's own flag; the Wikipedia IPL personnel page's retirements not in it are listed as review TODOs |
| `team` | the 2026 IPL squads (retained + bought + replacements) from Wikipedia's "List of 2026 Indian Premier League personnel changes", cached and hand-editable in `data/curated/ipl_squads_2026.json` (which `scripts/ipl_squad_salaries.py` extends with each player's salary, acquisition, nationality and Cricsheet id, and the 2027-cycle trades and retirements, for Keep or release) |
| `dob` | overrides → Wikipedia infobox (the article Wikidata links, or, for an IPL squad player Wikidata can't find by his ESPNcricinfo id, the article the IPL personnel page links: since 2026-10-27, which gave 8 debutants their dates) → Wikidata (P569, day precision only) → the older `wikidata_enrichment.json`; a source date that makes him younger than 13 at his first match or older than 55 at his last is skipped for the next source. Until 2026-10-26 Wikidata came first and was read without its precision: a year-only date became 1 January, and its unsourced imports gave Mukesh Choudhary 1986 (1996) and Venkatesh Iyer 1990 (1994). Where both exist they agree for 93% of players; where they differed, seven IPL players checked against their iplt20.com and other published profiles had the infobox's date every time. Disagreements are listed in the review (`dob_disagree`); `sources.refresh_wikidata_dob` re-reads cached dates with their precision (ROADMAP I17e) |

The LLM name check asks, 25 players a call, whether each candidate is how fans refer to the
player (`Virat Kohli`, not `V Kohli` or a legal full name); a correction is accepted only when it
keeps a token the open data already knows (normally the surname). Answers are cached in
`data/curated/player_names_llm.json`.

**Reviewing.** Every disagreement between sources (role, bowling style, batting hand, country,
rejected or applied name corrections, squad rows that didn't match a player, retirements to
verify) is written to `data/curated/player_master_review.json`. Settle a row by adding the right
value to `data/curated/player_overrides.json` (keyed by `cricsheet_id`, with `_name` and
`_evidence`); overrides always win. A squad player with no match data has no `cricsheet_id`, so his date lives on his row of
`data/curated/ipl_squads_2026.json` (`dob` with a `dob_source` URL), or comes from his own article
(`_squad_only` in the master).

**Which article is his.** Wikidata finds the article by ESPNcricinfo id (P2697). Many debutants'
items lack that id, so since 2026-10-27 two fallbacks link the rest: (1) a Wikipedia search for a
cricketer article whose source carries his ESPNcricinfo id, accepted only when that article links
his ESPNcricinfo profile and no other article does (`sources.find_titles_by_cricinfo`, cached in
`data/curated/wikipedia_by_cricinfo.json`; run for the IPL players, today's squads and the active
players of the auction-pool leagues and T20Is), and (2) the article the IPL personnel page links
(`sources.squad_titles`). A date of birth whose year isn't the one the title gives
("(cricketer, born 1983)") is skipped, and a kept date that puts his first match in the data at 38
or older is listed in the review (`dob_late_debut`): usually a namesake's article (a 2026 Hundred
debut linked to a Usman Tariq born 1983).

**Build stamp.** The master records `_built_at`; every league export stamps `meta.json` with
`player_master: {built, hash}` (`master.build_stamp`), and `tests/test_identity_facts.py` fails when
the league exports come from different builds or disagree on a player's dob, country or retired flag.

**Availability** (`data/curated/ipl_availability.json`, since 2026-10-23). Who can't be bought at the next
IPL auction, keyed by `cricsheet_id`: `status` `retired` (an announced retirement; `scope` `ipl` = out of
the IPL and Indian cricket, may still play other leagues, or `all`; `date`; `role_now` for a coaching or
staff role) or `not_registered` (skipped the auctions in `seasons` only; kept in later pools and recorded so
a reviewer sees why a veteran is still there), each with `_evidence` = [{title, url, date}]. The export
leaves a retired player out of every auction pool (METHODOLOGY §7, `competitions.unavailable`), and the
player master reads its `retired` / `retired_scope` from it. A retirement reported later goes here with
its source; `tests/test_competitions.py` checks every record has one.

**Squad players with no obvious match** (issue I6, 22 Oct 2026). Of the 22 IPL squad players left
unmatched, three had played IPL 2026 under initials and were matched through the People Register's
ESPNcricinfo key against the key in the player's Wikipedia infobox: "MD Choudhary" = Mukul Choudhary
(cricinfo 1354217; the LLM name check had renamed him "Mukesh Choudhary", CSK's different player),
"T Dahiya" = Tejasvi Singh Dahiya (1460372; the check had guessed "Tanish"), and "SU Parakh" = Sahil
Parakh ("Parekh" on Wikipedia; his IPL debut of 27 Apr 2026 for DC is the id's first match). Each is an
override with evidence, and the squads file carries the id. The other 19 were searched in every
registry league and the People Register (surname spelling variants such as Oswal / Ostwal, Chauhan /
Chouhan, Parikh / Parekh, "Harnoor Singh" for Harnoor Pannu, and initials + surname): a same-surname
candidate either played for another side years earlier with an old cricinfo id (AR Kumar, AG Rao) or
for another country (NK Tiwari of Cyprus, Izhar Hussain of Switzerland), so none is a match. They have
no Cricsheet match yet; Keep or release prices them from the market instead of rating them.

**Captaincy** (`data/curated/ipl_captains.json`, hand-editable; `scripts/ipl_captains.py`, pages cached
in `data/curated/ipl_captain_pages/` pinned to a revision). IPL: each franchise article's captains
table (captain, from, to, matches), filled in from "List of Indian Premier League captains" (more
current): a one-team captain missing from his franchise's table gets a stint from the list (the
defunct sides have no table), and a latest stint that ends before the list's last year is extended to
it. Rising Pune Supergiant and Gujarat Lions (2016-17), whose captains led other sides too (the list
doesn't split their years), come from each season article's infobox `captain` (MS Dhoni RPS 2016, Steve
Smith RPS 2017, Suresh Raina GL 2016 and 2017; `matches` = the team's matches that season in the ball
data). 101 stints, all matched to a Cricsheet id (Wikipedia title first).
International: the men's Test, ODI and T20I tables of each Test nation's "List of … national cricket
captains" (12 nations; Ireland's page is "List of Ireland cricket captains"): 1,318 rows, 85% matched (the
rest mostly pre-2000); Ireland's 22 all match. One page error is fixed by hand (`"edited": true`,
`replaces_from`): the Ireland list gives William Porterfield's T20I captaincy as 2005-2007, before Ireland's
first T20I; he led from 2008 to June 2018 (ESPNcricinfo, 6 Jun 2018).
A stint covers every year from..to, except a stand-in (fewer than 4 matches a year): only its first
and last years count, and a stand-in is never "last season's captain".
`cricdex.scout.identity.captains.as_of(cid, season)` gives what was known before an auction
(regular IPL captain last season, IPL seasons as captain, captained his country in the two years
before), used by the market price; `summary(cid)` is the profile identity block's `captaincy`.

Licences: Wikidata is CC0; Wikipedia-derived facts (infobox fields, the 2026 squads, the auction
history, the captaincy) are CC BY-SA 4.0 and cited in each file's `_source`; Cricsheet is ODC-By.

Out of scope (year-2 at the earliest): a grassroots **CricHeroes** tier —
see [`ROADMAP.md`](ROADMAP.md#later). Cricbuzz and BCCI-domestic
scrapes were dropped.

## Names in the ball data → ids: each match's own registry

Cricsheet's match JSON carries `info.registry.people`, a per-match map of
scorecard name → identifier. The ingester keeps it as a
`players_<collection>` table (`match_id, name, identifier`), and every
metric, rating and export resolves names through
`cricdex.common.sql.player_ids`:

1. **The match registry first.** It's authoritative: the ball data can
   spell a player differently from the People Register's `unique_name`
   ("Navdeep Saini" vs "NA Saini"), or name someone the Register doesn't
   have yet. A name carried under two ids in one collection takes the id
   it has in most matches.
2. **The People Register's `unique_name` as fallback** for any name the
   registries don't cover.

The ball rows themselves still carry names (`batter`, `bowler`,
`non_striker`); the id is joined on through that relation, and the rating
model labels a name that resolves nowhere as `unresolved:<name>` rather
than guessing. The reverse direction (id → the name a player goes by in a
collection) is `scorecard_names`.

## Identity edge cases

- **Multiple Cricinfo IDs per player** (`key_cricinfo`, `_2`, `_3`)
  happen when ESPNcricinfo splits or merges profiles. The register
  ships all variants — when bridging, accept any of them as
  matching.
- **Players with no Cricinfo ID** (~45 rows) are typically very young
  age-group players, women's club cricketers, or recent debutants —
  Cricinfo just hasn't created profile pages yet. Re-ingest the
  register periodically (`--force`) to pick up new profiles.
- **Duplicate `unique_name`** is rare but possible (e.g. two players
  named "M Ahmed"). The register handles this with disambiguating
  metadata; downstream joins should prefer `identifier` over
  `unique_name` whenever both are available.
