# Changelog

All notable changes to CricDex. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic
versioning starts at v0.1.0.

---

## [Unreleased]

Rebuilt the Scout and Auction rooms, then unified **every surface** (web,
CLI, Textual TUI, Streamlit) onto a **single source of truth** — same
exported JSON inputs, same algorithm, locked by a parity test. The older
Neo4j-graph twins and MILP squad optimiser are kept as advanced/research
views, no longer the default path.

### Added

- **`cricdex.web_parity`** — a Python port of the web Auction + Scout logic
  (`site/src/lib/auction.ts`, `site/src/pages/Scout.tsx`): same pricing
  constants, same look-alike formula, same franchise personalities, and a
  **bit-exact LCG RNG** so the Monte-Carlo reproduces the browser
  trial-for-trial. It reads the **same** exported JSON the web fetches
  (`site/public/data/<collection>/{auction_pool,retentions,scout_index}.json`),
  so the inputs are identical too.
- **Parity test** (`test_scripts/test_web_parity.py`) — runs the canonical TS
  under Node (`--experimental-strip-types`) and asserts the Python port is
  identical (retentions, auction teams/marquee/sample-draft, scout
  look-alikes + prices) within 1e-9. Fails CI if the surfaces ever drift.
- Canonical desktop entry points: `cricdex scout look-alikes`,
  `cricdex auction room`; Streamlit **Scout** + **Auction room** pages; the
  TUI **Scout** + **Sim** tabs — all web-identical.

### Changed

- **Auction room (web) — real-rules IPL auction sim.** Replaced the
  browser "build my squad" knapsack with a Monte-Carlo of an actual IPL
  auction:
  - **Cross-collection pool** — IPL players + free agents from the BBL
    (overseas) and SMAT (uncapped Indians), not IPL-only. Active-only
    (last ~3 yrs), ≥150 balls, associate/non-IPL-nation noise filtered,
    cross-tier values penalised (BBL −0.07, SMAT −0.20).
  - **Crore pricing recalibrated** to recent real auctions —
    `clamp(1.6·e^(5.8·skill)·roleMult, 0.3, 27)` with a **recency decay**
    so dormant/retired names (Lynn, Mishra) stop topping the buys.
  - **Editable retentions** — Mega = the real 2025 lists (~5, slab-priced
    from a 120 cr purse); Mini = keep most of the squad (free, small
    leftover purse). Both shown and editable before you run.
  - **Two-phase fill** — every team fills to a 20-man minimum, then tops
    up toward a 25 cap (squads land 20–25, no team left short).
  - Real IPL rules: overseas cap 8, retention slabs, uncapped/RTM, second-
    price clearing, ~300 Monte-Carlo trials. See
    [`docs/AUCTION_MATH.md`](AUCTION_MATH.md).
- **Scout (web) — 3-tier look-alike finder.** Replaced the browser scout
  graph with: pick an active IPL player → similar **IPL peers**, then
  uncapped **SMAT** prospects, then overseas **BBL** options. Matches share
  archetype (role + seam/spin) and are ranked by within-tier skill-standing
  z-score, so cross-tier stars line up despite incomparable raw numbers.
  Each row now carries an **estimated crore price** (the Auction room's
  skill→price curve via a shared `estValue`, tier-discounted so SMAT/BBL is
  comparable to IPL) and the **saving** vs the pick (budget swap); an
  uncapped-**gem** flag marks SMAT prospects with high standing on
  below-median exposure (moneyball); **role / batting-slot filters** narrow
  or re-target each tier; and a one-click **Draft** drops a prospect into the
  Auction room as a retention (`/auction?draft=<id>`). Scout index now emits
  per-player `balls` for the gem cutoff.
- **Export pipeline** — `scripts/export_site.py` gains
  `_export_auction_pool` (cross-collection, recency, tier penalty) and
  `_export_scout_index` (3-tier z-standing), plus real-2025 retention
  lists; `collections.json` merge so single-collection runs don't clobber
  the index.
- **Intent Curve leaderboard** — fixed a misleading ranking. The metric is
  a per-innings *shape*, but the web table ranked the raw long form, which
  duplicated each batter across buckets and let late-innings buckets (plain
  set-phase strike rate) dominate. Now pivoted to one row per batter, ranked
  by **early SR** (balls-weighted SR over balls 1–10 — who attacks from ball
  one), with the full 6-bucket curve drawn as an inline sparkline.

---

## [0.1.0] — v1 release (pending tag)

The first cut a non-developer can install + browse. Terminal-first
distribution; Streamlit dashboard kept as a parallel browser surface
over the same `~/.cricdex/data/`.

### Added

- **CLI** — single `cricdex` console entry point with `init / config
  / data / leaderboard / profile / compare / records / venues /
  match-report / translate / rules / scout / auction / dashboard /
  tui` subcommands. `cricdex init` is a one-shot first-run wizard;
  every produce-command supports `--force` for opt-in refresh.
