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

The Cricbuzz / CricHeroes register layers are thin, but CricDex is
**Cricsheet-only** — it relies on the register's existing bridges and
does not scrape these sources.

## Enrichment on top of the register

Two on-disk caches extend the register by `cricsheet_id`, both committed:

1. **Wikidata** (`data/curated/wikidata_enrichment.json`) — dob / photo /
   socials for 289/300 active players (one-time pull).
2. **Gemini taxonomy** (`data/curated/player_taxonomy.json`) — role /
   seam-spin / batting slot / country for 2040 players.

Out of scope (year-2 at the earliest): a grassroots **CricHeroes** tier —
see [`DEFERRED.md`](DEFERRED.md) §grassroots. Cricbuzz and BCCI-domestic
scrapes were dropped.

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
