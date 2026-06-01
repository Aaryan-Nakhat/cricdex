# CricDex

Open cricket intelligence platform — natural-language rule Q&A, novel
sabermetrics (NGI / WPA, Crease Longevity, Slow-Start Cost, Wicket
Quality, Pressure Runs, …), multi-tier scouting graph with
dismissal-aware Bayesian opponent-adjusted ratings, MILP auction
war-room + GRPO auction self-play + substitute advisor, side-by-side
comparator.

**Distribution is terminal-first.** A single console script `cricdex`
fronts everything; a Streamlit dashboard is included as an optional
browser view of the same data.

## Install

```bash
# One-shot run (no install)
uvx --from cricdex cricdex --help

# Global install
pip install cricdex                            # base CLI
pip install 'cricdex[cli,graph,ui]'            # rich/textual TUI +
                                                # Neo4j scout graph +
                                                # Streamlit dashboard
```

## First run (5 commands)

```bash
cricdex init                                   # wizard + Gemini key
cricdex data ingest cricsheet -c ipl           # ~600 MB ball-by-ball
cricdex data ingest rules                      # 21 PDFs + 11 k clauses
cricdex data ingest metrics -c ipl             # 9 leaderboards
cricdex leaderboard ngi -c ipl --top 15        # your first query
```

Optional next step — `cricdex dashboard` opens the Streamlit UI on
`http://localhost:8501` reading the same `~/.cricdex/data/`.

Full command reference: [`docs/CLI.md`](docs/CLI.md). Onboarding flow:
[`docs/FIRST_RUN.md`](docs/FIRST_RUN.md). Architecture:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Pending work
(phase-grouped): [`docs/TODO.md`](docs/TODO.md). Canonical catalogue
of every known gap + fix path: [`docs/DEFERRED.md`](docs/DEFERRED.md).

## Modules

All shipped unless marked otherwise. See `docs/ROADMAP.md` for ✅ /
⏸ / ⏳ status of every subsidiary feature.

| Module | What |
|---|---|
| `scout` | Per-collection player graph (Neo4j) + dismissal-aware Bayesian opponent-adjusted ratings (NumPyro/JAX, ADVI + NUTS — scoring + survival for batters, economy + strike for bowlers) + style-twin k-NN. |
| `metrics` | 10 novel context-adjusted ratings: NGI, Pressure Runs, Intent Curve, Dot-Ball Recovery, Counter-Attack, Boundary Dependency, Pressure Conversion, Wicket Quality, Crease Longevity, Slow-Start Cost. + per-player/matchup dismissal fingerprint. |
| `rules` | Natural-language Q&A over verified rulebook PDFs (MCC Laws + ICC PCs + IPL + Hundred + BBL/WBBL + Cricket Australia domestic + ICC Codes + Anti-Corruption). 11k+ clauses indexed in Qdrant. Curated supplementary clauses cover gaps such as the IPL Impact Player rule. |
| `auction` | MILP squad optimiser via `scipy.optimize.milp` + Monte-Carlo price-band simulator (real IPL teams, editable bidding personalities) + GRPO RL self-play scaffold + war-room substitute advisor (composite of graph similarity + Bayes complete-value + budget). CLI + dashboard war-room. |
| `records` | 9 record SQL queries + On-This-Day digest. |
| `venues` | Per-venue innings totals + chase/set winrate + phase rates + dismissal mix. |
| `profiles` | Per-player profile assembler aggregating every source CricDex has. |
| `comparator` | Plotly-radar + transposed table side-by-side + probabilistic skill head-to-head. |
| `api` | FastAPI public REST surface + OpenAPI at `/docs`. See [`docs/API.md`](docs/API.md). |
| `dashboard` | 10-page Streamlit app: Leaderboards, Rules Chat, Records, Compare, Venues, Auction (MILP + war-room advisor), Player Profile (Wikidata photo + DOB + dismissal fingerprint), Auction Simulator (Monte-Carlo + GRPO RL), Player Twins (per-collection graph), Update Data. |

Cricsheet-only: all data derives from Cricsheet ball-by-ball + the
People Register + (one-time) Wikidata enrichment. Live-feed, scrape,
and non-Cricsheet sources are intentionally out of scope.

Deferred to year 2: OpenBoundary (Hawk-Eye OSS), ChuckCheck (elbow flex
biomechanics), ScoutVLM (video → ball-by-ball), Highlight CV,
CricHeroes grassroots tier.

## Stack

- Python 3.12, `uv` package manager
- DuckDB (analytics) · NumPyro / JAX (Bayesian ratings) · Qdrant (vectors) · Snowflake-arctic-embed-l-v2 (multilingual, Matryoshka-truncated to 384-dim) · PyTorch (GRPO auction agent)
- FastAPI + Uvicorn (service layer)
- Postgres + Redis + Neo4j (planned as scout / cache / graph come online)
- Docker + Docker Compose (deployment)

## Repository layout

```
src/cricdex/        Python package; one subfolder per module
scripts/            Typer CLIs for each pipeline
data/               raw + processed datasets (gitignored except curated/)
data/rules/curated/ hand-curated supplementary rule clauses (committed)
notebooks/          exploration
tests/              pytest
docs/               ARCHITECTURE, ROADMAP, DECISIONS, RUNNING, DOCKER, UPDATING_RULES
docker/             (placeholder for future Dockerfiles per service)
Dockerfile          multi-stage app image
docker-compose.yml  local stack — Qdrant + app
Makefile            top-level workflow targets
```

## License

MIT.