- **Textual TUI** — `cricdex tui` launches an interactive 6-tab
  app (Leaderboard / Profile / Scout / Auction / Rules / Records).
- **Streamlit dashboard** — 12 pages over the same `~/.cricdex/data/`:
  Home, Leaderboards (10 metric tabs), Rules Chat, Records, Match
  Reports, Compare, Venues, Auction (MILP + war-room advisor),
  Player Profile (Wikidata photo + DOB + social links), Translate
  Commentary, Auction Simulator (MC + GRPO), Player Twins (graph
  similarity, archetype auto-flip).
- **Provenance banner** — every data-backed dashboard page shows
  source + last-refreshed timestamp + a "load latest" pointer.
- **Fuzzy player resolver** — `rapidfuzz`-backed; CLI prints
  suggestions and exits 1 on no-exact-match, Streamlit renders a
  "did you mean?" confirmation button.
- **Novel metrics** — Pressure Runs, Intent Curve, Dot-Ball Recovery,
  Counter-Attack, Boundary Dependency, Pressure Conversion, Phase
  Dilation, Slow-Start Cost, Wicket Quality, **NGI (Net Game Impact)** —
  the WPA-style flagship.
- **NGI's WP model v2** — match-id holdout split, venue + innings1
  features, isotonic calibration, Brier + log-loss + reliability
  buckets in the output. Perfect calibration after isotonic
  (when the model says 70% win chance, batting team actually wins
  ~70% of the time).
- **Bowling-style classifier** — every Player node carries
  `bowling_style ∈ {pace, spin, unknown}`. Curated overrides at
  `data/curated/bowling_styles.json` for HV Patel / DJ Bravo /
  Coetzee / Vyshak / Madhwal / Deshpande / etc., otherwise
  middle-overs-% heuristic (≥55% → spin, <50% → pace). CLI +
  Streamlit + advisor all expose a `--style pace|spin` filter.
- **Wikidata enrichment** — `cricdex data ingest wikidata` resolves
  cricketer Q-ids via the action-API's
  `haswbstatement:P2697=<statsguru_id>` bridge (sidesteps WDQS rate
  limits) and fetches the entity JSON. 289 / 300 of the top
  active IPL/intl players currently enriched with DOB, country,
  birthplace, Wikimedia photo, Twitter / Instagram, ESPNcricinfo
  + Cricbuzz player IDs. Cached at
  `data/curated/wikidata_enrichment.json`. Profile page surfaces
  the photo + DOB + age + clickable social row.
- **Scout** — NumPyro hierarchical Bayes ratings (ADVI default +
  NUTS available) with opponent-strength bridging; Neo4j scout
  graph with FACED + TEAMMATE_OF + PLAYED_IN edges + traversal
  helpers (`co_faced_bowlers`, `teammate_overlap`,
  `find_replacement`).
- **Dismissal-aware ratings** — the Bayes fit is a joint model: a
  runs Negative-Binomial + a per-ball dismissal Binomial. Each
  batter gets a scoring skill AND a survival (dismissal-resistance)
  skill; each bowler an economy AND a strike (wicket-taking) skill —
  four opponent-adjusted axes, all higher = better. A player's
  composite `value` is the two axes summed, so a fast slogger who
  gets out often no longer outranks a complete batter on scoring
  alone.
- **Probabilistic skill head-to-head** — `cricdex compare A B`
  reports `P(A is genuinely better than B)` per role (complete
  batting / bowling value) from the difference of their Bayesian
  posteriors; near-50% reads as "too close to call". Surfaced in
  CLI, TUI and the Streamlit Compare page.
- **Dismissal fingerprint** — per-batter, per-bowler and per-matchup
  breakdown of *how* a player gets out / takes wickets (bowled / lbw
  / caught / stumped …), with a one-line scouting read. Descriptive
  metadata, separate from the skill model.
- **Auction** — MILP squad optimiser, Monte-Carlo price-band
  simulator (10 real IPL franchises with editable bidding
  personalities + a `~/.cricdex/teams.yaml` override), GRPO RL
  self-play scaffold (real-IPL pool + 6 franchise archetypes +
  terminal squad-quality bonus), war-room substitute advisor.
  Player pricing keys off the dismissal-aware complete value.
- **Rules Q&A** — 11k+ parsed clauses from 21 versioned PDFs
  (MCC, ICC PCs, IPL, Hundred, BBL/WBBL, SA20, Cricket Australia
  domestic, ICC Codes, Anti-Corruption); dense (snowflake-arctic-
  embed-l-v2 + Matryoshka-384) + BM25 + RRF fusion + Jina rerank.
  Cited clauses now render with human-readable titles + URLs.
