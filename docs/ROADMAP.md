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
- Style twins (per-role ball-by-ball style axes against par, robust z, same role and bowling type; METHODOLOGY §5a) and co-faced cohorts on every profile.

**Rooms and pages**
- **Scout**: cross-league look-alikes across IPL, SMAT, BBL, SA20, CPL and T20 Blast, with estimated price,
  saving versus the pick, a gem flag, role and batting-slot filters, and one-click draft into the auction.
- **Auction room**: real-rules IPL auction Monte-Carlo with a cross-league pool ranked by expected season
  value (P(plays) × contribution per match, METHODOLOGY §6c),
  editable Mega / Mini retentions charged by the 2025 slab rule, every team bidding by a demand model fitted
  on the 2019–2026 auctions (since 2026-10-23; no hand-set personalities), lots as real shortlists in set
  order, IPL ladder clearing within each team's purse (no price cap), an accelerated round and a
  post-auction player search.
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
- [x] 6. NGI is scored mostly in-sample (train on 70% of matches, score all). Use 5-fold out-of-fold
  predictions for scoring; keep the test split for reporting. *Done 2026-10-17: 5-fold out-of-fold scoring; the 70/15/15 test split still reports (IPL OOF NGI correlates 0.94 with the old in-sample).*
- [x] 7. ΔWP is quantised by isotonic calibration steps (small swings read exactly 0). Use smooth
  calibration (Platt, beta or spline) for differences; count how many balls read 0 before and after. *Done 2026-10-17: beta calibration; balls with ΔWP exactly 0 on the IPL 70% → 23%, ECE 0.024.*
- [x] 8. No monotone constraints: a wicket could raise the batting side's WP in sparse states. Add
  `monotone_constraints` and log the share of wrong-sign balls. *Done 2026-10-17: wicket balls raising batting WP 3.9% → 0.01% (IPL).*
- [x] 9. Credit for extras and non-striker run-outs goes to the striker; the bowler gets run-out credit and
  fielders nothing. Give extras to the bowler/team only, debit `player_out`, credit named fielders. *Done 2026-10-17: play / wicket / extras split; rule in METHODOLOGY §2; `ngi_fielding`.*
- [x] 10. Ties are dropped instead of labelled 0.5.
- [x] 11. NGI per match divides by matches batted or bowled (Kohli 276 vs ~282 appearances). Count
  appearances from the XI (`info.players`). *Done 2026-10-17: appearances from `match_players_<col>` (Kohli 279).*

**Ratings and valuation (`scout/ratings/bayesian.py`, `web_parity/pricing.py`)**
- [x] 12. No era or season effect (IPL first-innings average ~155 in 2009–13 → 193 in 2026). Add season,
  phase, venue and innings effects with hierarchical priors. *Done 2026-10-17: season random walk, phase, innings and hierarchical venue terms in both sub-models.*
- [x] 13. NegBin dispersion doesn't scale with balls (variance grows with balls², high-volume edges are
  under-weighted). Use `concentration = alpha * balls` or a per-outcome multinomial; compare held-out fit. *Done 2026-10-17: `concentration = alpha × balls`; held-out fit in METHODOLOGY §4/§8.*
- [x] 14. `value` is an equal-weight sum of two z-scores (survival means little for a finisher). Move to a
  runs-currency value: runs per ball minus a phase-dependent wicket cost. *Done 2026-10-19: runs per 100 balls above the league's average ball, a wicket priced by a first-innings value function at each player's own (over, wickets down) mix (`scout/ratings/runs_value.py`); prices re-calibrated (METHODOLOGY §4, §6; AUCTION_MATH).*
- [x] 15. Bowler economy ignores extras (wides-heavy bowlers flattered). Add extras or a wides sub-model. *Done 2026-10-17: wides + no-balls sub-model folded into economy.*
- [x] 16. One population prior for every batter, so tail-enders shrink to "average batter". Use a role or
  batting-slot prior mean. *Done 2026-10-17: batting-slot and frontline / part-time prior means.*
- [x] 17. Cross-league valuation takes the max over leagues with hand-set tier penalties (Yash Thakur 1.65
  from SMAT vs −0.33 IPL; Unadkat 1.37 vs −0.14). Pool by precision so IPL evidence dominates; later fit
  league effects jointly.
