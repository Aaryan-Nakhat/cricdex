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
| `capped`, `first_international` | Cricsheet men's T20I (ingested), ODI and Test archives (downloaded, only `info.players` read, never exported) |
| `primary_role` | overrides → the ball data when it is decisive (overs per match, batting position, stumpings across every exported league) → Wikipedia infobox role → LLM taxonomy |
| `bowling_style` / `bowling_arm` / `bowling_category` | overrides → Wikipedia infobox bowling → LLM taxonomy |
| `batting_hand` | overrides → Wikipedia infobox batting → Wikidata playing hand → LLM taxonomy |
| `country` | overrides → latest international side (Cricsheet) → Wikidata country for sport → infobox → LLM, normalised to ISO alpha-3 (ENG / SCO / WIN for the non-ISO sides) by `countries.normalise` |
| `active` | played any exported league or a men's international in the last 18 months (`master.ACTIVE_MONTHS`) of the data |
| `retired` | overrides (with evidence); the Wikipedia IPL personnel page's retirements are listed as review TODOs |
| `team` | the 2026 IPL squads (retained + bought + replacements) from Wikipedia's "List of 2026 Indian Premier League personnel changes", cached and hand-editable in `data/curated/ipl_squads_2026.json` |
| `dob` | overrides → Wikidata (P569) → Wikipedia infobox → the older `wikidata_enrichment.json` |

The LLM name check asks, 25 players a call, whether each candidate is how fans refer to the
player (`Virat Kohli`, not `V Kohli` or a legal full name); a correction is accepted only when it
keeps a token the open data already knows (normally the surname). Answers are cached in
`data/curated/player_names_llm.json`.

**Reviewing.** Every disagreement between sources (role, bowling style, batting hand, country,
rejected or applied name corrections, squad rows that didn't match a player, retirements to
verify) is written to `data/curated/player_master_review.json`. Settle a row by adding the right
value to `data/curated/player_overrides.json` (keyed by `cricsheet_id`, with `_name` and
`_evidence`); overrides always win.

Licences: Wikidata is CC0; Wikipedia-derived facts (infobox fields, the 2026 squads) are CC BY-SA
4.0 and cited in the master's `_sources`; Cricsheet is ODC-By.

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
