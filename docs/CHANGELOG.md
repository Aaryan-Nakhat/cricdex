# Changelog

All notable changes to CricDex. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic
versioning starts at v0.1.0.

---

## [Unreleased]

### Engineering: one pipeline, a safe export, loud failures (2026-10-27)

- **One written-down pipeline.** `src/cricdex/pipeline.py` lists every rebuild step in order
  (ingest, People Register, player master, ratings, metrics, the model fits, form forecast, export)
  with its commands, inputs and outputs; `python -m cricdex.pipeline --list / --from / --only /
  --refit / --fresh`, resumable through marker files ([PIPELINE.md](PIPELINE.md)).
  `scripts/rebuild_all.sh`, `make refresh-all` and the refresh workflow now run it, so the player
  master and the form forecast are part of every rebuild. The model fits (translation, drift,
  shrink, playing time, price, Keep) follow the frozen validation protocol and run only on request.
- **The export is atomic and lighter.** Each league is cooked into `site/public/data/.staging/` and
  swapped in only when it fully succeeded (the rename is retried a few times when Windows holds a
  file, then fails with the path); `collections.json` and `leagues.json` are written last, through a
  temporary file. One DuckDB connection for the whole export (the profiles used to open a second
  one with a second copy of the league's ball-by-ball), temp tables dropped after each league and
  after the auction pool, the style-twin cache cleared, and Python's memory freed between leagues.
  Same output for the same input.
- **No more silent failures.** The export no longer skips a records board, a venue, the phase
  boards, a profile or a cohort with a warning: it stops with the player or league named. A failed
  time-window metrics run stops the export instead of leaving stale boards. Across `src/` and
  `scripts/`, the remaining `except Exception` blocks were narrowed to the error they expect
  (a provider error, a malformed match file, a missing export, an unmounted widget) and log what
  was skipped; the ones left catch everything only to show the error on screen (TUI, dashboard).
- **Deploy waits for CI.** The Pages deploy runs after a green CI run of a push to main, on that
  commit (`workflow_run`), or by hand. The refresh workflow runs CI on its data commit before
  calling the deploy.
- **Tools and dependencies.** The pre-commit ruff hook matches the locked ruff (0.15.12).
  Patched versions of starlette, python-multipart, urllib3, pillow, cryptography, idna, certifi,
  anyio, h2 and others (`uv audit`; pillow 13 came with streamlit 1.66), and react-router 6.30.6
  for the site. Left: filelock (the fix is 4.x, held back by its dependents) and two react-router
  advisories fixed only in 7.x.

### Security hardening (2026-10-27)

- **GitHub Actions.** Every third-party action is pinned to a commit SHA with its version in a
  comment. Workflow tokens are read-only by default: only the refresh job can write, and only the
  Pages deploy job gets the Pages and OIDC permissions. Checkouts keep no credential; the refresh
  passes its token to the one `git push`. The refresh's `collections` input reaches the shell
  through an environment variable and must be league keys from `config/leagues.toml`. Its Python
  install is locked (`uv sync --locked`, `UV_LOCKED=1`).
- **LLM answers are checked.** A new module, `cricdex.scout.identity.taxonomy`, holds every field
  of the LLM taxonomy and the name check to a fixed list (role, bowling category and style, batting
  slot, hand, confidence, country code) or a bounded plain name. It runs when an answer is saved
  (`scripts/enrich_taxonomy.py`, the name check) and when the cached files are read (player master,
  profiles, fielding, export fallback). Bad values are dropped with a warning. The sporting codes
  MAW and MGL and the code GB-SCT now map to Malawi, Mongolia and Scotland. Tests:
  `tests/test_taxonomy_schema.py`.
- **Content-Security-Policy on the site.** A `<meta>` policy in `site/index.html` allows scripts,
  styles, fonts and data only from the site, images also from Wikimedia, and the inline theme
  script by a hash that the build computes (`site/vite.config.ts`). Dev mode drops the tag.
- **Docker.** The image runs as the unprivileged user `app`. Compose publishes the API and the
  dashboard on `127.0.0.1`; set `CRICDEX_BIND=0.0.0.0` to expose them (docs/DOCKER.md).
- **SECURITY.md** says how to report a problem and what is hardened.

### Keep or release: "Should they?", honest test wording, link previews (2026-10-27)

- **Should they? (a cost-aware read beside the call).** The Keep call is what franchises will likely
  do, and in a mini year the fitted model hardly weighs the cost: its ln(price / cost) and ln(cost)
  terms (+0.141, +0.139) nearly cancel, so Kartik Sharma reads 93% Keep at a 14.2 cr cost against a
  1.67 cr market price. The model is not refitted (frozen protocol). A new column asks the other
  question from the market price alone: **Yes** when the median market price is at least what keeping
  him costs, **No** when even the upper quartile is below it, **Close** in between. It never changes
  the call, the default plan or the purse. `should_of` ⇄ `shouldOf` (parity-tested), on the Keep page
  (sortable), in the CLI table and in the CSV (`should_keep`). METHODOLOGY §10 step 5b.
- **No more "tested once" on 2025–26.** Each model was chosen on data up to 2024, but the 2025 and
  2026 seasons have since been looked at up to five times (several price recipes, the Bid plan
  replays). README, the About, Keep and Bid plan pages, AUCTION_MATH and METHODOLOGY now say so and
  call those figures optimistic. Stale numbers fixed: the price's 20 dearest predictions fetch 0.83×
  them with the shipped recipe Z (0.87× was T's); the Bid plan replays now give 1 of 10 and 0 of 10
  teams ahead (the pages still said 7 of 10 and 2 of 10).
- **Link previews and byline.** Open Graph and Twitter card tags in `site/index.html` with a
  1200 × 630 preview image (`docs/media/src/og.html` → `site/public/og.png`, `scripts/render_images.py
  og`). "by Aaryan Nakhat" on the home page and in the sidebar.
- **Home page leads with the 15 Nov 2026 retention calls** (to the Keep page), instead of the old
  mega-auction hero; the rest of the home page is unchanged.

### Role tags and ages from current data, not career data (2026-10-27)

- **Keeper, opener, death bowler and spinner tags now use the last 3 years.** Before this, the
  stumping counts, death-over shares and spin bowling were read over the whole career, and the
  batting slot came from the LLM taxonomy alone. As a result, Duckett and Glenn Phillips were tagged
  keepers, and Padikkal and Ishan Kishan were tagged openers. Kohli, Samson, Marsh, Markram and
  Prabhsimran Singh had no opener tag, and Shivam Mavi and Rahul Tewatia kept their death and spin
  tags. Now:
  - A keeper needs 2 stumpings in that window. A claim from Wikipedia or the LLM stands unless his
    last 3 years hold 40 or more T20 matches without a stumping.
  - An opener walked out at 1 or 2 in at least half of his last 30 T20 innings, counted over every
    league together or in any one league where he has 8 or more innings. The tag follows the
    batting evidence, so Narine counts.
  - A spinner must still bowl.
  - Details are in docs/IDENTITY.md and METHODOLOGY §8.
- **Occasional keepers are not keepers.** A Wikipedia infobox role of "Occasionally Wicket Keeper"
  no longer counts as a keeper; Ruturaj Gaikwad's had given CSK five keepers.
- **Ages for IPL debutants.** A squad player whose Wikidata item lacks his ESPNcricinfo id is now
  linked to a Wikipedia article in one of two ways:
  - a search for the cricketer article that links his ESPNcricinfo profile, cached in
    `data/curated/wikipedia_by_cricinfo.json`;
  - the article the IPL personnel page links.

  Players with no article at all get a sourced `dob` in `player_overrides.json`, or on their row
  of the squads file when they have no match data. A date whose year contradicts the article title
  is skipped, and a first match at 38 or older is listed for review.
- **Country from the article title.** An article titled "(Trinidad and Tobago cricketer)" now sets
  the country before the LLM taxonomy does.
- **Build stamp and fact checks.** Each league's `meta.json` now records the player-master build it
  was exported with (`player_master: {built, hash}`). A new test file,
  `tests/test_identity_facts.py`, checks:
  - every league comes from one build, with the same dob, country and retired status for a player;
  - every rated Keep player has an age;
  - Narine, Kohli, Samson and Markram are openers;
  - Gaikwad and Duckett are not keepers.

### CI green again, docs audited (2026-10-27)

- **The scout export used the connection it was given.** The time-aware and calibration steps opened the
  hard-coded database path, so CI, which has no database, failed. They now read the given connection's file,
  and leave values unchanged when there is none.
- **The IPL auction record and the sourced availability file are now committed** (`data/curated/`), so the
  retention-slab and availability tests run in CI. They skip cleanly when the files are absent.
- **Docs audit:** Bid plan is marked draft everywhere, with the replay numbers updated. Stale formulas and
  limits are corrected, and missing scripts and modules are added to the READMEs. There are 0 broken links.

### How far a value is trusted: a fitted calibration (ROADMAP I18; 2026-10-27)

- **The contribution per match read each value's posterior mean as if it were certain** (its sd went only to
  a display), and nothing checked that a mean resting on a thin, old or other-league record predicts the IPL.
  Each role's value is now calibrated before anything reads it: `value used = mu + k (value − mu)`
  (METHODOLOGY §4c; `scout/ratings/shrink.py`, `scripts/value_shrink_fit.py`, `config/value_shrink.json`).
- **Frozen protocol**, four candidates (none; one factor per role; a factor set by the value's own sd; that
  plus the non-IPL share and years since his last season), walk-forward 2019–24 on next season's
  contribution per match. **One factor per role** won (MAE 3.935 against 4.010); test once on 2025–26: 4.311
  against 4.385, rank 0.310 against 0.296, bias +0.26 against +0.66. Shipped: batting mu −10.7, k 0.76;
  bowling −7.9, 0.81. The evidence-dependent candidates were worse: thin records are not singled out.
- Bowling aging rechecked on the same validation: older bowlers who play are under-predicted, so a flat
  bowling curve stands.
- Refitted on it: replacement curves, P(plays) (0.5585 / 0.0855 / 0.5754 in the test), as-of contributions,
  the export. The market price's input is not calibrated.
- **Reality**: every contribution falls about a quarter (Gill 6.8 → 5.2, Kohli 4.1 → 3.1, Jani 4.6 → 3.5); ranks
  barely move (Kohli 27 → 28, Rohit 145 → 145). Gate: the same five pass, Cummins and the star price fail.
  **Buy model still off**: Chirag Jani first on six sheets, Nabi on three.
- Replays (2025–26 seen five times): "auction" 2024 5 of 10, 2025 1 of 10, 2026 0 of 10; "none" 7, 6, 5 of 10.
  Tests: `tests/test_shrink.py`.

### Time-aware values: ratings that see age (ROADMAP Tier D #34, I18; 2026-10-27)

- **What the auction tools read is now a player's level next season**, not his career average (METHODOLOGY
  §4b; `scout/ratings/drift.py`, `scripts/rating_drift_fit.py`, `config/rating_drift.json`). Each role's value
  is moved by A(his age next season) − the balls-weighted mean of A over the seasons his rating rests on.
  The aging curve A is fitted per group in a state-space model of every player's season values in every pool
  league, within players, with a selection model (a season he could have played and didn't is evidence his
  level fell) as the survivorship correction; without it the curve was the survivors' (flat after 28).
