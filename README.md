# CricDex

Open cricket intelligence platform — natural-language rule Q&A, novel
sabermetrics (NGI / WPA, Phase Dilation, Setting Tax, Wicket Quality,
Pressure Runs, …), multi-tier scouting graph with Bayesian opponent-
adjusted ratings, MILP auction war-room + GRPO auction self-play +
substitute advisor, side-by-side comparator, multilingual commentary
translator, DRS practice game, daily newsletter digest.

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
| `scout` | Player graph (Neo4j) + Bayesian opponent-adjusted ratings (NumPyro/JAX, ADVI + NUTS) + style-twin k-NN. Pro tier ingested; grassroots / CricHeroes tier planned. |
| `metrics` | Six novel context-adjusted ratings: Pressure Runs, Intent Curve, Recoverability, Counter-Attack, Boundary Dependency, Sticky Dot Pressure. |
| `rules` | Natural-language Q&A over 21 verified rulebook PDFs (MCC Laws + ICC PCs + IPL + Hundred + BBL/WBBL + SA20 + Cricket Australia domestic + ICC Codes + Anti-Corruption). 11k+ clauses indexed in Qdrant. Curated supplementary clauses cover gaps such as the IPL Impact Player rule. |
| `pulse` | Reddit fetcher + Gemini sentiment extractor. Data load blocked from datacenter IPs. |
| `auction` | MILP squad optimiser via `scipy.optimize.milp` + Monte-Carlo price-band simulator + GRPO RL self-play (`scripts/train_auction_grpo.py`, real 429-player IPL pool, 6 franchise archetypes) + war-room substitute advisor (`scripts/auction_advisor.py`, composite of graph similarity + Bayes value + budget). CLI + dashboard war-room. |
| `drs` | 20-scenario umpire-decision practice game with MCC / ICC citations. |
| `records` | 9 record SQL queries + On-This-Day digest. |
| `reports` | LLM-written match reports grounded in Cricsheet facts, no hallucinations. |
| `predict` | Deferred — needs the `live` feed first. |
| `live` | Cricbuzz live-score fetcher. Pipeline correct; data load blocked from datacenter IPs. |
| `venues` | Per-venue innings totals + chase/set winrate + phase rates + dismissal mix. |
| `profiles` | Per-player profile assembler aggregating every source CricDex has. |
| `comparator` | Plotly-radar + transposed table side-by-side. |
| `newsletter` | Markdown digest compiler (On-This-Day + headlines + auto match report). |
| `commentary_translate` | English → Hindi / Tamil / Bengali / Urdu / Sinhala / Marathi / Telugu / Kannada (text-only). Voice-cloned audio deferred to year 2. |
| `api` | FastAPI public REST surface (12 endpoints + OpenAPI at `/docs`). See [`docs/API.md`](docs/API.md). |
| `dashboard` | 12-page Streamlit app: Home, Leaderboards, Rules Chat, Records, Match Reports, Compare, Venues, Auction (MILP + war-room advisor), Player Profile (with Wikidata photo + DOB + social links), Translate Commentary, Auction Simulator (Monte-Carlo + GRPO RL), Player Twins (graph similarity, role-archetype auto-flip). |

Deferred to year 2: OpenBoundary (Hawk-Eye OSS), ChuckCheck (elbow flex
biomechanics), Voice analyst, ScoutVLM (video → ball-by-ball), Highlight
CV, Tournament B2B.

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
