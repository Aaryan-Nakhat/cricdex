# scout/ingest

Source-specific loaders that feed the scout pipeline.

| Module | Source | Status | Notes |
|---|---|---|---|
| `cricsheet.py` | cricsheet.org JSON match archives | ✅ shipped | Ball-by-ball into DuckDB `balls_<collection>` + `matches_<collection>`. Includes a `indian-domestic` aggregator that downloads all 38 Indian state-team zips and deduplicates by match_id. Coverage: **Syed Mushtaq Ali Trophy** (T20) — 689 matches, 157,514 deliveries, 2016-2024. Cricsheet does NOT publish ball-by-ball for Ranji Trophy or Vijay Hazare — CricDex is Cricsheet-only, so that gap is out of scope. |
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
