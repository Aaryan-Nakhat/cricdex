# Roadmap

What CricDex does today, what comes next, what's further out, and what it deliberately won't do. How each
shipped model works is in [METHODOLOGY.md](METHODOLOGY.md); the reasoning behind past choices is in
[DECISIONS.md](DECISIONS.md); dated changes are in [CHANGELOG.md](CHANGELOG.md).

CricDex is **Cricsheet-only**: every number comes from Cricsheet's ball-by-ball data, plus the Cricsheet
People Register for identity, a one-time Wikidata pull for dates of birth and photos, and one AI-classified
taxonomy (role, bowling type, batting slot, country).

---

## Shipped

**Data and identity**
- Cricsheet ingest → DuckDB for eight men's collections (IPL, BBL, SA20, CPL, T20 Blast, SMAT, men's T20Is,
  recently played), with all-time, last-3-years and last-year windows.
- One Cricsheet id per player from each match's registry, with the People Register (18,651 players, 99.8%
  linked to ESPNcricinfo) as fallback and ~7,500 name variants for search.
- Merged venue names: one `"<ground>, <city>"` per ground, renamed grounds under their current name, old
  spellings kept as aliases.
- Indian domestic T20 (Syed Mushtaq Ali Trophy) via Cricsheet's state-team archives: 689 matches.
- Wikidata enrichment: date of birth, photo and socials for 331 of 342 cached players.
- AI-classified taxonomy for 2,525 players (an LLM via LiteLLM, any provider set in `.env`).

**Models and metrics**
- **Net Game Impact (NGI)**: a calibrated XGBoost win-probability model, ΔWP per ball credited to batter
  and bowler.
- Nine context metrics: Pressure Runs, Intent Curve, Dot-Ball Recovery, Counter-Attack, Boundary
  Dependency, Pressure Conversion, Wicket Quality, Crease Longevity, Slow-Start Cost.
- Wicketkeeping and Fielding boards: twelve leaderboards in all, each in three time windows.
- Dismissal-aware Bayesian ratings (NumPyro / JAX): scoring, survival, economy and strike skills with
  uncertainty, ADVI by default and NUTS available; checked against NUTS on the IPL.
- Ratings backtests: established IPL players and IPL newcomers rated from other leagues
  (`scripts/backtest_ratings.py`, `scripts/backtest_newcomers.py`).
- Head-to-head probabilities from the rating uncertainty.
- Style twins (cosine k-NN: 13 axes for batters, 3 for bowlers) and co-faced cohorts on every profile.

**Rooms and pages**
- **Scout**: cross-league look-alikes across IPL, SMAT, BBL, SA20, CPL and T20 Blast, with estimated price,
  saving versus the pick, a gem flag, role and batting-slot filters, and one-click draft into the auction.
- **Auction room**: real-rules IPL auction Monte-Carlo with a cross-league pool, IPL-relevance weighting,
  editable Mega / Mini retentions, team personalities, budget-aware bidding, second-price clearing with a
  27 cr cap, two-phase fill and a post-auction player search.
- Matchups, Phase, Form, Partnerships, Aging, Venues, Records (with On This Day), Player Profile and
  Compare pages.

**Surfaces**
- Static website on GitHub Pages (React + Vite), the canonical surface:
  https://aaryan-nakhat.github.io/cricdex/
- `cricdex` CLI and Textual TUI, Streamlit dashboard and FastAPI REST API, all reading the same data.
- `cricdex.web_parity`: the Python twin of the web's Scout, Auction and Head-to-Head logic, held
  identical by parity tests in CI.
- Docker image and Compose stack; a manual `refresh-data` workflow that re-ingests, refits, re-cooks and
  redeploys the site.

---

## Review backlog (2026-10-17)