- [x] 18. The price curve isn't fitted to any sale data, and one curve serves batting and bowling. Fit to
  real auction prices (roadmap 13). *Done 2026-10-21: the market price (METHODOLOGY §6b) is fitted to
  the 2018–2026 auctions and is the price everywhere; the curve stays as "on-field worth"; a quantile
  calibration lifts the 10 cr+ lots from ~0.45× to ~0.62× of their price.*

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
- [x] 25. Style twins use cosine on unscaled, mean-imputed features (`style_twin.py::_vectorise`; Mayank
  Agarwal's twins are DJ Bravo, JR Hopes, MF Maharoof). Z-score, per-role feature sets, eyeball 20 famous
  players. *Done 2026-10-22: rebuilt from the ball-by-ball (slot, phase tempo vs par, boundaries / dots,
  spin vs pace, risk; bowlers: phase usage, economy by phase, strike, wicket types, pace / arm), robust z
  with shrinkage, same-role and bowling-type gates; Mayank → Samson, Uthappa, Kishan (METHODOLOGY §5a).*
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
- [x] 33. Newcomer comparison not like-for-like: the model value is tier-penalised, the raw baseline pools
  leagues unadjusted. Give the baseline the same league centring. *Done 2026-10-19: the baseline is each league's
  numbers relative to its average, minus the same tier discount. The old batter-survival edge didn't survive
  it (METHODOLOGY §8).*
- [x] 34. `_other_league_view` keeps each player's best league rating (biased upward). Use a
  precision-weighted average. *Done 2026-10-19: pooled by 1 / (value sd² + tier translation sd²), the auction
  pool's rule.*
- [x] 35. Selection on playing time (newcomers need 60+ IPL balls; poor starters get dropped). Note it and
  run a sensitivity check. *Done 2026-10-19: the script re-scores at 30 and 120 balls; noted in METHODOLOGY §8
  (at 120 balls batters flip, n = 44).*
- [x] 36. Multiple comparisons: the old "97% of resamples" result (one-sided p ≈ 0.03) was one of six tests
  and wasn't significant after correction. Report all six with Holm-adjusted p. *Done 2026-10-19: all six reported;
  with the runs value every Holm p is 1.0, so nothing is significant.*
- [ ] 37. Weak target: Spearman on noisy season totals, one ADVI seed, no noise ceiling (roadmap 27).
  *In part 2026-10-19: 3 ADVI seeds and the held-out log-likelihood per ball are done; the split-half noise ceiling
  is still open.*

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
- [x] Mean-field ADVI: re-check against NUTS after adding context effects (roadmap 4). *Done 2026-10-18 on the IPL: ADVI sds a median 98% (batters) / 92–95% (bowlers) of NUTS's, P(A>B) within a median 2–2.5 points; NUTS r-hat 1.02, 0 divergences.*
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
- [x] 4. Era and season adjustment (M–L): season, phase, venue and innings terms in the Bayesian model; an
  era feature in the WP model; venue par by season; an Impact-era toggle on boards. *Done 2026-10-19: season
  random walk, phase / innings / venue terms; era-relative WP features; venue par by season; `era_impact`
  window on the boards.*
- [x] 5. WP/NGI hygiene (S–M): out-of-fold scoring, smooth calibration, monotone constraints, ties at 0.5,
  correct credit for extras and run-outs. *Done 2026-10-19: correctness 6–11, plus fielder credit.*
- [x] 6. NegBin dispersion fix plus a role-level prior mean, then re-run both backtests (S). *Done 2026-10-19:
  both backtests re-run (METHODOLOGY §8).*
- [x] 7. Current squads, salaries and purses JSON plus a retention calculator (M): hand-built from the
  Wikipedia 2026 personnel-changes page; retain/release value minus cost, purse left, replacement cost per
  role. Check the official 2027 retention rules first. *Done 2026-10-21: **Keep or release** (`cricdex
  keep`, the site page): salaries for all 274 squad players (`scripts/ipl_squad_salaries.py`, 2027 trades
  and retirements applied), the cycle's rules as data in `config/competitions.toml` (each rule sourced or
  marked assumed; the 2027 purse isn't published, 125 cr assumed), price vs salary → Keep / Release /
  Borderline with a reason, purse left, role gaps filled from free agents plus other teams' release calls,
  web ⇄ Python parity (METHODOLOGY §10). Open: the 22 squad players with no ball-by-ball can't be rated;
  four teams' salaries don't reproduce their published 2026 purses (CSK 2.0, DC 3.45, KKR 6.0, RR 4.0 cr).*
- [ ] 8. "True" strike rate and economy (S–M): runs against the same-match, same-phase baseline, on boards
  and profiles.
- [x] 9. Cross-league pooling (S–M): precision-weighted with IPL evidence dominating, instead of the max.
- [ ] 10. Exports and link previews (S–M): CSV/XLSX for every table, Open Graph / Twitter meta tags.
- [ ] 11. Uncertainty everywhere (M): sample-size badges, minimum-sample defaults per window,
  Empirical-Bayes shrunk values, an n-balls badge and shrunk estimate on head-to-heads.

- [x] 11b. Form forecast (M): each player's value over the next three seasons with an 80% range and
  P(regular), for retention and mega-auction contracts. *Done 2026-10-21: `cricdex.scout.forecast` +
  `scripts/form_forecast.py` (walk-forward ratings at every season end, regression to the mean + an age curve
  with an inverse-probability survivorship correction, walk-forward-calibrated ranges); a "Form forecast"
  section on the player profile, `cricdex forecast "<name>"` / `--team`; backtest from 2021–23 against
  four baselines (METHODOLOGY §11). 2026-10-22: starts from each player's current level (a Kalman
  level model with age drift, blended with the career rating by weights chosen on validation), a 15-player
  reality check in §11, and the "3-season outlook" column in Keep or release (page, CLI, CSV, parity).*
