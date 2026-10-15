# Roadmap

## Phase 1 (Foundations + CricMetrics) — ✅ shipped

- Cricsheet ETL → DuckDB. Phase tagging respects match_type.
- Cricsheet People Register identity bridge (17,981 players, 99.8 % Cricinfo coverage).
- Wikidata enrichment shipped — dob / photo / socials via the Wikidata entity API (342 cached players, 331 with a DOB; cached JSON, merged into profiles).
- LLM player taxonomy — role / seam-spin / batting slot / country for 2,525 players (an LLM via LiteLLM, configured with `LLM_MODEL`; shown as "AI-classified").
- Novel metrics v1 (10): NGI, Pressure Runs, Intent Curve, Dot-Ball Recovery, Counter-Attack, Boundary Dependency, Pressure Conversion, Wicket Quality, Crease Longevity, Slow-Start Cost.
- Wicketkeeping + Fielding leaderboards ✅ — 12 leaderboards in all, across 8 collections × 3 windows (all-time / last 3y / last 1y).
- Public leaderboard surface (web + Streamlit dashboard + CLI/TUI, all from the exported JSON).

## Phase 2 (Scout v1) — ✅ shipped (with documented coverage notes)

- BCCI Domestic: Syed Mushtaq Ali Trophy ✅ via the Cricsheet state-team aggregator (689 matches, 157,514 deliveries). Ranji Trophy + Vijay Hazare — out of scope (Cricsheet-only; a BCCI / Cricinfo scrape was removed, see [`VNEXT.md`](VNEXT.md)).
- CricHeroes grassroots scraper — year-2 backlog ([`VNEXT.md`](VNEXT.md) §A).
- Photo CLIP embeds — year-2 backlog, only needed once a CricHeroes tier lands (VNEXT §A).
- Bayesian opponent-adjusted ratings ✅ (NumPyro / JAX, ADVI default + NUTS available, 1,055 IPL player-roles fit; 10-50× faster than the prior PyMC implementation).
- Style-twin k-NN search ✅ (cosine over a 13-axis batter vector — 12 metric axes + Bayes skill — and a 2-axis bowler vector; surfaced on every Player Profile).
- `/scout` filter UI ✅ via the Player Profile + Compare pages on the dashboard.

## Phase 3 (Auction + Scout) — ✅ shipped

- **Auction room ✅** (single source across web + CLI + TUI + Streamlit via `cricdex.web_parity`, locked by `test_web_parity.py` in CI, CLI `cricdex auction room`): real-rules IPL auction Monte-Carlo — cross-collection pool (IPL + BBL/SA20/CPL/Blast free agents + uncapped SMAT), crore prices recalibrated to recent auctions with recency decay, editable Mega/Mini retentions (real 2025 lists), overseas cap + retention slabs + second-price clearing, two-phase fill to 20–25-man squads (~300 trials, per-player post-sim search). See [`docs/AUCTION_MATH.md`](AUCTION_MATH.md). Full PettingZoo multi-agent self-play with personality-extracted franchise YAML remains the year-2 auction-v2 milestone.
- **Scout ✅** (single source across web + CLI + TUI + Streamlit via `cricdex.web_parity`, CLI `cricdex scout look-alikes`): cross-competition look-alike finder — pick an active IPL player → similar IPL peers, then uncapped SMAT, then overseas BBL / SA20 / CPL / T20 Blast, ranked by within-tier Bayesian skill-standing z-score. Plus per-row est. crore price + saving-vs-pick (budget swap), an uncapped-gem flag (high standing on low exposure), role/batting-slot filters, and one-click draft into the Auction room.

## Phase 3b (Analysis pages) — ✅ shipped

- **Matchups** (batter vs bowler + pace/spin splits), **Phase** (powerplay / middle / death specialists), **Form** (recent window vs career), **Partnerships** (batter-pair stands), **Aging** (performance vs age curves) ✅ — on web, CLI, TUI and Streamlit, all reading the exported JSON.
- **IPL-relevance weighting** for the auction pool ✅ — league-only veterans are down-weighted by time since their last IPL match and age.
- **`cricdex.web_parity`** ✅ — bit-exact Python port of the web's Scout / Auction / H2H / filter logic, parity-tested against the TypeScript in CI.

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
- Multi-agent RL auction-v2 — PettingZoo + per-franchise personality YAML (extracted from 10 yr bid history via an LLM) on top of today's fixed-archetype Monte-Carlo room.
- CricHeroes grassroots scraper ([`VNEXT.md`](VNEXT.md) §A). BCCI / Cricinfo scrapes are out of scope (Cricsheet-only).
