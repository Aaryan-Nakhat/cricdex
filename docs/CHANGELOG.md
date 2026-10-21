# Changelog

All notable changes to CricDex. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic
versioning starts at v0.1.0.

---

## [Unreleased]

Rebuilt the Scout and Auction rooms, then unified **every surface** (web,
CLI, Textual TUI, Streamlit) onto a **single source of truth** — the React
web app is canonical and the desktop surfaces mirror its analytical pages,
running the same algorithm over the same exported JSON inputs, locked by a
parity test. As part of that consolidation, three legacy subsystems were
**deleted entirely** (no longer advanced/research views, no longer present
at all): the **Rules Q&A** RAG stack, the **Neo4j scout graph**, and the
**MILP auction solver + war-room advisor + GRPO RL**.

### Model fixes: identity, NGI hygiene, context-adjusted ratings, eras

- **Every number is keyed by the registry id, resolved per match** (roadmap F1).
  `common/sql.py::keyed_balls` / `keyed_wickets` swap each player column for the id from that
  match's `players_<col>` registry and keep the scorecard spelling alongside; metrics, NGI, ratings,
  records, phase boards, matchups, partnerships, aging, cohorts, style twins, profiles and the
  exporter's players / match counts / activity / teams all group by it, and `relabel` adds `name`,
  `cricsheet_id` and `display_name` back for display. Two different players who share a scorecard
  name in one league (among players who batted or bowled: 38 names in men's T20Is, 7 in the BPL, 7 in SMAT, 3 in the PSL, 1 each in the IPL and The Hundred) are no longer merged
  (`tests/test_namesakes.py`). Profiles, cohorts and style twins are built by id; the site links rows
  by id first.
- **NGI** (roadmap 6–11, Tier A #5): every ball scored **out of fold** (5 folds by match; the 70/15/15
  split still reports accuracy, Brier, log loss and now ECE); **beta calibration** instead of isotonic
  (balls with ΔWP exactly 0: 70% → 23% on the IPL); **monotone constraints** (wicket balls raising
  batting WP: 3.9% → 0.01%); **ties labelled 0.5**; ΔWP split into play / wicket / extras and
  **credited** to the striker, the batter who is out (non-striker run outs debit him), the bowler
  (wides and no-balls are his, byes and leg-byes nobody's) and the **fielders** (20% of a catch or
  stumping, all of a run out) — new `ngi_fielding` column; NGI per match divides by **appearances in
  the playing XI** (`match_players_<col>`). Three era-relative features (current rate, target and
  required rate against the league's recent scoring level) cut the log loss on a held-out 2026 IPL
  season from 0.607 to 0.530. `compute_metrics.py ngi-diagnostics` prints all of these checks.
  Window and era boards reuse the league's cached out-of-fold scores (`data/metrics/.ngi_cache/`).
- **Ratings** (roadmap 12, 13, 15, 16, Tier A #4, #6): cells by season, phase, innings and venue with
  a **season random walk**, phase / innings fixed effects and a hierarchical **venue** term in both
  the runs and the dismissal models; **NegBin concentration = alpha × balls**; **batting-slot and
  frontline / part-time prior means**; a **wides + no-balls sub-model** folded into bowler economy.
  `value` is centred on the role's average and scaled by its full population spread.
  `variant="legacy"` keeps the old model for comparison; `scout_rate.py` writes the fitted context
  to `scout_context_<col>.json`; `bayesian.heldout_loglik` scores a later season ball by ball.
- **`value` in runs** (roadmap review 14, Tier B 16; `scout/ratings/runs_value.py`,
  `MODEL_VERSION` 2026.10-runs): runs per 100 balls above the league's average ball, a wicket priced at
  its run cost **where the player plays** — a value function over (over, wickets down) from the
  league's first innings, `λ = V(next ball, w) − V(next ball, w+1)` (IPL: ~14 runs early in the
  powerplay, 7–8 in the middle overs, 2–3 at the death), averaged over each player's own states and
  computed per posterior draw. Replaces the equal-weight sum of two sd-scaled axes, which made MS Dhoni
  the best active IPL batter (3.32 ahead of KL Rahul 3.31 and Kohli 2.97); now Dhoni is +1.1 runs per
  100 balls (40th of 64 active batters with 600+ balls) and Russell (+24.5), Abhishek Sharma, Salt,
  Head, Bairstow, Buttler and KL Rahul (+19.4) lead. New columns `value_rate`, `value_wkts`,
  `wicket_cost`; the wicket-cost table goes to `scout_context_<col>.json`. **Prices re-calibrated**:
  tier discounts, translation sds and the IPL-relevance penalty × 13.3 (the measured sd ratio; SMAT
  17.0, BBL / SA20 / PSL / ILT20 / Hundred 6.0, the rest 8.5; penalty 36), curve `3.15 × e^(0.079 ×
  value)` (was `1.1 × e^(0.95 × value)`) for the same pool median (1.17 vs 1.18 cr) and the same 25
  players at 10 cr+; Python ⇄ TS parity kept. **Prices use a cautious estimate**, `value − 0.5 ×
  value_sd` (`PRICE_CAUTION_SD`, `pricing.py` ⇄ `auction.ts`; `est_value(..., value_sd)` /
  `estValue(..., valueSd)`, used by the auction pool, Scout prices and the gem board): the exported
  pool and scout rows now carry `value_sd` (the blended value's sd, translation uncertainty included),
  and the curve was re-fitted to `4.03 × e^(0.0743 × priced value)` (median 1.18 cr, 25 at 10 cr+).
  Priyansh Arya drops from the 27 cr cap to 20, Ayush Mhatre 24.3 → 18, Inglis 18.8 → 14; proven stars
  move up slightly (Kohli 9.3 → 10.0, Rashid 15.6 → 16.3); Suryavanshi (+59.7 ± 12.5) stays at the cap.
  `value` itself stays the central estimate for display and rankings. **A price ceiling that rises
  with IPL evidence**: `27 × (0.5 + 0.5 × min(1, IPL balls in the role / 600))`
  (`CEILING_FULL_BALLS`, `CEILING_FLOOR_SHARE`, `price_ceiling` ⇄ `priceCeiling`), applied after the
  cautious estimate in the pool, Scout prices and the gem board; pool and scout rows carry
  `target_balls`. Suryavanshi 27 → 23.6 cr, Finn Allen 27 → 17.2; median and 10 cr+ count unchanged.
  The auction simulator also caps each player's sale price at his ceiling (pool rows carry
  `price_cap`), so bidding can't push a thin-IPL player to the 27 cr record either. The backtests score the overall axis in the same runs
  currency (`runs_value.observed_value`); established IPL players 2021–26 (3 seeds), overall: batters
  0.19 vs 0.15 career, bowlers 0.15 vs 0.11 (on the old z-sum yardstick 0.20 vs 0.15 and 0.10 vs 0.07,
  against 0.14 vs 0.15 and 0.12 vs 0.07 published with the sd-sum value); single axes and held-out
  log-likelihood unchanged. Newcomers, overall in runs: batters 0.08 vs 0.10 and bowlers 0.22 vs 0.26 (all
  13 leagues), batters 0.11 vs 0.06 (78% of resamples) and bowlers 0.22 vs 0.25 with the original five;
  every Holm p = 1.0. The 96–98% newcomer-batter lean below came from the sd-sum value and is withdrawn.
- **Eras in the registry**: `[[league.era]]` (the IPL's `impact`, "Impact Player era", since
  2023-03-31). The exporter builds an `era_<key>` window next to last1y / last3y, lists it in
  `meta.windows` / `meta.window_labels`, and the period selectors offer it (site Leaderboards,
  Streamlit Leaderboards via `common.filters.windows_for` / `window_label`, the TUI's LEADERS tab,
  which follows the chosen league).
- **Venues**: par for the last three seasons up front, all-time beside it, and a season-by-season
  par table (`innings_totals_recent`, `innings_by_season` in venues.json).
- **Backtests fixed, and the headline corrected** (roadmap 33–36, 37 in part): `backtest_newcomers.py`
  pools a player's leagues by precision (not the best league, which was biased upward), gives the
  baseline the same league centring and tier discount as the model (it used to compare the
  tier-discounted model with unadjusted raw numbers), reports all six role × axis tests with a
  bootstrap one-sided p and its Holm adjustment, runs 3 ADVI seeds, a 30 / 120-ball playing-time
  sensitivity check, caches fits keyed by `bayesian.MODEL_VERSION` (an older model's fits are never
  reused) and runs them in parallel (`--jobs`). `backtest_ratings.py` runs 3 seeds and adds the
  held-out log-likelihood per ball, with `--compare legacy`.
  **Corrected conclusion:** the old headline, a survival edge for newcomer batters "solid in 97% of
  re-draws", does not survive the fair baseline; it was mostly the league discount itself. With the
  runs-currency `value` (above), the ratings beat career averages for established IPL players
  (overall: batters 0.19 vs 0.15, bowlers 0.15 vs 0.11) and the new model predicts held-out balls
  better than the old one in every season 2021–26 (runs −0.6212 vs −0.6255, dismissals −0.1467 vs
  −0.1480 nats per ball). For IPL newcomers rated from other leagues they are no better than the
  players' own league-adjusted numbers (batters 0.08 vs 0.10, bowlers 0.22 vs 0.26 with all 13 other
  leagues; a lean for batters with the original five only, 0.11 vs 0.06, 78% of resamples); every Holm
  p is 1.0. An interim overall lean for newcomer batters (96–98% of resamples) came from the old
  sd-sum value and is withdrawn. New tables in METHODOLOGY §8, the README, the site's
  About page and `docs/media/backtest.png`; the hero video's backtest scene says the same.
- **`scripts/rebuild_all.sh --from ratings|metrics|export`** restarts a rebuild at that stage without
  re-downloading.

### Player master (names, capped, roles, squads)

- **`scripts/build_player_master.py`** (`make player-master`) builds one identity record per player
  of every exported league into `data/curated/player_master.json`: fan display names (Wikidata label
  by ESPNcricinfo id or the People Register, checked by the LLM, reviewed overrides win), full name
  and every alias, **capped** from Cricsheet's men's T20I / ODI / Test XIs, role from the ball data
  plus the Wikipedia infobox (the LLM taxonomy is now the last resort), bowling style / arm /
  category, batting hand, ISO country (`scout.identity.countries`), active / retired, the 2026 IPL
  squad and date of birth. Disagreements go to `player_master_review.json`; corrections to
  `player_overrides.json`.
- **Exporter**: players.json and profiles carry the identity block; every player of a league gets a
  profile (no dead links; tested), windowed boards count matches inside the window, numbers are
  numbers, stale leagues (SMAT) are flagged, retired players leave the auction pool, capped players
  leave the uncapped pool, impossible values stop the export, `--out` / `--skip-prep` allow a scratch
  export with no DB writes. Profiles gain the standard stat line (50s / 100s, highest score, best
  bowling, hauls, dots) and 25 style twins with country.

### League registry and complete Cricsheet ingest

- **One league registry** — `config/leagues.toml` (read with the standard-library `tomllib` by the new
  `cricdex.leagues`, validated on load; `python -m cricdex.leagues check | list | json`) is the only list of
  competitions: key, name, Cricsheet zip(s), gender, kind, region, strength tier and discount (with a
  `calibrated` flag), export, Scout pool (draftable, gem pool), auction pool, and the auction target's
  nationality allow/deny lists (Pakistan excluded as data). It replaces six disagreeing hard-coded lists:
  the ingester's collection map and 38 state-team zips, the exporter's default and auction-pool lists and
  tier tables, the newcomer backtest's leagues, `TIER_PENALTY` in Python and TypeScript, the web's labels,
  Scout tiers and `ScoutIndex` type, the parity harness, the TUI / CLI / Streamlit Scout tiers and
  collection pickers, the refresh workflow's default list and SMAT special case, `data_cmd.py`, the
  Makefile and the Update Data page (now a select). Adding a league is one entry: `docs/LEAGUES.md`.
- **Eight more men's leagues exported** — PSL, ILT20, The Hundred, MLC, BPL, LPL, Super Smash and CSA T20
  Challenge join the original eight (sixteen exported in all). New leagues borrow a strength discount by
  analogy (PSL / ILT20 / Hundred 0.45 like BBL / SA20; MLC / BPL / LPL / Super Smash / CSA T20 0.64 like
  CPL / Blast), marked `calibrated = false`. Women's leagues, Tests and ODIs are in the registry with
  `export = false`.
- **`leagues.json`** — the exporter writes the registry to `site/public/data/leagues.json`; the web app
  reads labels, Scout panels, price discounts and pool membership from it (`site/src/lib/leagues.ts`), and
  `web_parity/pricing.py` reads the same registry, so the parity test now iterates the registry's tiers.
  `collections.json` follows registry order. `GET /v1/leagues` serves it from the API.
- **API**: an unknown `?collection=` is a 400 listing the valid keys (time windows of known leagues pass).
- **`make refresh-all`** — every exported league: ingest all → people register → ratings for all →
  metrics for all → one export. `scripts/ingest_cricsheet.py all | list`.
- **Time windows** (`_last1y`, `_last3y`) defined once, in `common/sql.py`.

#### Fixed

- **Dead Cricsheet download names** — ILT20, The Hundred (men, women) and WBBL were never ingested
  (`ilt20_male`, `hundred_male`, `hundred_female`, `wbbl_female` 404); now `ilt_male`, `hnd_male`,
  `hnd_female`, `wbb_female`. MLC was listed but never pulled; now exported. An opt-in network test
  (`CRICDEX_NET_TESTS=1`) HEADs every registry zip.
- **SMAT from Cricsheet's one `sma_json.zip`** (695 matches) instead of 38 state-team zips (689 — the
  six missing matches were between Himachal, Jammu & Kashmir and Punjab, sides no state-team zip covered).
  The collection key stays `indian_domestic_male`; `ingest_cricsheet.py indian-domestic` is a deprecated
  alias.
