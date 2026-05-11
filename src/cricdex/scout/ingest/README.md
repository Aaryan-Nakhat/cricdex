# scout/ingest

Source-specific loaders that feed the scout pipeline.

| Module | Source | Status | Notes |
|---|---|---|---|
| `cricsheet.py` | cricsheet.org JSON match archives | ✅ shipped | Ball-by-ball into DuckDB `balls_<collection>` + `matches_<collection>`. |
| `people_register.py` | cricsheet.org/register/{people,names}.csv | ✅ shipped | Cross-ID bridge (Cricsheet ↔ Cricinfo ↔ Cricbuzz ↔ CricHeroes ↔ 8 more). See [`docs/IDENTITY.md`](../../../docs/IDENTITY.md). |
| `wikidata.py` | Wikidata SPARQL (P2697 = Cricinfo player ID) | 🟡 module ready, data pending | DOB / country / birthplace / gender enrichment in batches. Resumable via JSONL checkpoint under `data/register/`. The public WDQS endpoint aggressively rate-limits anonymous IPs — run from a less-throttled environment if you need the full 18k-row pull in one go. |
| Cricinfo profile scraper | espncricinfo.com | ⏸ blocked (Akamai-walled, returns 403 to non-browser clients) | Pivoted to Wikidata + Wikipedia REST API as the structured-metadata source. |
| Cricbuzz player profile scraper | cricbuzz.com | planned Phase 2 | Live-feed alignment + bowling/batting style. |
| BCCI Domestic scrapers | bcci.tv/domestic | planned Phase 2 | Ranji / SMAT / Hazare / U19. |
| CricHeroes scraper | cricheroes.com | planned Phase 2 | Grassroots; respect their ToS / partner API option. |

## Why we lean on aggregators where possible

The fastest path to a usable scout system is to compose **structured
ID registers** (Cricsheet's people register) and **public SPARQL
APIs** (Wikidata) before reaching for scrapers. The People Register
alone bridges 99.8% of Cricsheet players to Cricinfo without any HTTP
calls per player; Wikidata fills DOB / country / sex via a few batched
SPARQL queries. Only when those sources don't have what we need do we
move on to scraping.
