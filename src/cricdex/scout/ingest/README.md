# scout/ingest

Source-specific loaders that feed the scout pipeline.

| Module | Source | Status | Notes |
|---|---|---|---|
| `cricsheet.py` | cricsheet.org JSON match archives | ✅ shipped | Every field of the Cricsheet JSON format into DuckDB: `matches_`, `innings_`, `balls_`, `wickets_`, `replacements_`, `match_players_`, `players_<collection>` plus `ingest_meta` (schema version per collection). Which zip(s) a collection comes from is the league registry, `config/leagues.toml` ([docs/LEAGUES.md](../../../../docs/LEAGUES.md)). SMAT (`indian_domestic_male`) is Cricsheet's single `sma_json.zip` (695 matches; it replaced an aggregate of 38 state-team zips, 689 matches, which missed 6 matches played only between Himachal, Jammu & Kashmir and Punjab, sides no state-team zip covered). Cricsheet does NOT publish ball-by-ball for Ranji Trophy or Vijay Hazare — CricDex is Cricsheet-only, so that gap is out of scope. |
| `people_register.py` | cricsheet.org/register/{people,names}.csv | ✅ shipped | Cross-ID bridge (Cricsheet ↔ Cricinfo ↔ Cricbuzz ↔ CricHeroes ↔ 8 more). See [`docs/IDENTITY.md`](../../../../docs/IDENTITY.md). |
| `wikidata.py` | Wikidata entity API (`wbsearchentities` + entity JSON) | ✅ shipped | DOB / country / birthplace / photo / socials, cached in the committed `data/curated/wikidata_enrichment.json` keyed on `cricsheet_id` (342 players, 331 found). Throttled 0.6 s between requests. The entity API sits on a different rate-limit pool from the public SPARQL endpoint (WDQS), which hard-throttles datacenter IPs. Build the cache with `cricdex data ingest wikidata` (entity API); the older SPARQL bulk path (`scripts/ingest_wikidata.py` / `make docker-ingest-wikidata`) is still there but subject to that throttle. Pure enrichment, not on the critical path. |
| CricHeroes scraper | cricheroes.com | year-2 backlog ([`docs/ROADMAP.md`](../../../../docs/ROADMAP.md#later)) | Grassroots; respect their ToS / partner API option. |

Cricinfo, Cricbuzz and BCCI-domestic scrapers are out of scope (CricDex is
Cricsheet-only); see [`docs/ROADMAP.md`](../../../../docs/ROADMAP.md#out-of-scope).

## Why we lean on aggregators where possible

The fastest path to a usable scout system is to compose **structured
ID registers** (Cricsheet's people register) and **public APIs**
(Wikidata) before reaching for scrapers. The People Register
alone bridges 99.8% of Cricsheet players to Cricinfo without any HTTP
calls per player; Wikidata fills DOB / country / photo / socials via
its entity API. CricDex doesn't scrape.
