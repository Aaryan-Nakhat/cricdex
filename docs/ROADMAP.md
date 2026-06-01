# Roadmap

## Phase 1 (Foundations + CricMetrics + CricRules) — ✅ shipped

- Cricsheet ETL → DuckDB. Phase tagging respects match_type.
- Cricsheet People Register identity bridge (17,981 players, 99.8 % Cricinfo coverage).
- Wikidata enrichment shipped — dob / photo / socials for 289/300 active players (cached JSON, merged into profiles).
- Gemini player taxonomy — role / seam-spin / batting slot / country for 2040 players.
- Novel metrics v1 (10): NGI, Pressure Runs, Intent Curve, Dot-Ball Recovery, Counter-Attack, Boundary Dependency, Pressure Conversion, Wicket Quality, Crease Longevity, Slow-Start Cost.
- Public leaderboard surface (Streamlit dashboard + per-metric JSON).
- Rulebook PDF ingest. 21 verified PDFs from MCC / ICC / IPL / Hundred / BBL / WBBL / SA20 / Cricket Australia domestic / ICC Codes / Anti-Corruption.
- pdfplumber clause-hierarchy parser → ~11 k clauses.
- Qdrant + hybrid retrieval (dense `Snowflake/snowflake-arctic-embed-l-v2.0`, multilingual, Matryoshka-truncated to 384-dim + BM25 + RRF fusion + Jina rerank) + Gemini-proxy QA with citation discipline.
- Curated supplementary clauses for the IPL Impact Player rule (since BCCI's Player Regulations PDF isn't public).
- `/rules` chat UI (Streamlit page).

## Phase 2 (Scout v1) — ✅ shipped (with documented coverage notes)

- BCCI Domestic: Syed Mushtaq Ali Trophy ✅ via the Cricsheet state-team aggregator (689 matches, 157,514 deliveries). Ranji Trophy + Vijay Hazare ⏳ — Cricsheet doesn't publish those for India; needs BCCI / Cricinfo scrape both blocked from datacenter IPs.
- CricHeroes scraper ⏳ — Phase 2 follow-on.
- Photo CLIP embeds ⏳ — needed only for hard identity ambiguity; punt until BCCI / CricHeroes layers land.
- Neo4j graph populated for the pro tier ✅ (799 IPL players, 1,219 matches, 30,774 FACED edges).
- Bayesian opponent-adjusted ratings ✅ (NumPyro / JAX, ADVI default + NUTS available, 1,043 player-roles fit; 10-50× faster than the prior PyMC implementation).
- Style-twin k-NN search ✅ (cosine over a 9-axis feature vector + Bayes skill).
- `/scout` filter UI ✅ via the Player Profile + Compare pages on the dashboard.

## Phase 3 (Pulse + Auction) — partial

- `auction` MILP squad optimiser ✅ + Monte-Carlo price-band simulator ✅ + GRPO RL self-play scaffold ✅ (real 429-player IPL pool, 6 franchise archetypes, terminal squad-quality bonus) + war-room substitute advisor ✅ (`scripts/auction_advisor.py` + dashboard block — composite of graph FACED-cohort similarity, Bayes-driven projected value, role and budget filters). Full PettingZoo multi-agent self-play with personality-extracted franchise YAML remains the year-2 auction-v2 milestone.

## Phase 4 (Venues) — ✅ shipped

- `venues` pitch + conditions archive ✅ (5 SQL views; dashboard page).

## Phase 5 (Profiles + Comparator) — ✅ shipped

- `profiles` per-player profile builder ✅ — aggregates People Register IDs + Wikidata + career totals + every novel metric + Bayes skill + style twins.
- `comparator` visual side-by-side ✅ (Plotly radar + transposed table).

## Phase 6 (API + Records) — ✅ shipped

- `records` searchable records + On-This-Day ✅ (9 record queries).
- `api` public REST surface ✅ — FastAPI across records / venues / players / compare / rules QA / scout / auction. OpenAPI at `/docs`.

## Deferred (year 2+)

- OpenBoundary — ball tracking from broadcast video (CV stack).
- ChuckCheck — bowler elbow flex via monocular 3D pose.
- Voice analyst — coach earpiece (LiveKit / STT-LLM-TTS).
- ScoutVLM — VLM-driven ball-by-ball extraction from YouTube grassroots video.
- Highlight CV — auto key-moment clip extraction.
- Tournament management B2B (partner with CricHeroes instead of competing).
- Multi-agent RL auction-v2 — PettingZoo + per-franchise personality YAML (extracted from 10 yr bid history via Gemini) on top of today's GRPO single-agent scaffold.
- BCCI / CricHeroes / Cricinfo scrapers via Playwright + residential proxies, so the datacenter-blocked feeds finally populate.
