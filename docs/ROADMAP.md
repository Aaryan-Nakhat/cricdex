# Roadmap

## Phase 1 (Foundations + CricMetrics + CricRules) — ✅ shipped

- Cricsheet ETL → DuckDB. Phase tagging respects match_type.
- Cricsheet People Register identity bridge (17,981 players, 99.8 % Cricinfo coverage).
- Wikidata enrichment pipeline. Code shipped; data load deferred (WDQS hard rate-limits our datacenter IP).
- Novel metrics v1: Pressure Runs, Intent Curve, Recoverability, Counter-Attack, Boundary Dependency, Sticky Dot Pressure.
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

- `pulse` social-trend pipeline ✅ (Reddit JSON fetcher + Gemini sentiment + per-player aggregate). Data fetch blocked from datacenter IPs.
- `auction` MILP squad optimiser ✅ + Monte-Carlo price-band simulator ✅ + GRPO RL self-play scaffold ✅ (real 429-player IPL pool, 6 franchise archetypes, terminal squad-quality bonus) + war-room substitute advisor ✅ (`scripts/auction_advisor.py` + dashboard block — composite of graph FACED-cohort similarity, Bayes-driven projected value, role and budget filters). Full PettingZoo multi-agent self-play with personality-extracted franchise YAML remains the year-2 auction-v2 milestone.

## Phase 4 (Live + Predict + Venues + Newsletter + DRS) — ✅ partial

- `live` Cricbuzz live-score fetcher ✅ (datacenter-IP blocked; pipeline correct).
- `predict` daily-prediction game ⏸ — needs upcoming-match metadata that only lands when the live feed is wired from a non-datacenter network.
- `venues` pitch + conditions archive ✅ (5 SQL views; dashboard page).
- `newsletter` digest engine ✅ (Markdown compiler; on-this-day + headlines + auto match report).
- `drs` scenario simulator ✅ (20 hand-curated scenarios; dashboard practice game).

## Phase 5 (Profiles + Commentary translation + Comparator) — ✅ shipped

- `profiles` per-player profile builder ✅ — aggregates People Register IDs + Wikidata + career totals + every novel metric + Bayes skill + style twins.
- `commentary_translate` text-only translator ✅ (Hindi / Tamil / Bengali / Urdu / Sinhala / Marathi / Telugu / Kannada). Voice-cloned target-language audio is the deferred year-2 final feature.
- `comparator` visual side-by-side ✅ (Plotly radar + transposed table).

## Phase 6 (API + Records + Match Reports) — ✅ shipped

- `records` searchable records + On-This-Day ✅ (9 record queries).
- `reports` auto match-report generator ✅ (LLM with no-hallucination guard; cached Markdown per match).
- `api` public REST surface ✅ — FastAPI with 12 endpoints across records / venues / players / compare / rules QA / match reports / translate / auction. OpenAPI at `/docs`.

## Deferred (year 2+)

- OpenBoundary — ball tracking from broadcast video (CV stack).
- ChuckCheck — bowler elbow flex via monocular 3D pose.
- Voice analyst — coach earpiece (LiveKit / STT-LLM-TTS).
- ScoutVLM — VLM-driven ball-by-ball extraction from YouTube grassroots video.
- Highlight CV — auto key-moment clip extraction.
- Tournament management B2B (partner with CricHeroes instead of competing).
- **Voice-cloned commentary translation** — final-feature milestone. Clone English commentators with XTTS-v2 / F5-TTS / OpenVoice and synthesise target-language audio in their voice. Ships after text-translation v1 (✅) plus opt-in licensing with retired commentators.
- Multi-agent RL auction-v2 — PettingZoo + per-franchise personality YAML (extracted from 10 yr bid history via Gemini) on top of today's GRPO single-agent scaffold.
- Predict game once live-feed is unblocked.
- BCCI / CricHeroes / Cricinfo scrapers via Playwright + residential proxies, so the datacenter-blocked feeds finally populate.