- **Rain-reduced chases** — the chase in NGI's win-probability state and in Pressure Runs now uses the
  target Cricsheet records (`innings_<col>.target_runs`, `target_overs` × balls per over), so DLS chases
  are scored against the revised target and shortened overs. A database ingested before the
  `innings_<col>` table existed falls back to first-innings total + 1. METHODOLOGY no longer says
  Cricsheet doesn't flag D/L.
- **NGI's state table has a fixed row order**, so the fitted win-probability model is reproducible run to
  run (its calibration error had wobbled across the test threshold).

#### Changed

- **Complete Cricsheet parser** (`SCHEMA_VERSION = 2`, stored per match and in a new `ingest_meta` table;
  every optional key may be missing). `matches_<col>` gains gender, team type, season, event match number /
  stage / group, balls per over, outcome method (e.g. "D/L"), eliminator, bowl-out, by-innings, player of
  the match, officials, supersubs, missing-data notes, data version, revision. New `innings_<col>`
  (target runs / overs / balls, declared, forfeited, super over, penalty runs pre / post, absent hurt,
  miscounted overs, powerplays). `balls_<col>` gains one column per extras type, non-boundary, the number
  of wickets on the ball and the DRS review (by, umpire, batter, decision, type, umpire's call);
  `extras_type` stays the first extras key. `wickets_<col>` gains the wicket's position on the ball and
  substitute flags aligned with the fielders. New `replacements_<col>` (Impact Player, concussion and
  injury replacements) and `match_players_<col>` (each team's listed players with Cricsheet ids). Existing
  columns keep their names and meaning.
- **Draftable Scout pools** only list players the auction target's nationality rule admits.
- `scripts/backtest_newcomers.py` rates newcomers from every non-IPL auction-pool league by default;
  `--leagues bbl,sa20,cpl,blast,indian_domestic_male` repeats the published run.

### Docs

- **`docs/METHODOLOGY.md`** — one plain-English explanation of every model (data and identity, NGI, the
  nine metrics, Bayesian ratings, Scout, skill → crore pricing, the auction, the backtest) with worked
  examples and an honest limits section. New `docs/README.md` index, plus READMEs for
  `src/cricdex/web_parity/` and `scripts/`.
- **One roadmap** — `docs/TODO.md`, `docs/VNEXT.md`, `docs/DEFERRED.md` and `docs/SHIPPING.md` merged into
  `docs/ROADMAP.md` (shipped / next / later / out of scope); hosting notes moved into `ARCHITECTURE.md`.
- **Drift fixed** — `STUDY_GUIDE.md` (auction pricing and tier penalties in today's value units,
  budget-aware bidding, `value` as a population-sd sum, non-centred priors, ADVI vs NUTS check),
  `AUCTION_MATH.md` (IPL-relevance discount, real retention prices), `IDENTITY.md` (names now resolve
  through each match's registry; current register counts), `METRICS.md` (where super overs are still
  counted), broken relative links in module READMEs.

### Added

- **Aging curves** — a new page (web / Streamlit / TUI / CLI) plotting batting &
  bowling performance vs age. Each player-season (≥60 balls) is a data point,
  averaged by integer age into a curve (batting SR / average, bowling economy /
  strike-rate), with an optional per-player trajectory overlay. New `aging.json`
  export; ages from the Wikidata dob (~⅓ of players, elite-skewed; survivorship
  uncorrected — flagged in the UI). The IPL batting-SR curve peaks ~26–33 and
  tapers after ~37, as expected.
- **Fielding & Wicketkeeping boards** — two new leaderboards from the
  `balls.fielders` dismissal field (the least-quantified discipline). Per fielder:
  catches / stumpings / run-out involvements → **Wicketkeeping** (keepers) and
  **Fielding** (outfield) boards, split by role so keeper catches don't swamp the
  outfield list. Caught-and-bowled excluded (a bowling wicket); every fielder in a
  multi-fielder run-out credited. Rides the standard metric pipeline → appears on
  all 4 surfaces' leaderboard switcher. (Dismissal counts, not diving range —
  that needs video.) Effect (ipl): keeping top = Dhoni 258, fielding top = Kohli 146.
- **Partnerships** — a new page (web / Streamlit / TUI / CLI) of batter-pair
  stands from `non_striker`: a player's most productive partners + the all-time
  best partnerships (runs, innings, best stand, SR, average, fifty/hundred stands;
  runs include extras while both were at the crease). New `partnerships.json`
  export. (Kohli–de Villiers 3134 runs / 10 hundred-stands.)
- **IPL-relevance weighting for the auction pool** — league-only veterans (e.g.
  Imran Tahir, who still plays SA20 at 46 but hasn't featured in the IPL for
  years) no longer top the IPL auction. The recency penalty was keyed on "last
  match in *any* league"; now last-played is tracked **per league**, and each
  player carries an **IPL-relevance** weight (current IPL regular ≈ 1.0 — age
  barely matters; stale-IPL decays by years-since-IPL; never-IPL = uncapped-
  Indian prospect 0.7 / overseas leaguer age-driven). It's baked into the
  exported auction value (so the TS + Python sims stay in lock-step — no
  algorithm change), with the breakdown exported as columns on `auction_pool`
  rows (`last_ipl`, `home_league`, `age`, `ipl_relevance`) plus a new
  per-player **`activity_index.json`** (cross-league last-played + age). Effect:
  Tahir 0.40 → 0.155 (≈ #5 → #96); current stars unchanged (Kohli #15, Bumrah #2).
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
- **Four new analytical offerings**, shipped in sync across **all four
  surfaces** (React canonical · Streamlit · Textual TUI · CLI), reading the same
  exported JSON, each with the full player filter bar where applicable:
  - **Matchups** — batter-vs-bowler head-to-heads (as batter / as bowler) plus a
    batter's **pace-vs-spin** split with a "weaker vs" read (`metrics/matchups.py`
    → `matchups/<cid>.json`).
  - **Phase specialists** — powerplay / middle / death boards: best strike rates,
    tightest economies (`metrics/phase.py` → `phase.json`), filterable by
    activity / role / bowling / position / country / min-balls.
  - **Form board** — each metric recomputed over the recent window vs the career
    baseline, direction-corrected "form Δ", heating-up / cooling-down, with the
    full filter bar + recent-window picker (derived from the existing windowed
    leaderboards, no new export).
  - **"The next X" gems** — a pick-independent board of standout uncapped SMAT
    prospects (high standing on below-median exposure), added to Scout.

  New surfaces: web **Matchups / Phase / Form** pages; Streamlit
  **11_Matchups / 12_Phase / 13_Form**; TUI **Matchups / Phase / Form** tabs;
  CLI `cricdex matchups|phase|form`.
- Canonical desktop entry points: `cricdex scout look-alikes`,
  `cricdex auction room`; Streamlit **Scout** + **Auction room** pages; the
  TUI **Scout** + **Sim** tabs — all web-identical.
- **Full desktop↔web feature parity** for the analytical pages. The Streamlit +
  TUI Leaderboards gained the **time-window switcher** (all-time / last 3 yrs /
  last 1 yr) and the **full filter bar** (role / activity / bowling / position /
  country / min matches); the Player Profile gained the **Graph cohort** card and
  a ±σ skill-uncertainty band; Compare/Head-to-Head/Venues gained charts (radar /
  gauge / phase bars — Plotly on Streamlit, **plotext** on the TUI); the
  Intent-Curve sparkline now renders per-row; Records gained a year-range filter.
- **Shared single-source modules** so the surfaces can't drift: `common/filters.py`
  (FilterBar + windowed/cohort loaders, parity-locked by
  `test_scripts/test_filters_parity.py`), `common/metrics.py` (the 10-metric
  catalog), `common/spark.py` (sparkline).
- **Graph cohort restored as pure DuckDB SQL** (`scout/cohort.py`) — "faced the
  same bowlers / bowled to the same batters", no Neo4j. `export_site.py` writes
  `cohorts/<cid>.json` again (the writer had been removed with the graph stack,
  leaving the web/desktop cohort card reading stale orphan files).
- **Searchable player/venue pickers on the desktop** — Streamlit selectboxes +
  Textual `textual-autocomplete` filter on "Full Name (Short)" (type either),
  mirroring the web Combobox; collection + record-board fields are dropdowns too.
- **TUI auction brought to full parity** — editable per-team retentions editor,
  the Marquee table and a per-team representative-squad viewer (was a lone
  summary table), pool-scoped Find-player, and a Scout→Auction **Draft** with the
  web's "not in the priced pool" guard. Streamlit auction: retentions open by
  default, squad chips, choose which team keeps a drafted prospect.
- **abtop-style TUI restyle** — Tokyo-Night default + `t` theme cycler, titled
  bordered panels with focused-panel emphasis, a thread-worker spinner on the
  auction sim, coloured plotext charts, a two-colour H2H probability gauge, and a
  styled key-hint footer.

- **Ratings backtests** — `scripts/backtest_ratings.py` (established players,
  fit before each season, score that season vs raw career averages) and
  `scripts/backtest_newcomers.py` (IPL newcomers rated from BBL/SA20/CPL/Blast/
  SMAT only vs their raw numbers there). Results on the How-it-works page and
  in the README: no edge over career averages for established players; an edge
  for newcomer batters, none for newcomer bowlers. `bayesian.fit` gains
  `before=` (date cutoff) and `half_life=` (recency weighting, off by default —
  it didn't help in the backtest).

### Fixed

- **Scout prices and the auction's free agents used stale other-league ratings.** The local rebuild
  exported IPL (whose Scout index and auction pool read every league's ratings) before the other
  leagues were refit, so BBL / SA20 / CPL / Blast / SMAT players carried outdated, much smaller values:
  e.g. Nortje (SA20) priced at 1.1 cr instead of 9.2 cr, and 272 of 600 pool players at the 0.3 cr floor
  (median 0.37 cr) instead of 43 (median 0.97 cr). The rebuild now refits every league before any export
  (the GitHub refresh already did).
- **Pressure Conversion counts only wickets the bowler is credited with** — a run-out on the next ball
  isn't the bowler's squeeze paying off.
- **Super overs left out everywhere, Wicket Quality fitted in order, Slow-Start Cost explained right.**
  Boundary Dependency, Dot-Ball Recovery, Slow-Start Cost, Pressure Conversion, Wicket Quality, the
  fielding boards, matchups, partnerships, aging, player ball/match counts, cohorts and the rating model
  now use only the two main innings of a limited-overs match, like every other stat (guarded by
  `tests/test_super_overs.py`). The refresh workflow and `make refresh` fit the ratings before computing
  the metrics, so Wicket Quality is no longer empty on a fresh run (`compute_metrics` warns when the
  ratings file is missing). Slow-Start Cost's text now says what it measures: career strike rate minus
  strike rate over the first 20 balls of each innings (it never compared batting first with chasing);
  Pressure Conversion's text spells out its 4-dot streak rule. A new test keeps the web and Python
  metric text identical.

- **Auction room: a team with a big purse left half of it unspent, and stars
  cleared far above any real price.** Teams now bid harder when they have more
  money per open squad slot than the league (and softer when stretched), and no
  player clears above 27 cr (the real record). Mega run: Punjab (one retention)
  spends ~119 of 120 cr instead of ~62; every squad reaches 20; top prices
  27 / 27 / 26 cr instead of 43 / 39 / 31. Same change in the browser and the
  Python room (parity test passes).
- **Intent-Curve time windows were empty** — its per-bucket threshold (200 balls)
  is unreachable over a 1-yr window. `compute_metrics all` now scales the bucket
  minimum for windowed collections (last1y → 25, last3y → 80); the all-time board
  is unchanged. `intent_curve.last1y` 0 → 80 rows.
- **Post-sim player search** (web, Streamlit **and** the TUI Sim tab; mega &
  mini everywhere): after a run, look up any player — retained (by which team),
  sold (most-likely buyers, sold-%, avg price), or unsold. Backed by a new
  per-player `outcomes` summary the sim emits across all trials (parity-locked
  TS ⇄ Python). The TUI Sim tab also gained the Mega/Mini toggle.

- **More leagues — SA20 + CPL + T20 Blast.** Ingested SA20 (South Africa), CPL
  (West Indies) and the T20 Blast (England) and folded them into the
  cross-collection auction pool (free agents; tier-discounted SA20 −0.07 / CPL
  −0.10 / Blast −0.10) and the Scout as new look-alike tiers, so Scout/Auction
  now span IPL + SMAT + BBL + SA20 + CPL + Blast (was BBL-only overseas). All
  browsable collections too. Fixed two Cricsheet filenames: SA20 = `sat`,
  T20 Blast = `ntb`.
- **Name search via the Register's alias variations.** `resolve_name` now
  consults the People Register's 8.8k name variations (per-collection), so full
  names / alternate spellings resolve ("Jasprit Bumrah" → "JJ Bumrah").
- **Data refresh.** IPL → 2026-05-31 (season end), t20s_male + recently_played
  → 2026-06-02; Blast current to 2026-05-31. SMAT confirmed frozen upstream at
  2024-12-15. Taxonomy (LLM) enriched 363 newly-ingested players; Wikidata
  enriched for new faces. Repaired the ingest pipeline so refreshes are no
  longer silent no-ops (cricsheet CLI + re-extract-on-newer-zip + Indian-
  domestic `--force`).

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

### Removed

- **Rules Q&A** — the entire natural-language rulebook Q&A feature is gone:
  `src/cricdex/rules/`, the `cricdex rules` CLI command, the `/v1/rules/ask`
  API endpoint, the Streamlit **Rules Chat** page, the `data ingest rules`
  slice, the rulebook PDFs + parsed/curated clauses, Qdrant (vector store),
  and the Jina cross-encoder rerank. `jina_api_key` / `qdrant_url` config
  slots removed.
- **Neo4j scout graph** — `src/cricdex/scout/graph/`, the
  `cricdex scout twins` / `find-replacement` commands, the
  `/v1/scout/twins` + `/v1/scout/find-replacement` API endpoints, the
  graph-cohort sections on the Player Profile, the `data ingest graph`
  slice, and the Neo4j docker service. (Cosine **style twins** stay on the
  Player Profile — those never used the graph.) `neo4j_*` config slots
  removed.
- **MILP auction solver + war-room advisor + GRPO RL** —
  `src/cricdex/auction/advisor.py`, the
  `cricdex auction solve` / `recommend` / `simulate` / `train-grpo`
  commands, the `/v1/auction/solve` + `/v1/auction/recommend` endpoints, and
  the Streamlit **Auction Simulator** page + war-room section. The auction
  is now solely the real-rules Monte-Carlo **room** (`cricdex auction room`).
- **docker-compose** `qdrant` + `neo4j` services dropped; the local stack is
  now file-driven (DuckDB + exported JSON).
- **Streamlit Player Twins page** removed; relational graph twins no longer
  exist (cosine style twins remain on the Player Profile).

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
- Dead config slots: the per-provider LLM API keys, `qdrant_api_key`,
  `reddit_*`, `telegram_bot_token`, `resend_*`, `langfuse_*`, `hf_token`.

### Known caveats (see [`docs/ROADMAP.md`](ROADMAP.md))

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
