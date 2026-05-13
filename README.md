# CricDex

Open cricket intelligence platform — natural-language rule Q&A, novel
sabermetrics, multi-tier scouting graph, multi-agent auction simulator,
social-pulse analyser, and more. All modules ship behind a single
`docker compose up` so anyone can run the whole stack locally.

## Quickstart (Docker)

```bash
git clone https://github.com/Aaryan-Nakhat/cricdex.git
cd cricdex
cp .env.example .env
# (Optional) edit .env to wire up Gemini proxy / HF token / etc.

make docker-up                                # Qdrant + API on :8080
# --- Rules ---
make docker-ingest-rules-download             # 21 rulebook PDFs
make docker-ingest-rules-parse                # → ~11k clauses
make docker-embed-rules                       # → Qdrant collection
make docker-query Q="impact player rule" FORMATS=ipl
# --- Metrics + identity ---
make docker-ingest-cricsheet COLLECTION=ipl   # IPL ball-by-ball → DuckDB
make docker-ingest-people                     # cross-ID register
make docker-metrics-all COLLECTION=ipl        # 6 novel metrics → JSON
# --- Dashboard ---
make docker-dashboard-up                      # Streamlit on :8511
```

See [`docs/RUNNING.md`](docs/RUNNING.md) for the local `uv` path and the
full pipeline catalogue. See [`docs/DOCKER.md`](docs/DOCKER.md) for image
+ compose design notes. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the cross-module data flow. See [`docs/DEFERRED.md`](docs/DEFERRED.md)
for every known gap + the concrete fix path for each.

## Modules

All shipped unless marked otherwise. See `docs/ROADMAP.md` for ✅ /
⏸ / ⏳ status of every subsidiary feature.

| Module | What |
|---|---|
| `scout` | Player graph (Neo4j) + Bayesian opponent-adjusted ratings (NumPyro/JAX, ADVI + NUTS) + style-twin k-NN. Pro tier ingested; grassroots / CricHeroes tier planned. |
| `metrics` | Six novel context-adjusted ratings: Pressure Runs, Intent Curve, Recoverability, Counter-Attack, Boundary Dependency, Sticky Dot Pressure. |
| `rules` | Natural-language Q&A over 21 verified rulebook PDFs (MCC Laws + ICC PCs + IPL + Hundred + BBL/WBBL + SA20 + Cricket Australia domestic + ICC Codes + Anti-Corruption). 11k+ clauses indexed in Qdrant. Curated supplementary clauses cover gaps such as the IPL Impact Player rule. |
| `pulse` | Reddit fetcher + Gemini sentiment extractor. Data load blocked from datacenter IPs. |
| `auction` | MILP squad optimiser via `scipy.optimize.milp` + Monte-Carlo price-band simulator + GRPO RL self-play scaffold (`scripts/train_auction_grpo.py`). CLI + dashboard war-room. |
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
| `dashboard` | 11-page Streamlit app: Home, Leaderboards, Rules Chat, Records, Match Reports, Compare, Venues, DRS Practice, Auction, Player Profile, Translate Commentary. |

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
