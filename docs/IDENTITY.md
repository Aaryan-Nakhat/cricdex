# Player identity resolution

CricDex maintains one canonical `player_id` per person and bridges it
to every external identifier the rest of the cricket-data ecosystem
uses. This is what lets a query against a Cricsheet ball-by-ball
record fan out to an ESPNcricinfo profile, a Cricbuzz live feed, or a
CricHeroes grassroots ladder.

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
with 99.8% Cricinfo coverage (17,937 / 17,981 players). Leaning on
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
-- Cricsheet ball-by-ball → ESPNcricinfo profile ID
SELECT b.batter, p.identifier AS cricsheet_id, p.key_cricinfo
FROM balls_ipl b
JOIN people p ON p.unique_name = b.batter;

-- Resolve "V Kohli" / "Virat Kohli" / "V. Kohli" → same identifier
SELECT identifier, name FROM people_names WHERE name ILIKE 'v%kohli%';
```

## Coverage today

| Source | Players bridged | % |
|---|---|---|
| ESPNcricinfo | 17,937 | 99.8 |
| BBL | 296 | 1.6 |
| CricHeroes | 111 | 0.6 |
| Cricbuzz | 22 | 0.1 |

The Cricbuzz / CricHeroes layers are thin — those bridges need our
own scrape (planned, Phase 2 scout work).

## v2: extend with our own scrape

When the register doesn't cover a source CricDex needs, we'll layer
our own bridges on top:

1. **Cricbuzz** — scrape player profile pages, match `cricsheet_id` via
   `(unique_name, DOB, country)`.
2. **CricHeroes** — apply for partner API; until then, slow respectful
   scrape of public player URLs.
3. **BCCI Domestic** — Ranji / SMAT / Hazare scorecards link players
   by `(name, state)` — bind to `cricsheet_id` via Cricinfo profile
   linkages.

These extra bridges land in additional DuckDB tables
(`cricbuzz_players`, `cricheroes_players`, etc.) joined to the
canonical `people.identifier`. No edits to the canonical register —
the register stays the truth and our supplementary scrapes are
additive layers.

## Why not push `cricsheet_id` into ball-by-ball directly

Cricsheet's match JSON has `info.registry.people` — a per-match map
of name → identifier. We do not yet propagate this into the ball
table; today we join by `unique_name`. That's accurate but slower than
an integer FK join.

**Planned upgrade:** during cricsheet ingest, lift
`info.registry.people` into the ball rows so every ball has
`batter_id`, `bowler_id`, `non_striker_id` columns. See
`docs/ROADMAP.md` Phase 2.

## Identity edge cases

- **Multiple Cricinfo IDs per player** (`key_cricinfo`, `_2`, `_3`)
  happen when ESPNcricinfo splits or merges profiles. The register
  ships all variants — when bridging, accept any of them as
  matching.
- **Players with no Cricinfo ID** (~44 rows) are typically very young
  age-group players, women's club cricketers, or recent debutants —
  Cricinfo just hasn't created profile pages yet. Re-ingest the
  register periodically (`--force`) to pick up new profiles.
- **Duplicate `unique_name`** is rare but possible (e.g. two players
  named "M Ahmed"). The register handles this with disambiguating
  metadata; downstream joins should prefer `identifier` over
  `unique_name` whenever both are available.