**Tier B: before the mid-December 2026 mini-auction**
- [ ] 12. The IPL 2027 mini-auction room in its real state (M): real squads, released players, remaining
  purses, capped/uncapped base rules, RTM if the 2027 rules allow it, lots run by sets, the registered list
  when published, manual availability and injury flags. *Next step: competition rules are now config
  (`config/competitions.toml`, `cricdex.competitions`, used by Keep or release); wire the auction simulator
  (purse, squad limits, overseas cap, retention cost; still hard-coded IPL constants in `auction.ts` ⇄
  `auction.py` and `AUCTION_TARGET` in `export_site.py`) to that file, and start its Mini mode from the real
  squads and the purses Keep or release computes. SA20 / ILT20 / MLC / WPL cycles are further entries.
  2026-10-23: the room's lots follow the real lists (lots per open place and overseas share from the
  2018–2024 shortlists, capped sets before uncapped, an accelerated round), its squad minimum is the rule's 18
  (was 20) and its bids step up the IPL ladder; purse, squad and overseas defaults are still the room's own.*
- [x] 13. Auction price model fitted to real IPL prices (M): Wikipedia personnel pages 2008–2026 (CC BY-SA;
  pre-2014 prices in US$); hurdle model — P(sold) logistic, log(price) hedonic on value, role, overseas,
  capped, age, base price, mega/mini; sale probability plus a price interval; out-of-time test.
  *Done 2026-10-21: `scripts/ipl_auction_history.py` → `data/curated/ipl_auction_history.json` (1,647
  sold lots, 1,046 retentions, 97–99% matched); `scripts/ipl_price_model.py` (as-of-auction IPL refits,
  P(bought) logistic + Huber ln(price / purse), mega retentions included) → `config/price_model.json`;
  out of time (2025 + 2026) MAE 0.68 ln against 0.78 for the old curve, rank corr. 0.74 against 0.63;
  `market_price` ⇄ `marketPrice` in the pool, Keep or release and Scout. *2026-10-21 (later): captaincy
  (`scripts/ipl_captains.py` → `data/curated/ipl_captains.json`, IPL + international, as-of-auction
  features) and an out-of-fold quantile calibration of the top end (10 cr+ lots 0.45× → 0.62×, within
  ±50% 45% → 49%, mean |ln error| 0.67 → 0.71, overseas over-priced ~1.9×). Next: an unsold list (none on
  Wikipedia), the overseas lean, the base-price choice model.*
- [ ] 14. Bowler-type × batting-hand matchup grid with shrinkage (S–M): right-arm pace, left-arm pace,
  off-break, leg-break, slow left-arm, left-arm wrist spin, vs LHB/RHB, by phase, with n-badges.
