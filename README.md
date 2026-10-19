# CricDex

### The numbers behind cricket, honestly modelled.

Run the IPL mega auction yourself. See who really won a match, ball by ball. Rate every player against
the attacks they actually faced, with the error bars left in. Then check, out of sample, whether any of
it predicts anything.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Data](https://img.shields.io/badge/data-Cricsheet%20ball--by--ball-2E7D32)
![Models](https://img.shields.io/badge/models-NumPyro%20·%20XGBoost-6E56CF)
![Store](https://img.shields.io/badge/store-DuckDB-FFF000?logo=duckdb&logoColor=black)
![Surfaces](https://img.shields.io/badge/use%20it-web%20·%20CLI%20·%20TUI%20·%20Streamlit%20·%20API-0088CC)
![License](https://img.shields.io/badge/license-MIT-informational)
[![CI](https://github.com/Aaryan-Nakhat/cricdex/actions/workflows/ci.yml/badge.svg)](https://github.com/Aaryan-Nakhat/cricdex/actions/workflows/ci.yml)

<p align="center"><a href="https://github.com/Aaryan-Nakhat/cricdex/raw/main/docs/media/hero.mp4"><img src="docs/media/hero.gif" alt="A 45-second tour of CricDex: the IPL mega auction run 300 times; a real chase scored ball by ball for win probability; Bayesian ratings with their uncertainty; cross-league look-alikes with estimated prices; the honest backtest" width="100%"></a></p>

<p align="center"><b><a href="https://aaryan-nakhat.github.io/cricdex/">Open the live site</a></b> · no install, runs in your browser</p>

**[Auction room](#-run-the-ipl-mega-auction-yourself)** · **[Net Game Impact](#-who-really-won-it)** ·
**[Bayesian ratings](#-skill-judged-by-who-it-came-against)** · **[Scout](#-same-mould-other-leagues)** ·
**[Ten metrics](#-ten-numbers-a-scorecard-hides)** · **[The backtest](#-does-any-of-it-predict-anything)** ·
**[How it works](#-how-it-works)** · **[Quickstart](#-quickstart)** · **[Docs](#-docs)**

**10,300+ T20 matches. 2.3 million balls. Fifteen competitions. Every number computed from Cricsheet's
ball-by-ball data, and every model explained in plain English.**

---

## 🔨 Run the IPL mega auction yourself

<p align="center"><img src="docs/media/auction.png" alt="The mega auction: purse used per team, the top buys with their most likely team, and how a team bids" width="100%"></p>

Ten franchises keep their real 2025 retentions, then bid for every active T20 player, each in its own
style: the marquee chaser overpays for stars, the value hunter walks away from bidding wars, the
overseas-heavy side fills its eight slots. One auction is played 300 times with the order shuffled, so
you see **who lands each star, how often, and for how much**, and how every squad ends up.

- **Real rules:** 120 cr purse, retention slabs, 8 overseas max, 20 to 25-man squads.
- **Bidding that behaves like the real room:** a team with more money left per open slot bids harder,
  the winner pays just above the second-best bid, and no player goes above 27 cr (the real record) or
  above his own ceiling, which rises with how much IPL cricket he has played.
- **Yours to change:** release or add any retention, swap a team's personality, change the purse.
- **The pool is the whole T20 world:** IPL players plus free agents from the SMAT and every overseas
  league in the registry (BBL, SA20, CPL, T20 Blast, PSL, ILT20, The Hundred, MLC, BPL, LPL and more),
  weighted by how relevant they are to the IPL right now.

Prices are estimated from the skill model, calibrated to recent auctions, on a cautious estimate (value
minus half its uncertainty) and under a ceiling that rises with IPL experience, so a short, hot record
is priced below a proven one. They model how the room
behaves, not the exact crore of a real sale. → [How the auction works](docs/AUCTION_MATH.md)

## 📈 Who really won it?

<p align="center"><img src="docs/media/ngi.png" alt="Net Game Impact on a real chase: the win-probability line, and who gets the credit" width="100%"></p>

**Net Game Impact (NGI)** credits every ball by how much it moved the win. A calibrated win-probability
model reads the match before each delivery (score, wickets and balls left, target, required rate, run
rate against the ground's average and against the league's recent scoring level). The change after the
ball is that ball's value, credited to whoever caused it: runs off the bat to the striker and against the
bowler, wides and no-balls to the bowler alone, a wicket against the batter who is out, and a share of
catches, stumpings and run outs to the fielders. So a 30* that wins a tight chase counts for more than a
hundred in a lost cause.

Every ball is scored by a model that never saw that match, and per-match numbers count the matches a
player was in the XI. → [NGI in detail](docs/METHODOLOGY.md#2-net-game-impact-ngi)

## 🎯 Skill, judged by who it came against

<p align="center"><img src="docs/media/ratings.png" alt="Bayesian batting skill for two players with very different sample sizes, head-to-head odds, and the top active IPL batters and bowlers with their ranges" width="100%"></p>

Raw averages flatter a batter who feasted on weak attacks. The Bayesian model fits every player at once,
so runs against a great attack count for more, and every ball is judged against its own season, phase,
innings and ground, so a 2026 strike rate isn't compared with a 2009 one. Batters get a **scoring** and a **survival** rating,
bowlers an **economy** and a **strike** rating, and every rating comes with **how sure it is**. The two
combine into one **value in runs per 100 balls**, with a wicket priced at what it costs where the player
bats or bowls (about 14 runs early in the powerplay, 2–3 at the death), so a finisher is judged mainly on
how fast he scores. A player
with 400 balls gets a wide range; one with 7,000 gets a narrow one. Head-to-heads ("how likely is A
better than B?") use both ranges, so a thin record can't win the argument on its own.

→ [The rating model](docs/METHODOLOGY.md#4-bayesian-skill-ratings) · [Model notes](src/cricdex/scout/ratings/README.md)

## 🔭 Same mould, other leagues

<p align="center"><img src="docs/media/scout.png" alt="Scout: an IPL bowler and look-alikes from six pools, with match score, estimated price and saving" width="100%"></p>

Pick an IPL player. **Scout** finds players of the same role and type across every pool (IPL, SMAT,
and each overseas league: BBL, SA20, CPL, T20 Blast, PSL, ILT20, The Hundred, MLC and more), ranks them by how they stand **within their own league**, and prices each
one with the auction's own curve, so you see the budget swap and the saving. Uncapped prospects punching
above their sample get a gem flag, and one click drafts a prospect into the auction room.
→ [Scout](docs/SCOUT.md)

## 📊 Ten numbers a scorecard hides

<p align="center"><img src="docs/media/metrics.png" alt="The ten context metrics, the fielding boards and the other pages" width="100%"></p>

A 25-ball 40 in a slack chase and a 25-ball 40 chasing 12 an over look the same on a scorecard. These
put the context back: NGI, Pressure Runs, Intent Curve, Dot-Ball Recovery, Counter-Attack, Boundary
Dependency, Pressure Conversion, Wicket Quality, Crease Longevity and Slow-Start Cost, plus wicketkeeping
and fielding boards. Every board exists for every league and three time windows (all-time, last three
years, last year), and each metric is explained on the site. Also on every surface: matchups, phase
specialists, form, partnerships, aging curves, records and venues. → [Metric formulas](docs/METRICS.md)

## 🧪 Does any of it predict anything?

<p align="center"><img src="docs/media/backtest.png" alt="The backtest: model against plain baselines, and how sure each gap is over 2,000 resamples" width="100%"></p>

We checked, out of sample. For each season the model is fitted only on matches **before** it, then its
ranking of players is compared with how the season went (Spearman rank correlation: 1 = same order,
0 = no link). The baselines get the same league adjustment as the model, every fit is run with 3 seeds,
and the newcomer gaps are bootstrapped 2,000 times with a correction for running six tests:

| | CricDex | Plain baseline |
|---|---|---|
| Established IPL batters, next season (2021–26) | **0.19** | 0.15 (career average) |
| Established IPL bowlers, next season (2021–26) | **0.15** | 0.11 (career average) |
| IPL newcomer batters, rated from other leagues (2014–26, 103 players) | **0.22** | 0.10 (league-adjusted numbers there) |
| IPL newcomer bowlers, rated from other leagues (2014–26, 132 players) | 0.18 | **0.24** (league-adjusted numbers there) |

**The honest read:** an earlier version of this page claimed a survival edge for newcomer batters that held
in 97% of re-draws. That doesn't survive a fair, league-adjusted baseline: the edge was mostly the league
discount itself. With the fixes, the model ranks newcomer batters better **overall** (ahead in 96% of
resamples with all 13 other leagues, 98% with the original five), but nothing is significant after
correcting for six tests (best adjusted p = 0.15), and bowlers show no edge. For players the IPL already
knows, its value in runs edges career averages for both batters and bowlers, and the new model predicts held-out
balls better than the old one in every season. A single T20 season is mostly noise, so read the newcomer
result as **a lean, not proof**. Re-run it yourself with `scripts/backtest_ratings.py` and
`scripts/backtest_newcomers.py`.
→ [The backtest in detail](docs/METHODOLOGY.md#8-does-it-predict-the-backtest)

## 🧠 How it works

<p align="center"><img src="docs/media/architecture.png" alt="Cricsheet and the People Register into DuckDB, the models, exported JSON, and the five surfaces sharing one logic" width="100%"></p>

- **Open data only.** Cricsheet ball-by-ball plus its People Register (one id per player across every
  league), and a one-time Wikidata pass for dates of birth and photos. No scraping, no live feed.
- **Computed, not generated.** The one AI step tags each player's role, bowling type and country (an LLM
  via LiteLLM, any provider you set in `.env`), and it's marked "AI-classified" wherever it shows.
  Every stat and rating is computed.
- **One logic, five surfaces.** A Python pipeline builds the ratings and metrics into JSON. The static
  website reads it and runs the auction and Scout in your browser. The CLI, terminal UI, Streamlit
  dashboard and API run the same logic through `cricdex.web_parity`, a Python port with a bit-exact
  seeded random generator. Parity tests in CI keep the two identical, trial for trial.
- **Honest by default.** Super overs are left out, renamed grounds are merged into one venue, every
  rating carries its uncertainty, and the limits are written down. → [Methodology](docs/METHODOLOGY.md)

## 🚀 Quickstart

The quickest way is the [live site](https://aaryan-nakhat.github.io/cricdex/). To run it on your own
machine (Python 3.12 and [uv](https://docs.astral.sh/uv/)):

```bash
git clone https://github.com/Aaryan-Nakhat/cricdex.git
cd cricdex
uv sync                                        # CLI + terminal UI  (uv sync --extra ui adds Streamlit)

uv run cricdex init                            # set-up wizard (an LLM key is optional)
uv run cricdex data ingest cricsheet -c ipl    # IPL ball-by-ball, a few MB
uv run cricdex data ingest metrics -c ipl      # leaderboards + rebuilds the site data
uv run cricdex leaderboard ngi -c ipl --top 15 # your first query
```

Bare `cricdex` opens the terminal UI, `cricdex dashboard` the Streamlit app, and `cricdex auction room`
runs the auction in your terminal. Docker: [`docs/DOCKER.md`](docs/DOCKER.md). Every command:
[`docs/CLI.md`](docs/CLI.md). Step by step: [`docs/FIRST_RUN.md`](docs/FIRST_RUN.md).

## 📚 Docs

| Read | For |
|---|---|
| [Methodology](docs/METHODOLOGY.md) | every model in plain English, with worked examples, the backtest and the limits |
| [Metrics](docs/METRICS.md) · [Auction math](docs/AUCTION_MATH.md) · [Scout](docs/SCOUT.md) · [Identity](docs/IDENTITY.md) | the exact rules behind each feature |
| [First run](docs/FIRST_RUN.md) · [Running](docs/RUNNING.md) · [CLI](docs/CLI.md) · [API](docs/API.md) · [Docker](docs/DOCKER.md) | using it |
| [Architecture](docs/ARCHITECTURE.md) · [Study guide](docs/STUDY_GUIDE.md) | how the code fits together, in depth |
| [Roadmap](docs/ROADMAP.md) · [Changelog](docs/CHANGELOG.md) · [Decisions](docs/DECISIONS.md) | where it's going and why it is the way it is |

All docs: [`docs/README.md`](docs/README.md).

## Stack

Python 3.12 and uv · DuckDB · NumPyro / JAX (Bayesian ratings) · XGBoost (win probability) · FastAPI ·
Typer + Textual (CLI, terminal UI) · Streamlit · React + Vite + Tailwind (static site on GitHub Pages) ·
Docker · GitHub Actions (tests, parity tests, on-demand data refresh and redeploy).

```
src/cricdex/     the Python package, one folder per module
scripts/         pipeline, export, backtest and README-render scripts (see scripts/README.md)
site/            the React website; site/public/data is the committed data snapshot
tests/           pytest
test_scripts/    web ↔ Python parity tests
docs/            methodology, reference and project docs; docs/media holds the README visuals
```

## Credits and license

Ball-by-ball data and the People Register come from [Cricsheet](https://cricsheet.org/), with thanks;
dates of birth and photos from [Wikidata](https://www.wikidata.org/). CricDex is MIT licensed.