- **Frozen protocol**: seven candidates declared (aging only; a random walk only; both, with one bowling
  curve, pace and spin apart, or partially pooled; both without the selection model), chosen walk-forward on
  2019–24 by next season's contribution per match. **Aging only** won (MAE 4.019 against 4.036 for the career
  rating); every random-walk candidate was worse than the career rating. Test once on 2025–26: 4.400 against
  4.408, rank corr. 0.309 against 0.301; the bias for players 34+ falls from +0.49 / +1.32 to +0.13 / +1.04 runs
  a match. Shipped curve: batting flat 24–32, −4 at 36, −9 at 40; bowling within ±3 at every age.
- **Every consumer refitted on it**: replacement curves, P(plays) (squad 0.558, free agent 0.0855, buy 0.575
  in the test, same choices), the as-of contributions, the market price (recipe Z, the legacy blend moved
  the same way, won the price protocol on 2018–24 lots: 0.790 against 0.793; test 0.659 against 0.661;
  `value_input: "time_aware"`), the pool, Keep and Bid plan through the export. Keep's retention model was not
  refitted.
- **Reality**: Miller 2.8 → 1.8 runs a match (pool 59th → 78th), Warner 6.9 → 4.5, du Plessis 4.7 → 0.8, Dhoni
  2.7 → 0.4, Rohit 2.1 → 0.6, Kohli 5.9 → 4.1 (9th → 27th); Jaiswal 24th → 14th, Abhishek 19th → 13th, Gill 4th
  → 2nd; Bumrah and Rashid unchanged.
- **Reality gate**: the two first-target checks now pass on the shipped sheets (strict xfail marks removed);
  first targets spread over five players (Miller is third to fifth on six). Still failing: Cummins (59th) and
  the star price (0.3597). **Buy model rechecked and left off**: Nabi (42) and Chirag Jani (37, never-IPL)
  would top four sheets each.
- **Bid plan replays** (2025–26 seen four times): "auction" 2024 5 of 10 (+0.2), 2025 1 of 10 (−4.1), 2026 0 of
  10 (−2.7); "none" 7 of 10 (+0.9), 8 of 10 (+4.2), 5 of 10 (+0.3). The rules' ranking doesn't change.
- `export_site.py` writes `time_shift_bat` / `time_shift_bowl` on pool rows; `season_obs` caches every pool
  league's season values in `data/metrics/.drift/` (recomputed from a league's last year when it gets new
  matches). Tests: `tests/test_drift.py` (the filter and the selection update against brute force).

### I18 worked: buy model and rival plans built, tested and switched off; Cummins and the price gap explained (2026-10-27)