From an in-depth review against commercial tools, the public analyst community, franchise workflows, open
data sources and the modelling literature. Every item is listed; tick it off when it ships. The "Next" and
"Later" lists below predate this review and overlap with it (fielder credit, era effects, women's leagues).

The player-master pass (2026-10-17, `scripts/build_player_master.py`, see
[IDENTITY.md](IDENTITY.md#the-player-master)) closed items 19–23 and 32, Tier A #2, P1–P3 and P18, and
the capped half of item 26 (the uncapped Scout pool drops anyone with a men's T20I / ODI / Test). Source
disagreements left for a human are in `data/curated/player_master_review.json`.

### Correctness fixes

**Data and ingest**
- [x] 1. Dead Cricsheet download names: ILT20, The Hundred (men, women) and WBBL were never ingested. In
  `scout/ingest/cricsheet.py` `COLLECTIONS`, `ilt20_male` / `hundred_male` / `hundred_female` /
  `wbbl_female` 404; the right names are `ilt_male` / `hnd_male` / `hnd_female` / `wbb_female`. Rename and
  re-ingest.
- [x] 1b. MLC is listed but was never pulled (`mlc_male_json.zip` exists). Re-ingest and add a test that
  every listed collection lands.
- [x] 2. SMAT is rebuilt from 38 state-team zips (689 matches); Cricsheet ships one `sma_json.zip` (695).
  Switch to it, drop the de-dup step, explain the 6-match gap.
- [x] 3. DLS revised targets dropped at ingest: `parse_match_full` never reads `outcome.method` or
  `innings[].target`, and `ngi.py::_build_state_table` uses first-innings total + 1 and scheduled overs, so
  34 IPL rain chases are scored against the wrong target. Store `dls_method`, `target_runs`,
  `target_overs`, use them in the chase state, and correct METHODOLOGY (which says Cricsheet doesn't flag
  D/L).
- [x] 4. Only the first extras key and the first wicket per ball are kept. Store every extras key and every
  wicket.
- [x] 5. Unparsed fields: `replacements` (Impact Player, 557 IPL events), `review` (DRS, 990), `powerplays`,
  `runs.non_boundary`, `fielders[].substitute`, `season`, `event.stage`, `players` (XIs), `officials`,
  `player_of_match`.

**Win probability and NGI (`metrics/ngi.py`)**
- [ ] 6. NGI is scored mostly in-sample (train on 70% of matches, score all). Use 5-fold out-of-fold
  predictions for scoring; keep the test split for reporting.
- [ ] 7. ΔWP is quantised by isotonic calibration steps (small swings read exactly 0). Use smooth
  calibration (Platt, beta or spline) for differences; count how many balls read 0 before and after.
- [ ] 8. No monotone constraints: a wicket could raise the batting side's WP in sparse states. Add
  `monotone_constraints` and log the share of wrong-sign balls.
- [ ] 9. Credit for extras and non-striker run-outs goes to the striker; the bowler gets run-out credit and
  fielders nothing. Give extras to the bowler/team only, debit `player_out`, credit named fielders.
- [ ] 10. Ties are dropped instead of labelled 0.5.
- [ ] 11. NGI per match divides by matches batted or bowled (Kohli 276 vs ~282 appearances). Count
  appearances from the XI (`info.players`).

**Ratings and valuation (`scout/ratings/bayesian.py`, `web_parity/pricing.py`)**
- [ ] 12. No era or season effect (IPL first-innings average ~155 in 2009–13 → 193 in 2026). Add season,
  phase, venue and innings effects with hierarchical priors.
- [ ] 13. NegBin dispersion doesn't scale with balls (variance grows with balls², high-volume edges are
  under-weighted). Use `concentration = alpha * balls` or a per-outcome multinomial; compare held-out fit.
- [ ] 14. `value` is an equal-weight sum of two z-scores (survival means little for a finisher). Move to a
  runs-currency value: runs per ball minus a phase-dependent wicket cost.
- [ ] 15. Bowler economy ignores extras (wides-heavy bowlers flattered). Add extras or a wides sub-model.
- [ ] 16. One population prior for every batter, so tail-enders shrink to "average batter". Use a role or
  batting-slot prior mean.
- [x] 17. Cross-league valuation takes the max over leagues with hand-set tier penalties (Yash Thakur 1.65
  from SMAT vs −0.33 IPL; Unadkat 1.37 vs −0.14). Pool by precision so IPL evidence dominates; later fit
  league effects jointly.
- [ ] 18. The price curve isn't fitted to any sale data, and one curve serves batting and bowling. Fit to
  real auction prices (roadmap 13).

**Tags, flags and data hygiene**
- [x] 19. Wrong AI role/bowling tags in `data/curated/player_taxonomy.json`: Digvesh Rathi tagged right-arm
  fast-medium (leg-spinner; #1 on Wicket Quality), Mitchell Owen "bowler", Gayle / Head / Shashank Singh /
  Raina "allrounder" (×1.15 auction price), Navdeep Saini null; 864 all-rounders vs 462 batters overall.
  Check and override from Wikipedia/DBpedia infoboxes plus a human-reviewed override file; flag
  disagreements.
- [x] 20. Duplicate country codes (RSA/ZAF, SRI/LKA, BAN/BGD, IRL/IRE). Normalise to ISO and add a test.
- [x] 21. Retired players still active (Russell, Ashwin in the pool; Maxwell relevance 1.0 at 37.9; Dhoni
  team None; 27 "active" players with no team). Add retirement and in-squad flags from the 2026 squads.
- [x] 22. No profiles under 300 balls, so leaderboard links dead-end (365 of ~800 IPL players; 49/169 on
  ngi.last1y, 84/226 on fielding.last3y, 51/300 on pressure_runs). Build a profile for every IPL player and
  test every link resolves.
- [x] 23. Time-window boards use career match counts (KL Rahul 149 on the last-year Counter-Attack board),
  so the min-matches filter does nothing. Compute `matches` within the window.
- [ ] 24. Pressure Conversion samples are tiny (median 11 balls; #1 Saini on 2/7; last-year board 4 rows at
  0%). Redefine, add Empirical-Bayes shrinkage and intervals, or hide it.
- [ ] 25. Style twins use cosine on unscaled, mean-imputed features (`style_twin.py::_vectorise`; Mayank
  Agarwal's twins are DJ Bravo, JR Hopes, MF Maharoof). Z-score, per-role feature sets, eyeball 20 famous
  players.
- [ ] 26. IPL-ineligible Pakistani players in Scout pools (30, including Mohammad Amir as a Bumrah
  look-alike in the README), and capped players (Unadkat, Thakur) in the "uncapped SMAT" pool. Add
  eligibility and capped filters.
- [ ] 27. Stale README NGI image (shows Salt #1 at 0.097; live data has Lynn 0.0939, Salt 0.0936).
  Re-render from the data, or generate it in CI.

**Wording, presentation and auction state**
- [ ] 28. Head-to-head overclaims: 75–90% labelled "clearly better" (`headtohead.ts:79`); the README says
  Suryavanshi is 78% "clearly better" than Kohli on a fifteenth of the balls. Softer bands, and say the
  interval covers sampling error only.
- [ ] 29. Boundary Dependency labelled "lower is better" in `metrics.ts` and `docs/media/metrics.png`, but
  METHODOLOGY says "neither". Relabel as descriptive.
- [ ] 30. The profile says "above a replacement batter", but the model is centred on average. Fix the label.
- [ ] 31. Auction state is stale: Mega replays the 2025 retentions (Russell at KKR, Samson at RR); Mini
  gives every team 30 cr and its top 18 free. Load real 2026 squads and purses (roadmap 12).
- [x] 32. Numbers stored as strings in the JSON (`"total_runs":"1028"`; record runs as floats). Use numeric
  types and add a schema test.

**Backtest and evaluation (`scripts/backtest_*.py`)**
- [ ] 33. Newcomer comparison not like-for-like: the model value is tier-penalised, the raw baseline pools
  leagues unadjusted. Give the baseline the same league centring.
- [ ] 34. `_other_league_view` keeps each player's best league rating (biased upward). Use a
  precision-weighted average.
- [ ] 35. Selection on playing time (newcomers need 60+ IPL balls; poor starters get dropped). Note it and
  run a sensitivity check.
- [ ] 36. Multiple comparisons: the "97% of resamples" result (one-sided p ≈ 0.03) is one of six tests and
  isn't significant after correction. Report all six with Holm-adjusted p.
- [ ] 37. Weak target: Spearman on noisy season totals, one ADVI seed, no noise ceiling (roadmap 27).

**Engineering**
- [ ] 38. The CI job named `lint-test` doesn't run ruff or mypy. Add both.
- [ ] 39. The refresh workflow fails silently (`set +e`, best-effort per league, no validation gate, ~70 MB
  committed per run, never run on GitHub). Fail on errors, add assertions, move snapshots out of git.

**To verify (reviewers were unsure or disagreed)**
- [ ] Aging curves: survivorship bias, and date-of-birth coverage (METHODOLOGY says ~a third of players; the
  audit counted 331 of 2,525). Check how the curve is computed.
- [ ] Legal balls vs all deliveries: add one explicit test that every rate uses the right denominator.
- [ ] Effect sizes: re-run the backtests after each of the DLS, isotonic, monotone and NegBin fixes and
  report how much each moved the numbers.
- [ ] Mean-field ADVI: re-check against NUTS after adding context effects (roadmap 4).
- [ ] Impact Player coding is resolved (`reason: "impact_player"`, 557 IPL, 168 ILT20, 43 LPL events); use
  it.
- [ ] Lead the backtest story with the newcomer case; keep the honest established-player tie.

### Roadmap

Effort: S = up to 2 days, M = 3–7 days, L = 2+ weeks.

**Tier A: before the IPL 2027 retention deadline (reported 15 Nov 2026)**
- [x] 1. Ingest correctness sprint (S–M): the zip names, `sma_json.zip`, DLS method and target, all extras,
  both wickets, `season`, `event.stage`, `players`, `replacements`, `review`, `powerplays`,
  `non_boundary`.
- [x] 2. Data hygiene pass (M): taxonomy override from Wikipedia/DBpedia plus a reviewed file, ISO country
  codes, retired and in-squad flags, date-of-birth coverage above 90%, profiles for every IPL player,
  windowed `matches`, numeric JSON, an SMAT-staleness flag on every SMAT number, data-quality assertions.
- [ ] 3. Remove the mockable items (S): fix or hide Pressure Conversion, z-score style twins, retire "clearly
  better", relabel Boundary Dependency and replacement→average, refresh the README image, Scout
  eligibility (no Pakistani players in IPL pools, capped players out of the uncapped pool).
- [ ] 4. Era and season adjustment (M–L): season, phase, venue and innings terms in the Bayesian model; an
  era feature in the WP model; venue par by season; an Impact-era toggle on boards.
- [ ] 5. WP/NGI hygiene (S–M): out-of-fold scoring, smooth calibration, monotone constraints, ties at 0.5,
  correct credit for extras and run-outs.
- [ ] 6. NegBin dispersion fix plus a role-level prior mean, then re-run both backtests (S).
- [ ] 7. Current squads, salaries and purses JSON plus a retention calculator (M): hand-built from the
  Wikipedia 2026 personnel-changes page; retain/release value minus cost, purse left, replacement cost per
  role. Check the official 2027 retention rules first.
- [ ] 8. "True" strike rate and economy (S–M): runs against the same-match, same-phase baseline, on boards
  and profiles.
- [x] 9. Cross-league pooling (S–M): precision-weighted with IPL evidence dominating, instead of the max.
- [ ] 10. Exports and link previews (S–M): CSV/XLSX for every table, Open Graph / Twitter meta tags.
- [ ] 11. Uncertainty everywhere (M): sample-size badges, minimum-sample defaults per window,
  Empirical-Bayes shrunk values, an n-balls badge and shrunk estimate on head-to-heads.

**Tier B: before the mid-December 2026 mini-auction**
- [ ] 12. The IPL 2027 mini-auction room in its real state (M): real squads, released players, remaining
  purses, capped/uncapped base rules, RTM if the 2027 rules allow it, lots run by sets, the registered list
  when published, manual availability and injury flags.
- [ ] 13. Auction price model fitted to real IPL prices (M): Wikipedia personnel pages 2008–2026 (CC BY-SA;
  pre-2014 prices in US$); hurdle model — P(sold) logistic, log(price) hedonic on value, role, overseas,
  capped, age, base price, mega/mini; sale probability plus a price interval; out-of-time test.
- [ ] 14. Bowler-type × batting-hand matchup grid with shrinkage (S–M): right-arm pace, left-arm pace,
  off-break, leg-break, slow left-arm, left-arm wrist spin, vs LHB/RHB, by phase, with n-badges.
- [ ] 15. Opposition dossier PDF (M): opponent plus venue → probable XI, each batter's weak bowler types by
  phase, each bowler's danger batters, venue par.
- [ ] 16. Expected runs and wickets from ball-by-ball context (M–L): log-linear expectation over phase,
  wickets, venue, era, bowler type and balls faced, with shrinkage; a wicket priced in runs; a
  runs-currency value replacing the sd-sum. Don't call it "xR" (CricViz's xR uses ball-tracking).
- [ ] 17. Joint multi-league fit with league effects (M), publishing the translation factors (e.g. SMAT→IPL
  strike-rate factor with intervals).
- [ ] 18. Venue page v2 (S–M): par by season, chase-win curve against target, toss outcomes, phase pars,
  last three seasons by default.
- [ ] 19. New men's leagues (M each): PSL, BPL, ILT20, MLC, LPL, The Hundred, Super Smash — scouting pools
  first, full boards later.
- [ ] 20. Entry-point analysis (S): entry-over bins (1–3, 4–6, 7–11, 12–13, 14–16, 17–20) against SR,
  average and balls; each batter's best entry window and whether the team's order fits.
- [ ] 21. Impact Player and DRS views (S–M): sub usage by team and over, all-rounder bowling usage; DRS
  success by team, keeper and umpire.
- [ ] 22. Player profile v2 plus share cards (M): team, standard stat line, season table, phase splits,
  rating trend, readable units ("+X runs per 100 balls").
- [ ] 23. Refresh workflow gates (S–M): fail on any league error, sanity assertions, a diff report, a real
  run on GitHub, snapshots out of git.

**Tier C: mid-December 2026 to mid-March 2027**
- [ ] 24. Ball-by-ball match simulator (L): per-ball multinomial over dot/1/2/3/4/6/extra/out from batter,
  bowler, phase, wickets, balls faced, venue and era; within-innings dependence; 4-over bowler limit;
  validated on innings totals and match log-loss.
- [ ] 25. XI, batting-order and death-over optimiser on the simulator (M): 4-overseas rule, Impact sub, who
  bowls overs 17–20.
- [ ] 26. Auction value as wins added (M): replace the hand-set need 1.5/0.7 with marginal wins to a squad's
  best XI; calibrate team personalities against real auction moments.
- [ ] 27. Better evaluation (M): held-out ball-level log-likelihood, a split-half noise ceiling, calibration
  of P(A>B) and interval coverage, 3 ADVI seeds, a fair newcomer baseline with Holm-adjusted p,
  year-to-year stability of the bespoke metrics.
- [ ] 28. Women's leagues (M): WPL, WBBL, The Hundred women, women's T20Is.
- [ ] 29. Engineering (M): ruff and mypy in CI; eslint plus vitest on `auction.ts`, `filters.ts`,
  `headtohead.ts`; a Playwright check that every route and link works; route code-splitting (787 KB
  bundle); split `cli/tui.py` (2,693 lines) and `scripts/export_site.py` (1,442 lines); consider dropping
  one of the five interfaces.
- [ ] 30. Small features that sell (S each): fielder credit in NGI and NGI per leverage; a "Table of
  Justice" (deserved standings); value per crore for the last auction's buys; a batter archetype map (true
  dot% × true boundary%).

**Tier D: later or long-shot**
- [ ] 31. Optional licensed-feed importer (L): Hawk-Eye, CricViz, NV Play, Opta, BCCI, keyed on the
  register's `key_pulse`, `key_nvplay`, `key_opta`, `key_bcci`. Ship code only, never data.
- [ ] 32. Indian domestic after 2024 (blocked): contribute to Cricsheet, seek a BCCI or state partnership,
  or use a client feed.
- [ ] 33. Weather and dew (Open-Meteo plus Wikidata venue coordinates; free for non-commercial use only) and
  a hand-curated boundary-size table (M).
- [ ] 34. Research models (M–L): time-varying skill (random walk), correlated priors, within-player aging;
  keep each only if held-out fit improves.
- [ ] 35. Non-IPL auction and draft rooms (L): WPL, ILT20, MLC, SA20.

### Product review (owner, 2026-10-17)

One player-data pass (do together with Tier A #2):
- [x] P1. Common display names everywhere ("Virat Kohli", "Sanju Samson", "Yashasvi Jaiswal" — how fans say
  them, not scorecard initials like "V Kohli" and not legal full names like "Yashasvi Bhupendra Kumar
  Jaiswal"). Keep the scorecard name and full name as metadata; every alias stays searchable.
- [x] P2. A real "capped" flag (international appearances), so capped players (Hardik Pandya, Bhuvneshwar
  Kumar, Tilak Varma, Ishant Sharma…) never appear as uncapped SMAT prospects ("The next big things").
- [x] P3. Correct role and bowling type per player (Hardik Pandya = seam-bowling all-rounder), plus batting
  hand, bowling arm, ISO country, retired / active and current team — checked against open sources with a
  reviewed override file.

Player profile:
- [ ] P4. A "standard stats" view next to the totals: average, strike rate, economy, bowling average and
  strike rate, 50s/100s, best figures, dot %, boundary % — one click.
- [ ] P5. Explain "replacement batter" (what it is, how it's set) in plain words, and draw the baseline
  clearly (today it's a faint dash).
- [ ] P6. Every novel metric has an (i) with what it means and how to read it (higher or lower better,
  what a good value looks like).
- [ ] P7. Style twins: filter by country (same country by default; overseas / all on demand).
- [ ] P8. Pace / spin splits: "out rate" isn't clear — show it as "out once every N balls" (and say what
  the % is of).

Leaderboards and metrics:
- [ ] P9. Every metric says how to read it and whether higher or lower is better, in plain words.
- [ ] P10. NGI in human units (e.g. win chance added per match, wins added per season) instead of raw
  0.097-style numbers; same for NGI total / per match columns.
- [ ] P11. (i) popovers overlap each other and open for the wrong button — fix.
- [ ] P12. Filters are smart: options that can't apply are hidden or disabled (e.g. Fielding board → no
  "wicketkeeper" role filter, since keeping is its own board); audit every page for the same problem.

Compare / charts:
- [ ] P13. "Skill shape" is hard to read — replace with a clearer format.
- [ ] P14. Side by side: show standard stats too, and explain how to read batting / bowling value.
- [ ] P15. Aging curves: smooth, fast updates when selecting several players.

Scout:
- [ ] P16. Same type only: a seam-bowling all-rounder gets seam-bowling all-rounders (not Will Jacks or
  Naman Dhir); same for spin and batting slot.
- [ ] P17. Country filter: same country as the pick by default, overseas or all on demand.
- [x] P18. Fix "The next big things" (uncapped gems) listing capped stars (needs P2).

### Guardrails

- Don't overclaim: no "clearly better" at 75%, no "Crores cheaper", don't call the newcomer result
  significant, don't present crore prices as predictions until roadmap 13 ships, don't call
  context-expected runs "xR".
- Don't rank on tiny samples (no 7- or 11-ball leaders; raw head-to-heads are mostly noise below a few
  hundred balls).
- Don't mix eras: show the Impact-era split.
- Don't scrape (licence RED): ESPNcricinfo, BCCI, iplt20.com and the Pulselive API, FanCode, Kaggle dumps
  scraped from them, or a bundled commentary-text scraper.
- Don't redistribute HawkeyeStats (no licence; derived from Pulselive) — at most a private test fixture.
- Keep Cricsheet attribution and don't imply endorsement (ODC-By / CC BY 4.0); Wikipedia-derived tables are
  CC BY-SA; Open-Meteo needs a paid plan for commercial use.
- Don't invent rules: confirm the 2027 retention and RTM rules from official sources before building the
  calculator.
- Don't spread thin: ship franchise workflows before adding surfaces.
- Don't put ineligible players in IPL pools.

---

## Next

Work that needs no new data source.

- **Fielder and non-striker credit in NGI**: share a catch's or run-out's swing with the fielder, and book
  a non-striker run-out to the batter who was out.
- **Venue, phase and era effects in the ratings**: one skill set per career today.
- **Women's collections**: the ingester already knows the WPL, WBBL and women's T20I archives; nothing
  downstream has been built or checked on them yet.
- **Replacement Delta**: NGI against a replacement-level player ("cricket WAR"). Needs a sub-IPL baseline
  to define replacement level; SMAT is the obvious candidate.

## Later

Bigger pieces, most needing new data, a GPU or hosting.

**Grassroots**
- CricHeroes grassroots tier, if a partner API or a Cricsheet-compatible export becomes available; the
  rating model's opponent bridging is what would carry it (a grassroots batter who faced a few known
  semi-pro bowlers gets a sharper rating through them).
- Photo-based identity disambiguation for namesakes across tiers (only needed once a grassroots tier exists).

**Auction v2**
- Multi-agent self-play (every franchise its own learned bidding policy) instead of today's fixed
  personalities.
- Team personalities learned from real auction bid history instead of hand-assigned.

**Video and voice (year 2)**
- Ball tracking and pitch maps from broadcast video; a bowler-action (elbow flex) estimate from pose;
  automatic highlight clips; ball-by-ball extraction from grassroots video; a voice analyst.
- Disguise Coefficient for bowlers (outcome variance for the same line and length), which needs ball
  tracking.

**API and hosting**
- Auth and rate limiting in front of the REST API (required before any public API deploy), then hosting
  the API and the Streamlit dashboard. The website itself is already public.
- A GraphQL layer over the REST functions, if anyone needs it.

---

## Ongoing upkeep

- **Cricsheet refresh** when new matches land: the manual `refresh-data` workflow for the live site, or
  `make refresh COLLECTION=<c>` locally (download → ratings → metrics → site data).
- **People Register refresh** (Cricsheet updates it roughly monthly):
  `uv run python scripts/ingest_people.py --force` (also the first step of `refresh-data`).
- **Taxonomy for new players**: runs inside `refresh-data` when an LLM is configured.
- **Model checks after changes**: re-run the NUTS comparison and the backtests after any change to the
  rating model.

---

## Out of scope

Decided against, not pending.

- **Non-Cricsheet sources**: Reddit sentiment, Cricbuzz live scores, ESPNcricinfo or BCCI scraping (so no
  Ranji Trophy or Vijay Hazare, which Cricsheet doesn't cover ball by ball), extra rulebook PDFs.
- **LLM-written content**: commentary translation, match reports, newsletters, a rules Q&A bot. The LLM
  only tags player facts.
- **Earlier subsystems removed in the consolidation**: the Neo4j scout graph, the MILP auction solver,
  war-room advisor and RL auction prototype, and the rules RAG stack (see the changelog).
- **Fantasy-team optimiser** and **tournament-management software** (CricHeroes already does the latter
  well).
- **Package distribution**: no PyPI package and no published Docker image. The website is the public
  artifact; running it yourself is clone + `uv` or `make docker-up` (see [RUNNING.md](RUNNING.md)).