- **Identity** — Cricsheet People Register cross-source bridge;
  manual nationality overrides for known same-name collisions
  (Rashid Khan, Mohsin Khan).
- **Test coverage** — 70 unit + integration tests covering metrics,
  auction, scout, venues, rules, API routes, skill head-to-head,
  dismissal fingerprint.
- **Docs** — README rewritten CLI-first; `docs/CLI.md` exhaustive
  command reference; `docs/FIRST_RUN.md` onboarding; `docs/TODO.md`
  phase-grouped pending work; `docs/VNEXT.md` items moved out of
  v1 scope.

### Fixed

- Venues `phase_run_rates` crash on `Eden Gardens` —
  `JOIN ... USING (match_id)` ambiguity on `match_type`; every
  column inside the SQL is now alias-qualified.
- Player Profile no longer dumps raw JSON for novel metrics or
  Bayes ratings; renders human-readable tables + sentences.
- Compare empty cells render as `—` with a one-line explanation of
  which threshold excluded the row.
- Rules Chat citation strings switched from cryptic
  `cricket_aus_oneday_cup_2025_26 §24.2.1` to human-readable
  `Marsh One-Day Cup 2025-26 Playing Conditions, clause 24.2.1` +
  publisher URL.
- `cricdex dashboard` auto-picks a free ephemeral port (8501 was
  colliding on dev VMs).
- Player Twins / find_replacement direction-bug — bowler targets
  used to surface batter cohorts (and vice versa) because the
  earlier `role == 'bowler'` test fell over the lenient 60-ball
  all_rounder threshold, then the `bowling_style IN [pace, spin]`
  fallback tripped on part-time bowlers like Kohli / Rohit. Now
  uses `balls_bowled > balls_faced` on both target and candidates
  — unambiguous.
- Profile page metrics empty for everyone outside the top-10 —
  `compute_metrics.py all` was emitting only top-100 rows (and old
  runs had top-10 lying around on disk). Default bumped to top-500;
  re-emitted for every ingested collection. Bayes-rating sentence
  now reads from `profile.bayes.bayes_batter.skill` instead of the
  non-existent flat `bayes_skill_batter` key.

### Removed / dropped from v1

- **Cricsheet-only scope cull** — deleted every non-Cricsheet source
  and the LLM-convenience features built on them, so the codebase is
  exactly what ships: `pulse` (Reddit sentiment), `live` (Cricbuzz),
  `commentary_translate`, `reports` (match reports), `newsletter`,
  and the orphaned `drs` module — plus their CLI commands
  (`translate`, `match-report`), TUI tabs (Translate, Match Report →
  TUI now 10 tabs), Streamlit pages (4_Match_Reports,
  9_Translate_Commentary → dashboard now 10 pages), API routes
  (`/v1/translate`, `/v1/match-reports`), and `scripts/` entry
  points. Dropped 4 blocked rule sources from the manifest
  (sa20_pc_2023, wpl_pc_2026, bcci_domestic_pc,
  bcci_code_of_conduct_2025) — the 21 ingested PDFs are unaffected.
  Everything now derives from Cricsheet ball-by-ball + the People
  Register + one-time Wikidata enrichment.
- DRS Practice dashboard page (was a hand-curated FAQ stand-in
  for the eventual Hawk-Eye CV simulator — moved to year-2 vNext
  group D, scenario JSONL stays on disk).
- Streamlit page filenames A/B/C → renumbered 9/10/11 for
  consistent sort order.
- "~70% / 73% val accuracy" and Brier numbers stripped from user-
  facing copy (kept in CHANGELOG); calibration described in plain
  terms instead.
- Cloudflare R2 backup CLI + `r2_*` config (terminal users own
  their `~/.cricdex/data/`).
- Newsletter email send via Resend (BYO mailer if needed; digest
  remains a Markdown artifact).
- `python-telegram-bot` + `praw` extras (never wired).
- Dead config slots: `openai_api_key`, `groq_api_key`,
  `cerebras_api_key`, `anthropic_api_key`, `cohere_api_key`,
  `qdrant_api_key`, `reddit_*`, `telegram_bot_token`, `resend_*`,
  `langfuse_*`, `hf_token`.

### Known caveats (see [`docs/VNEXT.md`](VNEXT.md))

- Datacenter-IP-blocked feeds: Wikidata, Reddit, Cricbuzz live,
  Cricinfo profiles, BCCI Domestic (Ranji + Hazare), WPL/SA20
  PDFs. Pipelines work end-to-end from residential IPs.
- CricHeroes grassroots ingest deferred to year 2.
- Photo-CLIP identity disambiguation deferred (blocked by
  CricHeroes).
- Auction RL multi-agent PettingZoo training deferred (GPU
  budget).
- OpenBoundary Hawk-Eye, ChuckCheck elbow-flex, ScoutVLM,
  Highlight CV, voice-cloned commentary — year 2.