- [ ] 15. Opposition dossier PDF (M): opponent plus venue → probable XI, each batter's weak bowler types by
  phase, each bowler's danger batters, venue par.
- [ ] 16. Expected runs and wickets from ball-by-ball context (M–L): log-linear expectation over phase,
  wickets, venue, era, bowler type and balls faced, with shrinkage; a wicket priced in runs; a
  runs-currency value replacing the sd-sum. Don't call it "xR" (CricViz's xR uses ball-tracking). *Partly done 2026-10-19: a wicket priced in runs (value function over over × wickets down) and the runs-currency value replacing the sd-sum ship (review item 14); the context expectation is the rating model's season / phase / innings / venue terms. Still open: bowler type and balls faced in the expectation, and a chase-aware wicket cost.*
- [x] 17. Joint multi-league fit with league effects (M), publishing the translation factors (e.g. SMAT→IPL
  strike-rate factor with intervals). *Done 2026-10-23 (audit item 5): a translation per league and role, leagues
  pooled by group, fitted on players seen in both and tested out of time with level calibration (METHODOLOGY §6d;
  a tie with the old discounts on accuracy, no hand-set numbers). Open: a market-price recipe on the translated
  value that wins (Y didn't); a selection model for players who never get IPL games; a per-role prior in the
  blend.*
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
  *2026-10-23: need 1.5/0.7 and the personalities are gone: the simulator's teams bid by a demand model
  fitted on the 2019–2026 auctions (places short in his role, overseas places, purse per place, the upgrade
  he'd be; team effects lost out of time; METHODOLOGY §7). Bid plan's DEPTH 0.25 and NEED 0.63 are gone too
  (the bench fills the XI's missed matches by P(plays); needs reported, not scored). Still open: strength in
  wins rather than runs a match.*
- [x] 26b. Bid plan (M): an auction bidding-plan optimiser for one franchise: rivals simulated for the price to
  beat, targets by marginal squad strength per crore, max bids, fallback chains per role, every assumption
  editable. *Done 2026-10-21/22: page Bid plan + `cricdex bidplan`, web ⇄ Python parity; the auction
  simulator's bidding calibrated to the 2022–24 auctions and tested on 2025–26 (`scripts/auction_calibrate.py`,
  AUCTION_MATH Part 3b); no buying back own releases ("reconsider keeping" instead); the 2025 and 2026
  auctions replayed (`scripts/bidplan_backtest.py`: level with the real squads in 2025, worse in 2026).
  Next: the official 2027 auction list when published, Form forecast's three-season outlook for multi-year
  buys, rivals that react to our buys. (Team personalities learned from real bids: tried 2026-10-23 as
  team effects in the fitted demand model; they lost out of time.)*
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
  keep each only if held-out fit improves. *Within-player aging with a survivorship correction ships in the
  Form forecast (11b, METHODOLOGY §11); not yet inside the rating model.*
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

### Found while shipping (2026-10-17)

- [x] F1. Metrics are computed by scorecard name, so two different players who share a name in one league
  are merged (43 such names in men's T20Is, 8 in the BPL, 1 in The Hundred; none in the IPL). Key every
  metric, rating and board by the registry id (`players_<col>`) instead of the name. *Done 2026-10-17: `common/sql.py::keyed_balls` (per-match registry ids) everywhere; tests/test_namesakes.py. Re-counted on the current data, among players who batted or bowled: 38 names in men's T20Is, 7 in the BPL, 7 in SMAT, 3 in the PSL, 1 each in the IPL and The Hundred.*
- [ ] F2. Site data is now 217 MB (a profile for every player). Do roadmap item 39 soon: move the data
  snapshot out of `main` into a data branch the deploy reads, overwritten on each refresh.

### Open issues (owner, 2026-10-22)

All to fix. Order: data fixes and price model first, then Bid plan, then visuals and a rebuild.

- [x] I1. README auction / Scout images were rendered before the market price model — refresh every visual
  from current data (last, after the price fixes). *Done 2026-10-23:* every image and the hero video re-rendered
  from data (`scripts/media_data.py` → `docs/media/src/data.js`), plus new Keep or release and Bid plan (beta)
  images and a hero scene for them.
- [ ] I2. Bid plan (beta) doesn't beat real franchises in replay (re-run 2026-10-22 on expected contributions:
  8/10 in the 2025 mega, 0/10 in the 2026 mini; before, on per-100-ball strength, 4/10 and 2/10); target lists
  overlap across teams because the plan is a price-taker. Make rivals react to the plan's targets
  (equilibrium across teams) and re-validate; drop "beta" only when the replay beats the real franchises.
  *2026-10-23, still open:* rivals now bid by the fitted demand model and strength has no hand-set depth or
  need constants; the replay at equal spend is 6/10 (2025 mega, +2.5 runs a match) and 3/10 (2026 mini, −0.2):
  about level, not ahead in either type, so beta stays. P(≤ max bid) is no longer over-confident (top band
  0.92 → 0.89 came true in 2025, 0.91 → 1.00 in 2026; 0.35 / 0.35 on the lots a 2025 team bought itself).
  Left: rivals reacting to the plan, multi-season values, strength in wins (METHODOLOGY §12).
  *Re-run 2026-10-23 (evening) with the bench capped at a lot's P(plays) (I16):* 7/10 in the 2025 mega (+6.5)
  and 2/10 in the 2026 mini (−2.4, where the plan also spent far less than the real teams); P(≤ max bid) about
  right overall (0.38 / 0.39 in 2025, 0.48 / 0.52 in 2026) but high in the top band (0.89 / 0.76 in 2025,
  0.89 / 0.67 in the validation). Still beta.
- [ ] I3. Star prices still low out of time (lots ≥10 cr predicted at ~0.5× their price). *Re-examined
  2026-10-22, not ticked:* the ratio is regression to the mean, not a fixable level. Lots picked by their
  real price sit above any model; a model whose prices were exactly right on average would show 0.30×
  (0.22–0.41) on the same lots, and the new recipe shows 0.39× (the old map's 0.50× came from over-pricing
  the top: its 20 dearest predictions per auction fetched 0.65× their price; now 0.77×). Twenty-odd
  interactions, isotonic / quantile / per-group maps and an overseas × mega term were tried; none prices
  the 2025 stars higher without over-pricing everyone it ranks near them. Venkatesh Iyer, Chahal,
  Bhuvneshwar, the 2025 overseas pacers and the 2026 uncapped 14.2 cr buys stay beyond pre-auction facts
  (METHODOLOGY §6b reality table). Open question for the owner: accept "median + range" for stars, or add
  a non-data input (marquee sets, scouting). *Reworked 2026-10-22 (audit items 2–4):* mega retentions are
  now floors in a censored (Tobit) fit and the recipe is chosen on auctions up to 2024, then tested once:
  level on 2025–26 lots (0.654), retained stars priced at 0.60× their retention (0.54×); the Indian top
  end rises (Shreyas Iyer, Arshdeep, Pant, Gill, Bumrah) but the old stars (Kohli, Rohit) stay low, and
  the 27 cr / evidence ceiling now binds for 8 pool players. The prior market price helps P(bought) only.
  *Top end reworked the same evening (audit item 3):* the cause was the retained stars' floors pushing the
  linear index up (lots alone priced Gill at 22, with the floors 104), not a squared term; the price now
  goes through a monotone out-of-fold calibration with a fitted top slope (0.51), the value is held to its
  training support, the ceiling is gone, and nobody in the 2027 pool passes 27 (Gill 25.8). Chosen by the
  stated protocol (held-out lot error; the code had been using the log-likelihood), tested once: lot error
  level (0.661), top 20 0.87 (0.76). A literal purse bound (second-richest spendable purse, ~79 cr in
  2025) never binds; a fitted saturation put its cap at the purse itself. The Afghanistan caps source is
  done (METHODOLOGY §1). Still open: a brand / following input for the 35+ stars if a sourced one exists;
  the retained stars price at ~0.5× their retention (Keep now models the keeping instead).
- [x] I4. Overseas prices ~1.45× too high out of time (overseas price level swings between auctions).
  *Fixed 2026-10-22:* four calibration groups at their median (overseas split by mega / mini auction):
  out of time 1.10× (median +0.12 ln, was +0.50); leaving each auction out, overseas mega −0.05 and mini
  +0.03 in median (were +0.32 / −0.17). The level still swings: 2026 walking forward +0.23 in mean, −0.01
  in median. A 2025–27 rules-cycle overseas term was tried and rejected (worse 2026 median).
- [ ] I5. IPL 2027 purse and auction date are assumptions — confirm from official / press sources.
  *Checked 2026-10-22: no 2027 purse published anywhere (only the 157 cr salary cap); the auction is still
  "reported" for 16 Dec, ITC Grand Goa; retention lists due 15 Nov. Both stay `assumed` with dated sources in
  `config/competitions.toml`. Re-check when the retention lists and remaining purses come out (15 Nov).*
  *Rules re-checked 2026-10-22: 2027 is the last mini auction of the 2025–27 cycle (keep anyone at his
  contract, no RTM); the overseas fee cap limits the fee, not the bid; the 2025 retention slabs are assumed
  to carry into 2027 (owner's call), charged as in 2026 (rule reproduces all 20 published 2025–26 purses).*
- [x] I6. 22 squad players have no ball-by-ball data (unrated); CSK, DC, KKR, RR purses don't reconcile from
  Wikipedia salaries — reconcile against official remaining-purse figures and give unrated players a
  sourced prior. *Done 2026-10-22: all ten purses reconcile exactly (2025 retention-slab charge, DNA India;
  Vipraj Nigam 0.5 not 0.3), pre- and post-auction; 3 of the 22 matched by ESPNcricinfo key (Mukul
  Choudhary, Tejasvi Singh, Sahil Parakh), the other 19 priced from the market model as "no match data"
  (METHODOLOGY §10).*
- [x] I7. SMAT data ends Dec 2024 (prospects judged on stale form) — check for newer open data; otherwise make
  staleness explicit in every SMAT-based number. *Done 2026-10-22: Cricsheet lists SMAT 2024-25 groups and
  2025-26 as missing, no other open source; pool / Keep rows carry `stale_share` + `stale_note`, shown on
  Auction, Bid plan, `cricdex auction` and the Keep reason (METHODOLOGY §9). Re-check Cricsheet each refresh.*
- [x] I8. Captaincy gaps: Rising Pune Supergiant, Gujarat Lions, Ireland. *Done 2026-10-22: season articles
  for RPS / GL, "List of Ireland cricket captains" for Ireland (IDENTITY.md).*
- [x] I9. Afghanistan internationals missing (Rashid Khan, Noor Ahmad, Gurbaz and the rest counted as
  uncapped). *Done 2026-10-22:* Cricsheet withholds every match featuring Afghanistan since Nov 2024 (a
  protest, its own article); caps restored from Cricsheet's archive as kept by the Wayback Machine (to Feb
  2023) and the revision history of Wikipedia's Afghanistan cap lists, checked against the archive where
  both exist (`scout/identity/withheld.py`, METHODOLOGY §1). Every other nation present. Afghanistan's
  T20I ball-by-ball can't be rebuilt (no Afghan T20I ratings; T20Is feed no price or pool value).
- [x] I10. Keep or release's call is hand-set (0.5 cr / 15% margins, the age-35 rule) and was never checked
  against real retentions (audit item 1). *Done 2026-10-22:* the call is the chance a franchise keeps a
  player like him, a logistic model of every real deadline 2018–2026 (price vs cost, 3-season forecast,
  captain / seasons there / home-grown, status), chosen on 2018–2024 and tested once on 2025–26: 78% of
  calls as the franchise made them (82% of stars) against 70% (64%) for the old rule (corrected that
  evening: the first run had priced the old rule with the afternoon's recipe, 71% / 70%)
  (`scripts/keep_backtest.py`, METHODOLOGY §10). Open: the mega-year calls under-keep (2025 allowed 6
  retentions, the training years 3–4); the model can't tell which stars a franchise lets go in a mini year
  (2026 stars' balanced accuracy 0.49); it inherits franchises' habits rather than optimising.
- [x] I11. The Auction room's 2025 replay charged retentions at their salaries (KKR 57 cr, not 69).
  *Done 2026-10-22:* charged by the 2025 slab rule (`retention_spend` ⇄ `retentionSpend`), including the
  real retentions too new to rate; reproduces all ten published 2025 purses.
- [x] I13. Bid plan's replay table and the auction calibration ran on the morning's price recipe; Bid plan's
  replays (`scripts/bidplan_backtest.py`) are due a re-run on the new recipe (the calibration was re-run).
  *Done 2026-10-22, late evening:* re-run on the shipped recipe T and the playing-time strength (METHODOLOGY
  §12). The 2027 examples were recomputed too.
- [x] I14. The IPL-relevance penalty and the all-rounder rule (better role × 1.15; per-100-ball strength) were
  hand-set (audit items 4, 6). *Done 2026-10-22, late evening:* expected season value = P(plays) × contribution
  per match, fitted on IPL XIs and tested out of time (METHODOLOGY §6c). Open: a mega/mini term for free
  agents' P(plays); contributions from an aged forecast instead of the career rating (items 3, 9); a newcomer's
  balls a match run high (XIs sum to 1.1–1.2× a side's balls; Bid plan caps them); fielding.
- [x] I15. Tier discounts were one hand-set number per league (both roles), eight borrowed, translation sds guessed,
  the level never tested, and a 300-ball switch (audit item 5). *Done 2026-10-23:* fitted translations and a
  precision blend (METHODOLOGY §6d). Open: the market price still takes the old blend (recipe Y lost); overseas
  league stars new to the IPL came out too high in the 2023–25 intake.
- [x] I12. Style twins still give odd matches (item 25) — rebuild the similarity features and check 20 famous
  players by eye. *Done 2026-10-22: see item 25; 20 players read by eye, `tests/test_style_twins.py`.*
- [x] I16. Bid plan's 2027 sheets weren't presentable: retired players in the pool (Warner at 16–19 cr max bids,
  Bravo, Dinesh Karthik, Amit Mishra, Shikhar Dhawan, Rayudu) and Sarthak Ranjan (rated −9.1) first for CSK, DC
  and RCB. *Done 2026-10-23:* three causes fixed, none in the ranking's sign. (1) The bench filled the XI's
  missed matches with whole appearances whatever the player's P(plays), so a free agent who plays 4% of the time
  counted at his full career contribution: a lot now gives the bench at most his P(plays) of an appearance
  (`bench_fill`, Python ⇄ TS, parity-locked). (2) A player with no batting position in the window was measured
  against the tail's replacement level (−61.6) at a batter's balls: Sarthak Ranjan +8.2 runs a match; he now
  takes his role's typical position (+1.2, `playing_time.expected_usage`). (3) The pool had no sourced
  retirements and took franchises from the player master: `data/curated/ipl_availability.json` (15 retirements
  with dated sources, 2 auction opt-outs recorded), contracts from the competition's squads (Rahane, retired in
  July, was still a KKR player), and the 3-year activity rule justified from the data (`scripts/inactivity_gap.py`:
  after 3 years away 1.9% of players, 4.4% of former IPL players, played an IPL match again). METHODOLOGY §6c,
  §7, §12; all ten sheets re-checked by hand.
- [ ] I17. Left from the I16 review (2026-10-23): (a) lower-order hitters rate far below the average ball
  (Ramandeep Singh −37 per 100 balls) yet beat the tail replacement level of positions 8–11, so a No. 8 batter
  is a cheap target on every sheet; a No. 8 may need its own replacement group (ratings and playing time
  together). (b) Where λ hits its floor (KKR, LSG, MI) the max bids run far above what rivals pay: unspent
  purse is worth nothing to the rule. (c) The README's room is a mega auction on the 2025 retention lists, so
  players bought in 2025 (Suryavanshi, Noor Ahmad) are lots there; the 2027 mini room is in METHODOLOGY §12.
  (d) Bangladesh players' 2027 eligibility is unreported (the BCCI had KKR release Mustafizur Rahman in Jan
  2026). (e) Some dates of birth look wrong (Mukesh Choudhary 40, Venkatesh Iyer 36).

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

- ~~Fielder and non-striker credit in NGI~~ and ~~venue, phase and era effects in the ratings~~: shipped
  2026-10-17 (review items 9 and 12). Next on that line: a player's own form drifting over time
  (Tier D #34) and a joint multi-league fit (Tier B #17).
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
- Multi-agent self-play (every franchise its own learned bidding policy) instead of today's one fitted demand
  model.
- Bid-by-bid (paddle) data, if it ever becomes available: who bid against whom, not only who won and at what
  price, would identify team-specific demand (the 2026-10-23 team effects, fitted on winners and prices,
  lost out of time).

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
