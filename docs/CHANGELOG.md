# Changelog

All notable changes to CricDex. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic
versioning starts at v0.1.0.

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
- **Novel metrics** — Pressure Runs, Intent Curve, Recoverability,
  Counter-Attack, Boundary Dependency, Sticky Dot Pressure, Phase
  Dilation, Setting Tax, Wicket Quality, **NGI (Net Game Impact)** —
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
- **Auction** — MILP squad optimiser, Monte-Carlo price-band
  simulator, GRPO RL self-play scaffold (real-IPL pool + 6
  franchise archetypes + terminal squad-quality bonus), war-room
  substitute advisor.
- **Rules Q&A** — 11k+ parsed clauses from 21 versioned PDFs
  (MCC, ICC PCs, IPL, Hundred, BBL/WBBL, SA20, Cricket Australia
  domestic, ICC Codes, Anti-Corruption); dense (snowflake-arctic-
  embed-l-v2 + Matryoshka-384) + BM25 + RRF fusion + Jina rerank.
  Cited clauses now render with human-readable titles + URLs.
- **Identity** — Cricsheet People Register cross-source bridge;
  manual nationality overrides for known same-name collisions
  (Rashid Khan, Mohsin Khan).
- **Test coverage** — 57 unit + integration tests covering metrics,
  auction, scout, venues, rules, API routes.
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
