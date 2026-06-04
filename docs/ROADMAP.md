# Roadmap

## Phase 1 (Foundations + CricMetrics) — ✅ shipped

- Cricsheet ETL → DuckDB. Phase tagging respects match_type.
- Cricsheet People Register identity bridge (17,981 players, 99.8 % Cricinfo coverage).
- Wikidata enrichment shipped — dob / photo / socials for 289/300 active players (cached JSON, merged into profiles).
- Gemini player taxonomy — role / seam-spin / batting slot / country for 2040 players.
- Novel metrics v1 (10): NGI, Pressure Runs, Intent Curve, Dot-Ball Recovery, Counter-Attack, Boundary Dependency, Pressure Conversion, Wicket Quality, Crease Longevity, Slow-Start Cost.
- Public leaderboard surface (Streamlit dashboard + per-metric JSON).

## Phase 2 (Scout v1) — ✅ shipped (with documented coverage notes)

- BCCI Domestic: Syed Mushtaq Ali Trophy ✅ via the Cricsheet state-team aggregator (689 matches, 157,514 deliveries). Ranji Trophy + Vijay Hazare ⏳ — Cricsheet doesn't publish those for India; needs BCCI / Cricinfo scrape both blocked from datacenter IPs.
- CricHeroes scraper ⏳ — Phase 2 follow-on.
- Photo CLIP embeds ⏳ — needed only for hard identity ambiguity; punt until BCCI / CricHeroes layers land.
- Bayesian opponent-adjusted ratings ✅ (NumPyro / JAX, ADVI default + NUTS available, 1,043 player-roles fit; 10-50× faster than the prior PyMC implementation).
- Style-twin k-NN search ✅ (cosine over a 9-axis feature vector + Bayes skill; surfaced on every Player Profile).
- `/scout` filter UI ✅ via the Player Profile + Compare pages on the dashboard.

## Phase 3 (Pulse + Auction) — partial

- **Auction room ✅** (single source across web + CLI + TUI + Streamlit via `cricdex.web_parity`, locked by `test_web_parity.py`, CLI `cricdex auction room`): real-rules IPL auction Monte-Carlo — cross-collection pool (IPL + BBL/SA20/CPL/Blast free agents + uncapped SMAT), crore prices recalibrated to recent auctions with recency decay, editable Mega/Mini retentions (real 2025 lists), overseas cap + retention slabs + second-price clearing, two-phase fill to 20–25-man squads (~300 trials, per-player post-sim search). See [`docs/AUCTION_MATH.md`](AUCTION_MATH.md). Full PettingZoo multi-agent self-play with personality-extracted franchise YAML remains the year-2 auction-v2 milestone.
- **Scout ✅** (single source across web + CLI + TUI + Streamlit via `cricdex.web_parity`, CLI `cricdex scout look-alikes`): cross-competition look-alike finder — pick an active IPL player → similar IPL peers, then uncapped SMAT, then overseas BBL / SA20 / CPL / T20 Blast, ranked by within-tier Bayesian skill-standing z-score. Plus per-row est. crore price + saving-vs-pick (budget swap), an uncapped-gem flag (high standing on low exposure), role/batting-slot filters, and one-click draft into the Auction room.

## Phase 4 (Venues) — ✅ shipped

- `venues` pitch + conditions archive ✅ (5 SQL views; dashboard page).

## Phase 5 (Profiles + Comparator) — ✅ shipped

- `profiles` per-player profile builder ✅ — aggregates People Register IDs + Wikidata + career totals + every novel metric + Bayes skill + style twins.
- `comparator` visual side-by-side ✅ (Plotly radar + transposed table).

## Phase 6 (API + Records) — ✅ shipped

- `records` searchable records + On-This-Day ✅ (9 record queries).
- `api` public REST surface ✅ — FastAPI across records / venues / players / compare. OpenAPI at `/docs`.

## Deferred (year 2+)

- OpenBoundary — ball tracking from broadcast video (CV stack).
- ChuckCheck — bowler elbow flex via monocular 3D pose.
- Voice analyst — coach earpiece (LiveKit / STT-LLM-TTS).
- ScoutVLM — VLM-driven ball-by-ball extraction from YouTube grassroots video.
- Highlight CV — auto key-moment clip extraction.
- Tournament management B2B (partner with CricHeroes instead of competing).
- Multi-agent RL auction-v2 — PettingZoo + per-franchise personality YAML (extracted from 10 yr bid history via Gemini) on top of today's fixed-archetype Monte-Carlo room.
- BCCI / CricHeroes / Cricinfo scrapers via Playwright + residential proxies, so the datacenter-blocked feeds finally populate.