- **Bid plan relabelled from beta to draft** on the site, in the README and in METHODOLOGY: max bids are not
  reliable until player ratings see age and recent form (ROADMAP I18, Tier D #34).

- **P(plays) of an auction buy** (METHODOLOGY §6c): the squad model's inputs plus price, fitted on the real buys
  of 2018–24 (`playing_time_fit.py buy`). Chosen on 2024 (B3), test 2025–26 log loss 0.574 against 0.749 for the
  free-agent P(plays) Bid plan uses. Parity-locked (`buy_p` / `lot_p` ⇄ `buyP` / `lotP`; keep.json `buy_model`;
  the pool carries `ipl_matches`, `last_share`, `age`, `captain_ipl_last`). **Off** (`BIDPLAN_BUY_MODEL`). It puts
  Warner, Nabi, du Plessis and never-IPL domestic batters first, and a value calibration on real buys
  (`playing_time_fit.py value`) chose no shrink. The ratings' missing decline is the root (Tier D #34).
- **Rival plans (I2)**: `rival_plan_bids` / `_apply_rival_plans` ⇄ `applyRivalPlans`, the export's
  `bidplan_rivals.json`, page and CLI loaders. **Off** (`BIDPLAN_RIVAL_PLANS`): with purse-bound max bids the plans
  bid each other to 10–15 cr, unconverged after three passes.
- **Replay fix**: `follow_plan` now replays the "auction" money rule with its money value (it used λ = 0) and the
  lots' P(plays). The corrected 2025–26 replays (seen three times): same-spend next season 3 of 10 and 0 of 10.
  `bidplan_backtest.py --buy` for the buy model (1 of 10 and 0 of 10).
- **Cummins** (57th): a real signal, documented with his 2024–26 bowling against the league and his 8 of 15
  matches in 2026. **Kartik Sharma, Prashant Veer**: bought on SMAT 2025–26, UP T20 League and trial form outside
  the data. The gate's xfail reasons now say so.

### Replacement curves, a value for unspent purse, and dates of birth (issue I17, 2026-10-26)

- **Replacement level as a curve** (METHODOLOGY §6c). The levels were one number per batting-slot group and per
  bowling group, so a lower-order hitter whose usual position is 7.5 (Ramandeep Singh, −37 runs per 100 balls)
  was measured against the 8–11 group's −61.6, set by bowlers batting at 9–11, and was first on 9 of 10 Bid plans.
  The level is now a curve in usual batting position (monotone, isotonic) and in balls bowled a match (a kernel
  mean), fitted on minimum-price buys. Candidates declared first, chosen on the 2018–24 auctions, tested once on
  2025–26: the curves predict a buy's rating no better than the groups did, but there is no longer a 38-run jump
  at one position (`playing_time.curve_at` / `fit_curve`, `scripts/playing_time_fit.py repl`). The same fix
  removes a jump at the 15-ball frontline line (Jadeja and Hardik bowl 14–15 balls and gained 1–1.5 runs a match
  from it). P(plays) refitted: squad test log loss 0.558 → 0.556, free agents 0.0856 → 0.0853. Ramandeep 1.9 →
  0.5 runs a match, pool rank 80 → 171, in no team's top five; the pool's top ten keeps nine of its ten (Pooran
  in, Suryakumar Yadav 11th).
- **What unspent purse is worth** (METHODOLOGY §12 step 4, AUCTION_MATH Part 4). Money left after an IPL auction
  buys nothing for the season (replacement fees are capped at the replaced player's and sit outside the cap), so a
  crore is worth what the later lots can still buy at their expected prices (the rivals' median), lots ranked by
  gain on the likely squad ÷ price, and a squad place what it would push out (`_MoneyValue` ⇄ `MoneyValue`,
  parity-locked; `plan(money=...)`, `bidplan_backtest.py --money`). Calibration target, the real spend shares:
  minis a median 0.76 of the purse (2024 0.90), megas 0.99, hardly depending on purse or open places. Chosen on 2024
  over the old single λ ("none", spend error 0.46) and the market rate of 2026-10-26 ("market", 0.72): error 0.11.
  Test 2025–26: spend error 0.01 / 0.11, but next-season squads at the same spend were weaker than the real ones for
  8 and 10 of 10 teams ("none": 3 and 5). A place-cost term was added after the test; the result held (seen twice).
  The 2027 sheets spend 0.87–0.99 of the purse; λ is 0 at the first lot (places run out first), so max bids are
  purse-bound. The replay inputs were rebuilt (`auction_demand_fit.py inputs` / `mk` on the new as-of
  contributions).
- **The reality gate** (METHODOLOGY §13, `tests/test_reality_gate.py`): seven checks of the real IPL outputs with
  thresholds from real data or cited records (spend vs real teams with similar purses, first-target concentration
  vs the fitted chance franchises bid, minimum-price players, 18 cr stars in the top N, IPL age records, Keep on the
  18 cr stars, star prices vs the documented error). It fails four today. They are marked as strict known
  failures, each pointing to ROADMAP I18.
- **Dates of birth** (docs/IDENTITY.md). The player master took Wikidata's date before the Wikipedia infobox, and
  read it without its precision, so a year-only date became 1 January. Where both exist they disagree for 7%
  of players, and the infobox matched the published profiles (iplt20.com and others) in every case checked
  (Mukesh Choudhary 1996, Wikidata 1986; Venkatesh Iyer 1994, Wikidata 1990). Now: overrides → infobox → Wikidata
  at day precision → legacy, and a date implausible at debut or last match falls through to the next source
  (`master._pick_dob`; `sources.refresh_wikidata_dob` re-read 4,814 cached Wikidata dates: 128 year-only).
  50 IPL players changed. After the fix, every IPL player over 38 with a match since 2025 is a known veteran,
  and the only debut under 15 is Vaibhav Suryavanshi (real). Disagreements are listed in the review
  (`dob_disagree`, 222).
- **Mustafizur Rahman, 2027**: no BCCI or IPL statement on Bangladesh players found; left in the pool and flagged
  as unknown (METHODOLOGY §12), not recorded in `ipl_availability.json`.
- IPL site data re-exported (`export_site.py --collection ipl --skip-prep`).

### Bid plan's 2027 sheets: who is in the auction, and a bench that respects P(plays) (issue I16, 2026-10-23)

- **Why the sheets were wrong.** Not the ranking's sign. (1) The bench filled the XI's missed matches with whole
  appearances at each player's full contribution, ignoring his P(plays): a free agent who plays 4% of the time
  (David Warner, 40) added 4–5 runs a match and drew max bids of 16–19 cr. An auction lot now gives the bench at
  most his P(plays) of an appearance (`bench_fill`, `web_parity/bidplan.py` ⇄ `site/src/lib/bidplan.ts`, a new
  parity case and unit tests). (2) A player with no batting position in the four seasons before was measured
  against the tail's replacement level (−61.6) at a batter's balls: Sarthak Ranjan (rated −9.1, nothing in the
  data since 2018) came out at +8.2 runs a match and first on CSK's, DC's and RCB's sheets. He now takes his
  role's typical position (`playing_time.expected_usage`; +1.2, P(plays) as a free agent 0.01). (3) The pool
  had no sourced retirements and took each player's franchise from the player master.
- **Who is in the 2027 pool** (METHODOLOGY §7): players not under contract in the competition's squads (the
  squads file with the 2026 auction, trades, retirements and releases; Ajinkya Rahane, retired in July, had
  stayed a KKR player), not in the new **`data/curated/ipl_availability.json`** (15 announced retirements, each
  with dated sources: Bravo, Dinesh Karthik, Shikhar Dhawan, Amit Mishra, Rayudu, Pollard, Saha, Chawla,
  Gowtham, Rishi Dhawan, Finch, Ashwin, Russell, Mohit Sharma, Rahane; Warner and du Plessis recorded as not
  registering for 2026 only, so they stay), and with a T20 match in a pool league in the last **3 years**, now
  justified from the data (`scripts/inactivity_gap.py`: after 3 years away 1.9% of players, 4.4% of former IPL
  players, played an IPL match again; after 2 years 3.6% / 9.5%). The player master reads its `retired` flags
  from the same file (the three retirements in `player_overrides.json` moved there). An official auction list
  still replaces the inferred pool.
- **All ten 2027 sheets re-checked** (METHODOLOGY §12 table): active players outside a 2027 contract or
  released by a plan, cheap IPL regulars and young free agents first. **Replay re-run**: at the real spend the
  plan's squad was stronger next season for 7 of 10 teams in the 2025 mega (+6.5 runs a match) and 2 of 10 in
  the 2026 mini (−2.4; it spent far less), from 6 and 3; P(≤ max bid) about right overall, high in the top band
  (0.89 said, 0.76 came true in 2025). Still beta.
- README `bidplan.png` shows a live 2027 sheet (RCB's top five targets, max bids, a fallback chain) from
  `scripts/media_data.py --bidplan-team`.

### README visuals refreshed from current data (issue I1, 2026-10-23)

- **Every visual is now filled from data, not typed in.** `scripts/media_data.py` computes the numbers from the
  exported site data with the same `cricdex.web_parity` code the CLI uses (the default 300-run mega auction, Keep
  or release for RCB, Scout for Jasprit Bumrah, ratings and head to heads, the NGI leaders, the backtest JSON) and
  writes `docs/media/src/data.js`; the `img-*.html` pages and `hero.html` read it. `render_images.py` and
  `render_video.py` stop on a page error instead of filming a half-filled page.
- **auction.png / hero**: the fitted bidding room (no personalities, no 27 cr cap tag): purse used, the dearest
  buys at the market model's prices, how a team bids by the demand model. **scout.png**: market prices, the
  fitted league translation instead of hand-set discounts, the SMAT staleness badge. **ratings.png**: top batters
  and bowlers limited to current IPL squads, retired players left out. **backtest.png**: the current figures
  (newcomer batters 0.12 vs 0.08, ahead in 70% of resamples; bowlers 0.25 vs 0.26). **architecture.png**: the
  league translation, playing time, market price and bidding, keep and forecast models; Wikipedia's IPL pages as a
  source. **ngi.png**: leaders from the leaderboard file (unchanged).
- **New**: `keep.png` (RCB: cost, market price, chance kept, the call; 78% / 82% on the test deadlines) and
  `bidplan.png` (BETA label; P(≤ max bid) said vs came true and the 6 / 10, 3 / 10 replay), placed in their README
  sections; the hero video gains a Keep or release + Bid plan scene (about 54 s now).

### Auction room: bidding fitted on real auctions; Bid plan without hand-set strength constants (2026-10-23)

- **A demand model replaces the personalities** (audit item 7; `scripts/auction_demand_fit.py` →
  `config/auction_demand.json`, `web_parity/auction.py` ⇄ `site/src/lib/auction.ts`, METHODOLOGY §7, AUCTION_MATH
  Part 3). For each lot, each team with room and purse decides whether to bid (logistic) and how high (ln bid =
  mu + the lot's heat + a Gumbel own view), from his market, base and last price, the money per open place
  across the market, the auction's stage, and its own places short in his role, open overseas places, purse per
  open place and the upgrade he'd be. Fitted by exact likelihood on every sold lot of 2019–2026 (who bought him,
  at what price), each team's squad, overseas count, purse and best player per role rebuilt lot by lot from the
  history's set order (inside a set the page's order; no unsold lots, so the fit conditions on a sale). Gone:
  the six archetypes and their per-team defaults, need 1.5 / 0.7, the budget pressure clamped to 0.75–1.6, the
  1.02 clearing step, MIN_SQUAD 20, the calibrated level / curve / anchor / shock / tightness
  (`auction_calibrate.py` now checks the fitted room instead of tuning it).
- **Frozen protocol, round 1**: nine candidates (market price only; + needs; + purse per place; + upgrade; + stage; + a
  mega level; + team effects; + needs in whether a team bids; + his own contribution, declared after the 2022–23
  validation replays and before the test), chosen by leave-one-auction-out log-likelihood on 2019–2024 (D7,
  −4.402 against −4.488 for market price only), tested once on 2025 / 2026 (−5.136 / −4.464 against −5.405 /
  −4.666; best of the nine), refitted on 2019–2026. Team effects lost out of time. Lots' market prices: from
  the other 2018–2024 auctions for 2019–2024 (the walk-forward recipes of 2019–2021 learned from three auctions),
  walk-forward for the test.
- **Round 2, after the owner's review** (Pant's typical simulated price 9.0 cr against a real 27 and a market
  price of 21.5): the causes tested on 2019–2024 only, with a reality criterion declared first (a second look at
  2025–26, disclosed). The likelihood already uses the order statistics and fits both spreads; a heavy-tailed heat
  collapsed to one component; a bid in proportion to the market price (R1), or without the base price in the
  level (R2), loses out of time. A calibrated room's own top 10 lie inside its 10–90% range 70% of the time at
  2.3× its median: the real top 10 of 2019–2024 managed 43% at 4.3×, a shortfall in the mini auctions (the
  market price missed their stars: 2–8× it) and none in the 2022 mega. Shipped: **R4, D7 + a slope of its own for
  the market price above 2 cr** (LOAO −4.399, best; test −5.137 / −4.453), 7 of the 2025 real top 10 inside their
  range (D7 6), calibration level.
- **Out of time, all ten teams bidding** (R4; against the room before on the same inputs): real price inside the
  simulated 10–90% 67% / 70% of 2025 / 2026 sold lots (64% / 56%), contested lots 69% / 85% (62% / 50%), the
  real buyer the most frequent simulated one 16% / 19% (9% / 16%), the 10 dearest simulated lots 1.06× / 0.81×
  their real price (1.15× / 0.78×); lot error 0.65 / 0.60 (0.62 / 0.64). The typical price of a star is still
  low (Pant 10.6, range 3.2–32.3, real 27; Shreyas Iyer 11.5, real 26.75; the room before: 20.6 / 14.7).
- **Lots and rules from the real lists**: lots per open place 4.6 (mini) / 3.0 (mega) and 35.7% overseas from
  the 2018–2024 shortlists; capped sets before uncapped, an accelerated round for the unsold; the IPL bid ladder
  (5 / 10 / 20 / 25 lakh; Business Today 2024-11-23, checked on the real prices); the purse rule and squad
  minimum 18. `auction_lots(pool, open_places, mode)`, `lot_sequence`, `ladder_next`.
- **Bid plan** (audit item 8; `web_parity/bidplan.py` ⇄ `bidplan.ts`, METHODOLOGY §12): DEPTH 0.25 on the next
  four and NEED 0.63 a place are gone. The bench now fills the XI's missed matches (Σ over the XI of 1 −
  P(plays), best contribution a match first, one appearance a match each), so the depth weight is the fitted
  P(plays); role needs are reported, not scored. Rivals bid by the fitted model; the price to beat is the next
  ladder step above the best rival's bid (was × 1.02).
