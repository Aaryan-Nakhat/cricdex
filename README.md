# CricDex

Open cricket intelligence platform — novel sabermetrics (NGI / WPA,
Crease Longevity, Slow-Start Cost, Wicket Quality, Pressure Runs, …),
dismissal-aware Bayesian opponent-adjusted ratings, cross-competition
scout look-alikes, real-rules IPL auction Monte-Carlo, and a side-by-side
comparator.

**One source of truth.** The React static web app is canonical; the CLI,
Textual TUI, and Streamlit dashboard mirror the same analytical pages and
run the same logic via `cricdex.web_parity` (a Python port of the web's
TypeScript auction + scout, locked by `test_scripts/test_web_parity.py`).
Live demo: https://aaryan-nakhat.github.io/cricdex/

## Install (clone + uv)

```bash
git clone git@github.com:Aaryan-Nakhat/cricdex.git
cd cricdex
uv sync                       # base CLI
uv sync --extra cli --extra ui   # + TUI + Streamlit dashboard
uv run cricdex --help
```

## First run (4 commands)

```bash
cricdex init                                   # wizard + Gemini key
cricdex data ingest cricsheet -c ipl           # ~600 MB ball-by-ball
cricdex data ingest metrics -c ipl             # 10 leaderboards
cricdex leaderboard ngi -c ipl --top 15        # your first query
```

Optional next step — `cricdex dashboard` opens the Streamlit UI on
`http://localhost:8501` reading the same `~/.cricdex/data/`.

Full command reference: [`docs/CLI.md`](docs/CLI.md). Onboarding flow:
[`docs/FIRST_RUN.md`](docs/FIRST_RUN.md). Architecture:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Pending work
(phase-grouped): [`docs/TODO.md`](docs/TODO.md). Known gaps + year-2
backlog: [`docs/DEFERRED.md`](docs/DEFERRED.md).

## Modules

All shipped unless marked otherwise. See `docs/ROADMAP.md` for ✅ /
⏸ / ⏳ status of every subsidiary feature.

| Module | What |
|---|---|
| `scout` | Cross-competition look-alike finder across six pools (IPL, SMAT uncapped Indian, BBL, SA20, CPL, T20 Blast) — one implementation shared across web + CLI + TUI + Streamlit via `cricdex.web_parity` (locked by `test_web_parity.py`). Ranked by within-tier Bayesian skill-standing z-score, with per-row est. crore price + saving-vs-pick (budget swap), uncapped-gem flag, role/slot filters, and one-click draft into the auction. Backed by dismissal-aware Bayesian opponent-adjusted ratings (NumPyro/JAX, ADVI + NUTS — scoring + survival for batters, economy + strike for bowlers). |
| `metrics` | 10 novel context-adjusted ratings: NGI, Pressure Runs, Intent Curve, Dot-Ball Recovery, Counter-Attack, Boundary Dependency, Pressure Conversion, Wicket Quality, Crease Longevity, Slow-Start Cost. + per-player/matchup dismissal fingerprint. |
| `auction` | Real-rules IPL auction Monte-Carlo — cross-collection pool (IPL + BBL/SA20/CPL/Blast free agents + uncapped SMAT) **weighted by IPL-relevance** (per-league last-played + age, so league-only veterans don't top the IPL pool), editable Mega/Mini retentions from the real 2025 lists, overseas cap + retention slabs, second-price clearing, two-phase fill to 20–25-man squads (~300 trials, per-player post-sim search). One implementation shared across web + CLI + TUI + Streamlit via `cricdex.web_parity`, bit-exact seeded RNG, locked by `test_web_parity.py`. |
| `matchups` / `phase` / `form` | Batter-vs-bowler head-to-heads + pace/spin splits; powerplay / middle / death specialist boards; recent-form-vs-career deltas (direction-corrected) — all four surfaces, reading the same exported JSON, with the full player filter bar. |
| `records` | 9 record SQL queries + On-This-Day digest. |
| `venues` | Per-venue innings totals + chase/set winrate + phase rates + dismissal mix. |
| `profiles` | Per-player profile assembler aggregating every source CricDex has. |
| `comparator` | Plotly-radar + transposed table side-by-side + probabilistic skill head-to-head. |
| `api` | FastAPI public REST surface + OpenAPI at `/docs`. See [`docs/API.md`](docs/API.md). |
| `dashboard` | Streamlit app mirroring the web pages: Leaderboards, Player Profile (Wikidata photo + DOB + dismissal fingerprint + style twins), Compare, Head-to-head, Matchups, Phase, Form, Scout, Auction, Records, Venues, Update Data. |

Cricsheet-only: all data derives from Cricsheet ball-by-ball + the
People Register + (one-time) Wikidata enrichment. Live-feed, scrape,
and non-Cricsheet sources are intentionally out of scope.

Deferred to year 2: OpenBoundary (Hawk-Eye OSS), ChuckCheck (elbow flex
biomechanics), ScoutVLM (video → ball-by-ball), Highlight CV,
CricHeroes grassroots tier.

## Stack

- Python 3.12, `uv` package manager
- DuckDB (analytics) · NumPyro / JAX (Bayesian ratings) · exported JSON snapshots (file-driven; no vector DB, no graph DB)
- FastAPI + Uvicorn (REST) · React + Vite static site (GitHub Pages)
- Docker + Docker Compose (local stack + the nightly refresh pipeline)

## Repository layout

```
src/cricdex/        Python package; one subfolder per module
scripts/            Typer CLIs for each pipeline
data/               raw + processed datasets (gitignored except curated/)
notebooks/          exploration
tests/              pytest
docs/               ARCHITECTURE, ROADMAP, DECISIONS, RUNNING, DOCKER
docker/             (placeholder for future Dockerfiles per service)
Dockerfile          multi-stage app image
docker-compose.yml  local stack — app
Makefile            top-level workflow targets
```

## License

MIT.
