# scout/ingest

Source-specific loaders that feed the scout pipeline.

| Module | Source | Status | Notes |
|---|---|---|---|
| `cricsheet.py` | cricsheet.org JSON match archives | ✅ shipped | Ball-by-ball into DuckDB `balls_<collection>` + `matches_<collection>`. Includes a `indian-domestic` aggregator that downloads all 35 Indian state-team zips and deduplicates by match_id. Coverage: **Syed Mushtaq Ali Trophy** (T20) — 689 matches, 157,514 deliveries, 2016-2024. Cricsheet does NOT publish ball-by-ball for Ranji Trophy or Vijay Hazare on India — that gap needs a separate BCCI / Cricinfo scrape, planned but not yet shipped. |
| `people_register.py` | cricsheet.org/register/{people,names}.csv | ✅ shipped | Cross-ID bridge (Cricsheet ↔ Cricinfo ↔ Cricbuzz ↔ CricHeroes ↔ 8 more). See [`docs/IDENTITY.md`](../../../docs/IDENTITY.md). |
| `wikidata.py` | Wikidata SPARQL (P2697 = Cricinfo player ID) | 🟡 module ready, data pending | DOB / country / gender enrichment in 50-id batches. Resumable JSONL checkpoint under `data/register/`. **WDQS hard-throttles our GCP datacenter IP to "1 req / min"** even after a multi-hour cooldown, so the full 18k pull takes ~6 hours. Run from a residential IP / VPN / a different host, or accept the slow grind. The Cricsheet People Register already gives a 99.8% Cricinfo bridge — Wikidata is pure enrichment, not on the critical path. |
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