- **Bid plan replayed** (`bidplan_backtest.py --inputs`, now also over 2019–2024 for the reliability of P(≤ max
  bid)): at the real team's spend, next-season output, ahead of the real squad for **6 of 10 teams in 2025 (+2.5
  runs a match) and 3 of 10 in 2026 (−0.2)** with the R4 rivals (D7 rivals: 6 and 4), from 8 and 0: about level,
  so **beta stays**. P(≤ max bid) is no longer over-confident: top band 0.92 → 0.89 came true (2025), 0.91 → 1.00
  (2026); 0.35 / 0.35 on the lots a 2025 team bought itself; it errs low in the validation (0.40 / 0.56); no
  recalibration map (decided after seeing the test tables; disclosed).
- **Surfaces**: the Auction page, TUI and Streamlit lose the personality pickers; `cricdex.auction.real_pool` is
  the franchise list only; the Auction and Bid plan pages, README, About, AUCTION_MATH, METHODOLOGY §7 / §12,
  STUDY_GUIDE and ROADMAP (I2, #12, #26) rewritten. `tests/test_auction_demand.py` locks the constants to the fit
  (Python and TS); the parity tests run the new simulator with every demand path on.

### League translation: fitted per league and role, no 300-ball switch (2026-10-23)

- **Fitted, not hand-set** (audit item 5; `scripts/league_translation_fit.py`, `src/cricdex/scout/translation.py`,
  `config/league_translation.json`, METHODOLOGY §6d). How a rating in another league carries over to the IPL is
  fitted per league and per role on every player seen in both: a player's observed IPL value in a season against
  his league rating as of that season (time-matched: played the league in the two years before), with a
  ball-count noise term, leagues pooled hierarchically within a registry `group` (NumPyro NUTS), then put on the
  IPL rating's scale. Translation sd from the fit (9–15 runs per 100 balls against the guessed 6.5 / 10.5). SMAT
  batters lose about 9 runs at +10, SMAT bowlers almost nothing (the old single −17 hit both); overseas bowling
  carries over almost whole. The eight "borrowed" leagues are fitted, pulled toward their group.
- **The 300-ball switch is gone.** A player's IPL rating and every translated league are blended by precision
  (the prior each posterior holds divided out); a long IPL record dominates by its small sd.
- **Frozen protocol**: five candidates (registry groups / one group / phase mix / IPW / prior divided out),
  rolling validation 2022–24, test once on 2025–26 against the old scheme and no translation, with level
  calibration. Result: **a tie on the log score** (fitted −4.960 / −5.022 batters / bowlers against −4.952 /
  −5.018 for the old scheme); newcomer bowlers' level fixed (bias +4.6 against +13.7 runs per 100 balls), but the
  top fifth of predicted batters fell short in 2025–26. Phase and IPW didn't help. A trial run printed one test
  table before validation (disclosed; nothing changed after it). Reality table of 25 players: mean error 11.7
  against 13.3 (internationals and SMAT better, overseas league stars new to the IPL worse).
- **Fed through**: the pool's `value`, both roles' values in the contribution per match, P(plays)'s inputs and
  the replacement levels (the playing-time model refitted under its protocol: squad test log loss 0.558, was
  0.562; free agents 0.0855, was 0.0848; bowling replacement −11.3 → −5.1 frontline, −27.4 → −13.0 part-time),
  Bid plan, Scout (`ipl_value` / `ipl_value_sd` per row; the gem flag and SMAT staleness labels unchanged), the
  on-field worth.
- **Not fed through: the market price.** Recipe Y (T on the translated value) lost the price model's protocol
  (LOAO MAE 0.800 against 0.792) and the Keep re-test (test F1 72.2% against 72.4%), so `price_value` keeps the
  old blend (`translation.legacy_blend`, now with its own `price_value_sd`) until a recipe on the translation wins.
  `config/price_model.json` and `config/keep_model.json` unchanged; the auction calibration not re-run (recipe
  unchanged).
- **Contracted players always stay in the auction pool**: the 600 cap applies to free agents only (with bowlers'
  contributions lower, a below-replacement squad bowler would otherwise have fallen out of the room's squads).
- `config/leagues.toml` tiers carry a pooling `group`; `discount`, `calibrated` and `translation_sd` are rejected.
  `pricing.TIER_PENALTY`, `leagues.discount()` / `translation_sd()` / `tier_discounts()` and the TS `tierDiscount` /
  `estValue` are gone; `est_value` / `scout_price` / `scoutPrice` take no tier (values arrive translated).
  `leagues.json` carries each league's fitted `translation`. Parity cases for Scout prices and the price input's
  sd added. `scripts/backtest_newcomers.py` pools through the translation.

### Playing time: P(plays) × contribution per match replaces the relevance penalty and the all-rounder rule (2026-10-22, late evening)

- **One valuation** (audit items 4 and 6; `src/cricdex/scout/playing_time.py`, `scripts/playing_time_fit.py`,
  `config/playing_time_model.json`, METHODOLOGY §6c): expected season value = P(plays a match) × contribution
  per match × 14, contribution = (batting value − replacement for his slot) × balls faced a match / 100 +
  (bowling value − replacement for his group) × balls bowled a match / 100. Fitted on real IPL XIs
  (Cricsheet `match_players`), every piece under the frozen protocol (chosen on 2024, fitted to 2023, tested
  once on 2025–26):
  - **expected balls**, a credibility estimate (his IPL history, other leagues discounted, his role's
    impact-era mean): test MAE 2.71 balls faced / 1.44 bowled a match against 3.12 / 1.55 for last
    season's share and 3.71 / 2.14 for the role mean;
  - **replacement levels**: the mean rating of minimum-price buys, by batting slot and bowling group (top
    −7.3, middle −16.8, lower −23.2, tail −63.2; frontline −11.3, part-time −27.4);
  - **P(plays) in a squad** (rank in the squad / projected XI, overseas places, experience, age, last season's
    share, keeper, captain, era): log loss 0.562 against 0.697 (base rate) and 0.626 (rank only), Brier 0.087;
  - **P(plays) of a free agent** (every past auction pool; includes whether he's bought): 0.085 against 0.157.
- **The IPL-relevance penalty is gone** (up to 36 runs per 100 balls on a hand-set curve). The pool is ranked
  by expected season value; the 150-ball cut is gone (the ratings' shrinkage and P(plays) handle thin
  records); recency and the 600 size limit stay, with their reasons in the code and METHODOLOGY §7. The room's
  mini retentions keep each team's top 18 by expected season value. `activity_index.json` carries `p_play`
  instead of `ipl_relevance` (Auction page, CLI, TUI and dashboard show "Plays %").
- **All-rounders count both disciplines.** `ROLE_MULT` (×1.15 / ×1.05) deleted from `pricing.py` ⇄
  `auction.ts`. Jadeja 74th → 8th, Hardik 127th → 30th, Green 57th → 15th; Narine's batting counts again.
- **Bid plan strength** = the best XI's Σ P(plays) × contribution per match, the XI's balls held to 115 an
  innings (`TEAM_BALLS`), replacement 0, NEED 0.63 and λ 0.05–3.2 (unit conversions of the hand-set 3 and
  0.25–16); a lot counts at the free-agent P(plays) (`p_play_free` for a squad player released). Without P the
  plans put 41–43-year-old veterans at the top of every list. `bidplan.py` ⇄ `bidplan.ts`.
- **Keep or release**: role gaps compare contribution per match (`level` in `keep.py` ⇄ `keep.ts`);
  `keep_features` takes P(plays) and contribution. `scripts/keep_backtest.py` declared L5 / L6 (playing
  time as inputs): better log loss (0.543–0.546 against 0.548–0.554) and stars, not better F1 (0.786 / 0.794
  against 0.795), so L4 stays (coefficients unchanged). The old rule's comparison corrected: 70% / 64%, not
  71% / 70% (it had been priced with the afternoon's recipe).
- **Market price**: candidate X (the contribution as `pv`) declared in `scripts/ipl_price_model.py` and not
  chosen (held-out lot error 0.794 against T's 0.792, top 20 0.92 against 0.98); T and its test unchanged.
- **Bid plan replays re-run** (roadmap I13, on recipe T and the new strength): same spend, next season, the
  plan's squad was stronger than the real one for 8 of 10 teams in the 2025 mega auction and none in the 2026
  mini (not comparable with the earlier 4 / 2: the measure changed). Rival prices: real inside the 20–80% range
  for 49% / 53% of lots. The METHODOLOGY §12 examples are recomputed.
- Checks: `tests/test_playing_time.py`; parity cases for expected contributions and the XI's ball budget,
  mini retentions by season value, keep features with playing time; `auction_check` on a scratch export (all
  ten purses as published, squads 20–25).

### Afghanistan caps, the top end without a ceiling, Keep or release on what franchises do (2026-10-22, evening)

- **Afghanistan internationals restored.** Cricsheet withholds every match featuring Afghanistan since 14
  Nov 2024 (its own article), so Rashid Khan had 1 international cap and Noor Ahmad, Gurbaz, Omarzai and
  28 more none. `scout/identity/withheld.py` restores their caps from Cricsheet's archive as kept by the
  Wayback Machine (XIs to Feb 2023) and the revision history of Wikipedia's Afghanistan T20I / ODI / Test
  cap lists (dated at the revision that published each appearance: can lag, never lead), checked against
  the archive where both exist (within ~1 appearance per player). `data/curated/international_caps.json`
  and the player master rebuilt offline (31 Afghan players now capped). Every other nation checked present.
  Rashid Khan's market price 5.4 → 8.9 cr. No rating changes (T20Is aren't an auction-pool league).
- **The market price's top end.** The 90 cr Gill came from the retained stars' floors pushing the linear
  index up (lots alone: 22 cr), not from a squared term (that ran away for Suryavanshi only). The price now
  passes a monotone out-of-fold calibration whose top rises at the slope real prices showed (0.51), the
  value is held to its training support, the quadratic term is dropped, and **the 27 cr / IPL-balls
  ceiling is removed** from the market price, the Auction room and Bid plan (the room keeps the purse rule).
  Twenty declared candidates (a saturating budget limit and top-end hinges among them), chosen by the
  stated rule (held-out lot error up to 2024; the code had been choosing by a log-likelihood that rewards
  over-pricing kept stars) and tested once: lot error 0.661 (level), each auction's 20 dearest predictions
  fetched 0.87× them (0.76× before). 2027 pool: Gill 25.8, nobody past 27. `pricing.py` ⇄ `auction.ts`
  (`calibrate` with `hi_slope`, `link_share`, `pv_max`); the upper quartile goes through the calibration.
- **Keep or release: the call is what franchises do.** The 0.5 cr / 15% margins and the age-35 rule are
  gone. `keep_probability` (a logistic model of every real retention deadline 2018–2026: price vs cost,
  3-season forecast, captain / seasons there / home-grown, capped Indian, overseas, age, IPL balls) gives the
  chance a franchise keeps a player like him; Keep ≥ 65%, Release < 35%, kept by default from 50%.
  `scripts/keep_backtest.py` rebuilds every squad before every deadline with only what was known then;
  chosen on 2018–2024, tested once on 2025–26: 78% of calls match the franchise (82% of stars) against 71%
  (70%) for the old rule. Kohli, Suryakumar, Jadeja, Samson, Rashid, Cummins, Klaasen are Keeps; Rohit,
  Dhoni and Tejasvi Singh Borderline and kept by default. `config/keep_model.json` (shipped in the package
  and in `keep.json`), `keep.py` ⇄ `keep.ts`, CSV `p_keep`, a "Kept by franchises" column (the page's and
  `cricdex keep`'s default sort), export `seasons_here` / `home_grown`.
- **Auction room: retentions cost the slab rule.** The 2025 replay charged salaries (KKR 57 cr); it now
  charges the 2025 rule (KKR 69), including real retentions too new to rate, and reproduces all ten
  published 2025 purses (`retention_spend` ⇄ `retentionSpend`; `slabs.ts` shared with Keep).
- **Calibration re-run** on the new price recipe and the room without a cap (`scripts/auction_calibrate.py`,
  now resumable).
- Tests: `tests/test_withheld.py`, `tests/test_price_model.py` (the calibrated top, no ceiling), parity
  cases for the calibration tail, the link, the retention charge (KKR 69) and the retention model.

### Retentions as floors, the recipe chosen before the test, 2025 slabs in Keep or release (2026-10-22)

- **Rules checked and cited** (`config/competitions.toml`, METHODOLOGY §10): the 2025–27 overseas fee cap
  limits the player's fee (18 cr), not the bid, and the purse pays the whole bid (ESPNcricinfo 29 Sep 2024;
  Business Today 16 Dec 2025 on Green); retention slabs 18 / 14 / 11 / 18 / 14, uncapped 4, charged as the
  higher of the slab total and the salaries (ESPNcricinfo 28 Sep 2024; RR's 2025 purse table). The rule
  reproduces every team's published 2025 purse and, applied to the 2025 retentions still on each squad,
  every 2026 purse (`tests/test_competitions.py`, replacing the hand-entered per-team charge as the check).
- **Keep or release: what keeping a player costs.** `retained_cost = "slabs"` for IPL 2027 (assumed: the
  2025 slabs carry on until the BCCI publishes 2027 rules). A 2025 mega-auction retention still with his
  franchise (`mega_retentions_2025` in the squads file) is charged by the slabs; his cost is what releasing
  him alone frees (Kohli 15 cr, not 21; Jurel and Parag 18, not 14). The call compares the market price
  with that cost; purse left = purse − what the kept players cost. `keep.py` ⇄ `keep.ts`
  (`slab_charge`, `purse_charged`, `retention_costs`), CSV `cost_cr`, the page, `cricdex keep` (cost column,
  `--sort cost`) and Bid plan's purse; parity cases with slabs.
- **Market price: retentions are floors.** The price is a censored (Tobit) regression: lots are prices,
  mega-auction retentions only "at least this" (`TobitRidge`). Mini-year retentions as floors were tried and
  made everything worse.
- **The recipe is chosen before the test.** Eleven declared candidates, chosen on auctions up to 2024
  (leaving one auction out, held-out log-likelihood of lots and retentions together), then scored once on
  2025–26. Shipped: Tobit, mega retentions as floors, with captaincy. Out of time it is level with the
  previous recipe on lots (mean |ln error| 0.654 both) and better on the retained stars (2022 / 2025
  retentions priced at 0.60× their retention price, 0.54× before). Older auctions are now scored against
  their own 0.2 cr floor.
- **The prior market price** (the last auction price or retention as a share of the purse, seasons since,
  retained or not) was added as the owner asked and tested: it improves P(bought) (log loss 0.585 → 0.564
  leaving one auction out) and ships there; it does not improve the price (released players with high
  last prices mostly fetch much less), so the price doesn't use it.
- **Data:** two wrong matches in the auction history fixed (2026 "Mangesh Yadav" had Mayank Yadav's id,
  2022 "Ramesh Kumar" R Vinay Kumar's; the initial + surname rule now rejects a contradicting first name).
  Found, not fixed: the database has no Afghanistan internationals, so Rashid Khan and the other Afghan
  players are priced as near-uncapped.
- **Effect on 2027 defaults:** 32 of 272 calls change. Kohli, Suryakumar Yadav, Rinku Singh, Rashid Khan and
  Cummins go from Release to Borderline; Bumrah, Hardik Pandya, Gaikwad, Axar Patel, Pant, KL Rahul and
  Abhishek Sharma to Keep; Rohit Sharma and Dhoni stay Releases (the market has never paid much for an
  Indian star of 35+ at auction; brand isn't in the model). The IPL-evidence ceiling / 27 cr record now
  binds for 8 pool players (1 before). Auction room bid levels re-fitted (AUCTION_MATH Part 3b): on the
  new price the room is calibrated a little worse than on the old one (2025 test: 65% of real prices inside
  the 10–90% range, was 77%), better on 2026 lot error (0.66, was 0.77).

### Market price: each kind of player at its median (I3 re-examined, I4 fixed) (2026-10-22)

- **New calibration.** `scripts/ipl_price_model.py` drops the quantile map for four groups at their
  median out-of-fold residual: overseas in a mega auction (−0.28 ln), overseas in a mini (+0.27), capped
  Indian (−0.09), uncapped Indian (−0.14) (`none+group-median-offset`, `config/price_model.json`). No
  new feature: the browser reads the groups through the existing `calibrationPart`; a parity case for an
  overseas player in a mega auction and `tests/test_price_model.py` added.
- **Out of time** (train ≤2024, test 2025 + 2026, 238 lots): mean |ln error| 0.712 → 0.655, median error
  53% → 51%, within ±50% 49% → 50%, bias +0.13 → −0.10 (median +0.23 → 0.00). Overseas 1.45× → 1.10×.
  Leave one auction out 0.802 → 0.770; walk forward to 2026 0.825 → 0.779.
- **Stars (I3), honestly.** The lots that sold for 10 cr+ now come out at 0.39× (was 0.50×), but a
  perfectly calibrated model would show about 0.30× there (regression to the mean); judged on the 20
  dearest *predictions* per auction the top went from over-priced (0.65×) to 0.77×. Reality table of 30
  well-known 2025–26 lots in METHODOLOGY §6b: 10 of 22 dear lots in the middle half (15 before), 3 of 8
  cheap ones (2). I3 stays open.
- **Tried and reported, not shipped:** overseas × mega and 2025–27 rules-cycle overseas terms, isotonic
  / quantile / per-group maps before the medians, recency weights, ~20 interactions, per-group lines.
- **Data:** the auction history re-matched against the rebuilt player master (Mukul Choudhary, Tejasvi
  Singh, Sahil Parekh in 2026; Mukesh Choudhary in 2022): 1,602 of 1,647 lots matched.
- **Keep or release** (2027 defaults): 49 of 272 calls change; Kohli, Rohit Sharma and Suryakumar Yadav
  go from Borderline to Release on price alone (brand and loyalty aren't in the model), Salt to Keep.
  `scripts/bidplan_backtest.py` now re-fits the new recipe; the Auction room's bid levels and the Bid plan
  replay were fitted with the old one and are due a re-run with I2.

### Data fixes I5-I8: 2027 dates, purse reconciliation, no-data players, stale SMAT, captaincy (2026-10-22)

- **I5, IPL 2027 purse and auction date.** Re-checked the press and iplt20 news on 22 Oct: no 2027 purse
  has been announced (only the 157 cr salary cap), so 125 cr stays an assumption with a dated note; the
  auction is still "reported" for 16 Dec at ITC Grand Goa (briefing 15 Dec; Sporting News 18 Oct, Business
  Standard 19 Oct), retention lists due 15 Nov. New sources in `config/competitions.toml`.
- **I6, purses reconcile for all ten teams.** The 2-6 cr gaps (CSK, DC, KKR, RR) were the 2025 retention
  slabs: a player retained before the 2025 mega auction is charged at his slab (18 / 14 / 11 / 18 / 14,
  uncapped 4), not his salary (DNA India). With that charge (`purse_check_2026.slab_charge`) and Vipraj
  Nigam's 2025 price corrected to 50 lakh (Wikipedia had 30; `salary_note`, kept through `--force`), 125
  − salaries − slab = the published pre-auction purse, and that − our auction prices = the published
  post-auction purse (CSK 2.4, DC 0.35, KKR 0.45, RR 2.65), exactly. The Keep page / `cricdex keep --check`
  show the slab; `tests/test_competitions.py` now requires all ten. Whether the slab counts in 2027 is
  unpublished: `retained_cost` is marked assumed.
- **I6, squad players with no match data.** Three of the 22 had played IPL 2026 under initials and are
  matched by their ESPNcricinfo key: Mukul Choudhary (MD Choudhary, whom the name check had renamed
  "Mukesh Choudhary"), Tejasvi Singh (T Dahiya), Sahil Parakh (SU Parakh); overrides with evidence, master
  rebuilt. The other 19 have no Cricsheet match anywhere (searched with spelling variants and initials).
  Keep or release now prices them from the market model (uncapped Indian, unrated, no IPL record, age
  when known, the role from their auction listing) and shows "no match data — priced from the market" in
  place of a value; the call stays Borderline, and when the auction paid well above the prior (Mangesh
  Yadav 5.2 cr) the reason says franchises saw something our data can't. `keep.py` ⇄ `keep.ts`, parity
  test extended.
- **I7, SMAT staleness made explicit.** Cricsheet still has no SMAT after 15 Dec 2024 (its missing page
  lists the 2024-25 group stage and all of 2025-26) and there is no other open-licence source. Auction-pool
  and Keep rows now carry `stale_share` (share of the evidence behind his value from a stale league) and
  `stale_note` ("SMAT data to Dec 2024"): a badge on the Auction and Bid plan pages, a column in `cricdex
  auction`, and a sentence in the Keep reason at 10%+ ("85% of his rating rests on SMAT data to Dec 2024
  (stale)."). Scout's SMAT pool and gem board already carried the stale badge; Form forecast is IPL-only.
- **I8, captaincy gaps.** Rising Pune Supergiant (Dhoni 2016, Smith 2017) and Gujarat Lions (Raina 2016-17)
  from their season articles; Ireland's Test / ODI / T20I captains from "List of Ireland cricket captains"
  (22 rows, all matched; Porterfield's T20I years fixed by hand, 2008-18, ESPNcricinfo). Pages cached and
  pinned; `scripts/ipl_captains.py --fetch-missing` fetches only what isn't cached. 101 IPL stints (all
  matched), 1,318 international rows (85% matched).

### Style twins rebuilt: players who play like him (roadmap 25 / I12)

- **New similarity, from the ball-by-ball** (`scout/search/style_twin.py`). Batters: slot (balls-weighted
  batting position), powerplay / death share, tempo in each phase against that season's par, boundaries,
  dots, rotation, six share, spin against pace, balls per dismissal, batting hand. Bowlers: powerplay /
  death share of balls, economy in each phase against par, balls per wicket, dots and boundaries
  conceded, bowled-or-lbw and stumped shares, pace and arm. Thin samples shrunk (60-ball phase prior),
  robust z-scores (median / MAD, clipped ±3), fixed weights in the order a fan describes a player
  (METHODOLOGY §5a). Replaces cosine over 13 / 3 pressure-and-skill axes, which gave Mayank Agarwal
  James Hopes and Bumrah Harbhajan Singh.
- **Gates**: 120 balls and 6 innings in the role; an opener's twins are openers first (within 1.5
  batting positions); a seamer's twins are seamers and a spinner's spinners, always; a wrist spinner's
  are wrist spinners first. Never the player himself.
- **"% alike" now means something**: 100 × (1 − weighted RMS z-gap ÷ 2). 100% identical, 50% one SD
  apart on average, about 35% for two random players; a top twin is usually 65–85%. `distance` stays
  1 − alike, so the web, Streamlit, TUI and CLI read the same number; the API rows add `alike`. The CLI
  profile shows "% alike" instead of a raw distance; the web bar's tooltip shows it too.
- Checked by eye on 20 well-known IPL players (Kohli → du Plessis, KL Rahul; Jaiswal ↔ Head; Bumrah →
  Steyn, Archer, Malinga; Kuldeep → Noor Ahmad, Brad Hogg). Tests: `tests/test_style_twins.py`.

### Bid plan: the auction bidding sheet (roadmap Tier A 26b)

- **New page, Bid plan** (`/bidplan`, Scout group, next to Keep or release) and **`cricdex bidplan --team
  RCB`**: the squad and purse from Keep or release (its URL state, so your keep / release calls carry
  over; Keep or release has a "Plan the auction bids" button), the other nine teams bidding 200 times in
  the Auction room's simulator for the price to beat, and an optimiser that picks the targets adding the
  most squad strength (best XI under the 4-overseas rule, depth, role needs incl. pace) for the purse. Per
  target: priority, rivals' median price, max bid (gain ÷ λ, capped by the purse left after the likely
  buys), P(≤ max bid), how often the plan lands him; fallback chains per role; the likely squad, expected
  strength / spend, needs met and still missing. Editable: purse, squad max / min, overseas cap, places
  each team opens (default 8), role needs, your own max bid per player, rival runs; all in the URL; CSV
  export and a print / PDF view. `cricdex.web_parity.bidplan` ⇄ `site/src/lib/bidplan.ts`, locked by
  `test_scripts/test_bidplan_parity.py` (synthetic leagues + all ten real teams). Method: METHODOLOGY §12.
- **The pool as data**: `data/curated/ipl_auction_register.json` (the official list once published) is
  exported as `ipl/auction_register.json` and replaces the inferred pool on the page and the CLI
  (`--register` for a file of your own).
- **Auction simulator calibrated to real auctions** (owner's call: "the obvious must fit reality"):
  `scripts/auction_calibrate.py` replays the 2022 mega and 2023 / 2024 mini auctions (walk-forward values and
  price models, real retentions and purses, sold lots + unsold alternatives) and fits the rivals' bidding:
  a level per auction type (0.86 mega, 1.04 mini), a concave curve on the market price (^0.75), a player's
  last IPL price as a reference (weight 0.3; `anchor_price` on a row), a demand shock per lot per run (ln sd
  1.0) and market tightness (money left ÷ market value of the best unsold players for the places left).
  Out of time (2025, 2026) the simulated 10–90% range holds 77% / 46% of real prices (was 28% / 12%) and the
  dearest simulated lots come out at 1.09× / 1.07× real (was 2.44× / 1.55×); the 2025 mega auction still
  ran ~1.5× above the simulation on contested lots. Neutral settings reproduce the old room
  (`opts["calib"]`). The Auction room keeps every team at 20+ players with ~5 cr left. AUCTION_MATH Part 3b.
- **No buying back your own releases**: the plan never bids for a player its team releases; a release worth
  more to the squad than his salary is listed as "reconsider keeping". A "usually enough" column (the bid
  that wins him in 9 runs of 10) sits next to the max bid (the walk-away price).
- **Replay of the 2025 mega and 2026 mini auctions**: `scripts/bidplan_backtest.py` (walk-forward values
  and price models, real retentions and purses, the pool with unsold alternatives, calibrated rivals, plans
  played against the real prices, squads scored on the next season). Same spend: level with the real squads
  in 2025 (4 of 10 ahead, mean +2) and worse in 2026 (2 of 10); rival price to beat vs real: MAE ln 0.60 /
  0.68, rank correlation 0.80 / 0.50, real inside the 20–80% range 55% / 52% (METHODOLOGY §12, with a
  reality-check table of well-known lots).
- The simulator's `one_trial` ⇄ `oneTrial` take an optional sale callback (the winning bid; Bid plan's
  price to beat). `open` added to Keep or release's `auto_release` kinds (Bid plan only).

### Form forecast: value over the next three seasons (roadmap Tier A 11b)

- **`cricdex.scout.forecast`** + **`scripts/form_forecast.py`** (`fits` → `backtest` → `build` → `export`):
  every IPL player's season value 2008–2026 in the rating's own currency and his career rating at every
  season end (walk-forward refits, the price model's cache).
- **Starts from the current level** (owner's call: the first version anchored on the career rating and had
  Kohli at −1 after +31 / +16 / +30). A local-level Kalman filter per role (true level drifting with age,
  debut prior, season noise ∝ 1 / balls; seven parameters by maximum likelihood on the seasons up to each
  origin) gives every player's current level and its own 1–3-season forecast. A ridge regression per role
  then maps a blend `w × career rating + (1 − w) × level forecast` (w chosen on validation origins 2014–18:
  0.25 for batters, 1 for bowlers, whose career rating is the better current level) plus a residual age curve
  to the value 1, 2 and 3 seasons later.
- Survivorship corrected by inverse-probability weighting (a logistic model of being seen again); age
  curves that rise past 32 (bowlers: selection the data can't see) are held flat, in the drift and the
  residual; Lichtman's phantom-season bound and the survivors-only curve published alongside. 80% ranges for
  his level and for one season (walk-forward calibrated); P(regular) (120+ balls) per horizon.
- **Backtest** (data through 2021 / 2022 / 2023, scored on 2022–2026, 3 ADVI seeds, against the career rating,
  the current level, career numbers, a naive age curve and last season): batters' error 21.6 / 21.4 / 20.5
  runs per 100 balls at 1 / 2 / 3 seasons, the lowest of all (22.8 / 22.8 / 22.7 for the rating, 21.9 / 22.1
  / 21.0 for the level alone), rank 0.20 / 0.16 / 0.14 (rating 0.22 / 0.17 / 0.10); bowlers tie the rating on
  error and rank a little lower; one-season 80% ranges caught 72–82%; P(regular) Brier 0.12–0.15 against
  0.14–0.18 and 0.19–0.22. Reality check of 15 stars against their last three seasons, each disagreement
  explained (METHODOLOGY §11); walk-forward, batters 34+ with a three-season average of +20 or more posted +6
  the next season on average while the forecast had them at +15.
- **Player profile**: a "Form forecast" section (fan chart per role from the current level: median, level and
  one-season 80% bands, P(regular) per season, his last seasons, the outlook badge and line), from
  `site/public/data/ipl/forecast.json`, which `scripts/export_site.py` now writes for the IPL. **Keep or
  release**: a sortable "3-season outlook" column (the three medians, the shape, P(regular) in 2029), in
  `keep.json` (`forecast`), `web_parity/keep.py` ⇄ `site/src/lib/keep.ts` (`forecast_note`, parity-tested),
  the CSV (`outlook_3y_avg`, `outlook_3y`) and `cricdex keep --sort outlook`. **CLI**: `cricdex forecast
  "<name>"` and `cricdex forecast --team RCB`. Retired players get no forecast.
- Tests: `tests/test_forecast.py` (the level model's causality and parameter recovery, projection math on
  synthetic careers, the outlook text, the Keep outlook pick, the site file and backtest schemas) and the
  Keep parity fixtures. Docs: METHODOLOGY §10–11, README, About, CLI, RUNNING, scripts README.

### Prices fitted to real IPL auctions (roadmap Tier B #13, correctness #18)

- **Group-aware calibration**: the calibration now has groups (overseas, capped Indian, uncapped Indian;
  `price.groups` in `config/price_model.json`, ranges on the market features; `calibration_part` ⇄
  `calibrationPart`, parity-tested): the shared quantile map plus each group's mean out-of-fold residual
  as its shift (`--calibration quantile+group-offset`, the new default). Out of time (2025–26), by group
  bias in ln: overseas +0.62 → +0.37, capped Indian +0.25 → −0.06, uncapped Indian −0.26 → +0.04; overall
  mean |ln error| 0.706 → 0.703, median error 51% → 53%, rank corr. 0.745 → 0.731, 10 cr+ ratio
  0.62 → 0.50. A separate map per group and shifts from the last two auctions were tested and are worse;
  the overseas lean left (≈1.45×) moves between auctions and no earlier-years shift removes it. The upper
  quartile now includes the group shift (residual sd 1.02, out of fold). Table by group: METHODOLOGY §6b.
- **Legal default squads in Keep or release** (`fit_to_rules` ⇄ `fitToRules`, parity-tested, plus
  `test_keep_default_plan_is_legal`): the default plan releases kept Borderline players (lowest surplus per
  crore first; a Keep only when no Borderline is left) until the overseas cap and then the squad maximum
  hold, never moving a player the user flipped; each gets "Released to fit the 8-overseas cap" / "the
  25-player squad limit" in his reason and `auto_release` in the CSV. CSK, MI, KKR, SRH and RCB are now
  legal by default (e.g. CSK releases Noor Ahmad and Dian Forrester for the overseas cap).
  `auction_check --trials 300`: every team ≥ 20, 1.5 cr left on average.

- **Auction history**: `scripts/ipl_auction_history.py` parses Wikipedia's per-season IPL personnel pages
  2008–2026 (CC BY-SA 4.0, each pinned to a revision; raw wikitext + HTML cached in
  `data/curated/ipl_auction_pages/`) into the hand-editable `data/curated/ipl_auction_history.json`:
  1,647 sold lots (base price, price, buyer, previous team, set, RTM) and 1,046 retentions with salaries,
  per-season auction date, mega / mini and purse (sourced or marked assumed). US$ prices (2008–2013)
  converted at the Federal Reserve H.10 rate on the auction day. 97% of sold lots and 99% of retentions
  matched to a Cricsheet id (title, name, initial + surname, close spelling). Wikipedia has no unsold lists.
- **Market-price model**: `scripts/ipl_price_model.py fits` re-fits the IPL before every auction date
  (cached, resumable); `fit` rebuilds each player as of his auction (value, caps and recent caps, age,
  IPL balls / seasons / gap, role, overseas, mega) and fits a hurdle model: P(bought) logistic on the
  not-retained IPL players of 2018–2026, ln(price / purse) by Huber regression on the 2018–2026 lots plus
  mega retentions → `config/price_model.json` (shipped in the package). Out of time (train ≤ 2024, test
  2025 mega + 2026 mini): mean |ln error| 0.68 against 0.78 for the old curve, rank correlation 0.74
  against 0.63, P(bought) AUC 0.78 and calibrated; lots of 10 cr+ still predicted at ~0.44×.
- **`market_price` ⇄ `marketPrice`** (`web_parity/pricing.py` ⇄ `site/src/lib/auction.ts`): the same
  features and coefficients, parity-tested on fixed inputs and every pool row. The pool's
  `projected_value` is now the market price (`onfield_value` = the old curve, `p_bought` added); Scout's
  est. prices use it (`scout_price` ⇄ `scoutPrice`); the export writes `ipl/price_model.json` and adds
  `price_value`, `intl_caps`, `intl_caps_2y`, `ipl_balls`, `ipl_seasons`, `ipl_gap` (and `age`,
  `is_overseas` in Scout) to pool, squad and Scout rows. Older exports fall back to the curve.
- **Keep or release** prices each player at the market (median; the upper quartile, ≈1.9×, is the
  "release only if even this is below the salary" figure), with **On-field worth** and the chance he's
  bought as new columns (page, CLI, CSV). Kohli, Gaikwad, Samson, Hardik, Suryakumar and Green move from
  Release to Borderline; Rohit, Narine, Klaasen and Cummins stay Release (age; captaincy isn't modelled).
- **Auction room**: at most 36% of the 200 lots are overseas (`AUCTION_OVERSEAS_SHARE`, the 2024
  shortlist's share); without it the market price filled two-thirds of the lots with overseas players and
  squads stalled below 20. `auction_check --trials 300`: every team reaches 20, 1.4 cr of purse left on
  average.
- Docs: METHODOLOGY §6 (6a on-field worth, 6b market price) and §10, AUCTION_MATH Part 0, README, About.
- **Captaincy data**: `scripts/ipl_captains.py` → `data/curated/ipl_captains.json` (hand-editable): IPL
  captain stints from each franchise article's captains table, filled in from "List of Indian Premier
  League captains" (97 stints, all matched), and men's Test / ODI / T20I captains from 11 Test nations'
  captain lists (1,296 rows, 85% matched); Wikipedia, CC BY-SA, pages cached and pinned in
  `data/curated/ipl_captain_pages/`. `cricdex.scout.identity.captains`: `as_of(cid, season)` (regular IPL
  captain last season, seasons as captain, national captain in the two years before; stand-ins never
  count as last season's captain) and `summary(cid)`.
- **Captaincy in the price**: three new market features (`captain_ipl`, `captain_seasons`,
  `captain_intl`); a regular IPL captain fetches about +22%. Out of time they don't improve the score
  (reported). Shown as a **Captain** badge in Keep or release (with "the market pays captains a premium"
  in the reason; `(C)` in `cricdex keep`), a **C** badge in the Auction room's squads, and IPL / national
  captaincy badges in the profile identity block (`identity.captaincy`). Pool, squad and Scout rows carry
  `captain_ipl_last`, `captain_ipl_seasons`, `captain_intl_2y`, `captain_teams`.
- **Top-end calibration** (`calibrate` ⇄ `calibrate`, knots in `config/price_model.json`): the linear
  predictor goes through a monotone quantile map fitted on out-of-fold predictions. Out of time (train
  and calibrate ≤ 2024, test 2025–26): 10 cr+ lots 0.45× → 0.62× their price, median error 56% → 51%,
  within ±50% 45% → 49%, rank corr. 0.741 → 0.745; mean |ln error| 0.674 → 0.706 and an upward lean (+0.19,
  mostly overseas players, ~1.9×). Isotonic recalibration and Duan smearing were tested and rejected
  (smearing over-prices the typical lot ~2–2.5×). The upper quartile now uses the out-of-fold residual
  sd (1.06). `auction_check --trials 300`: every team ≥ 20, 1.2 cr left on average.

### Keep or release: the retention calculator (roadmap Tier A #7)

- **New page, Keep or release** (`/keep`, in the Scout group next to the Auction room) and **`cricdex keep
  --team RCB`**: for each player in a franchise's squad, his salary against our estimated auction price
  (the pool's curve: cautious estimate, IPL-evidence ceiling), surplus, a Keep / Release / Borderline call
  with a one-line reason, age and outlook, and last season's raw numbers; then the squad if you follow it
  (purse left, open slots, warnings) and the role gaps (keepers, openers, death bowlers, spinners, overseas)
  filled cheapest-first from free agents plus the other teams' release calls. Any call can be flipped and
  the purse / role targets changed (kept in the URL); CSV export on the page and with `--csv`.
  `cricdex.web_parity.keep` ⇄ `site/src/lib/keep.ts`, locked by `test_scripts/test_keep_parity.py`
  (synthetic squads covering every branch plus every real team). Method: METHODOLOGY §10.
- **Competition rules as config**: `config/competitions.toml` + `cricdex.competitions` (validated like the
  league registry; `python -m cricdex.competitions check`). One entry, `ipl_2027`: deadline 15 Nov 2026,
  auction likely 16 Dec 2026 in Goa, 25-man squads with 8 overseas, no retention limit, kept players cost
  their salary, no RTM, 18 cr overseas fee cap. Every rule cites a source or is listed as `assumed`
  (purse: no 2027 figure published, 125 cr assumed; squad minimum 18; no minimum spend; replacements
  keepable; the auction date). Ships inside the package like `leagues.toml`.
- **Salaries in the squads file**: `scripts/ipl_squad_salaries.py` adds `salary_cr`, `acquired`,
  `country` / `overseas` and `cricsheet_id` to every row of `data/curated/ipl_squads_2026.json` from
  Wikipedia's 2026 personnel page (retained-list salaries, auction prices, replacement fees, trades), then
  applies the 2027 page's moves (Pant ⇄ Kuldeep Yadav, Natarajan ⇄ Zeeshan Ansari, Rahane retired). 274
  players, all with a salary; 252 matched to a Cricsheet id, 22 listed as unmatched. Mustafizur Rahman
  marked released (BCCI request). The file also keeps the published 2026 pre-auction purses as a check
  (six teams reproduce exactly).
- **Exporter**: the IPL export writes `ipl/keep.json` (~100 KB). `_export_auction_pool` also returns the
  same row for every squad player (thin records included), so a squad player's value is the pool's value;
  `auction_pool.json`, `activity_index.json` and `scout_index.json` are byte-identical to before.

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
