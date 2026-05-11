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

make docker-up                       # boots Qdrant + the app on :8080
make docker-ingest-rules-download    # 21 rulebook PDFs → data/rules/raw/
make docker-ingest-rules-parse       # → ~11k clause JSONL
make docker-embed-rules              # → Qdrant collection
make docker-query Q="what is the impact player rule in IPL" FORMATS=ipl
```

See [`docs/RUNNING.md`](docs/RUNNING.md) for the local `uv` path and the
full pipeline catalogue. See [`docs/DOCKER.md`](docs/DOCKER.md) for image
+ compose design notes. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the cross-module data flow.

## Modules

| Module | Status | What |
|---|---|---|
| `scout` | planned P0 | Player graph + opposition-bridged ratings spanning pro → semi-pro → grassroots (Cricsheet + Cricinfo + Cricbuzz + BCCI Domestic + CricHeroes). |
| `metrics` | planned P0 | Novel context-adjusted ratings (Pressure Runs, Intent Curve, Recoverability, Sticky Dot Pressure, Wicket Quality, NGI/WAR-cricket, etc). |
| `rules` | shipped v0 | Natural-language Q&A over cricket rulebooks (MCC Laws + ICC PCs men/women/U19 + IPL + WPL + Hundred + BBL + WBBL + SA20 + ILT20 + MLC + CPL + LPL + Cricket Australia domestic + ICC Codes + Anti-Corruption). 21 PDFs verified, 11k+ clauses indexed in Qdrant. Curated supplementary clauses cover gaps where the rule lives in a non-public BCCI doc (e.g. IPL Impact Player Regulations 2025-27). |
| `pulse` | planned P1 | Social trend analysis across Reddit + Bluesky + YouTube + Telegram + Twitter. Sentiment, rumour detection, hype-reality gap. |
| `auction` | planned P1 | Multi-agent RL auction simulator with per-franchise personality priors. |
| `drs` | planned P1 | DRS scenario simulator + umpire/scorer practice gamification. |
| `records` | planned P1 | Searchable records DB + On-This-Day digest. |
| `reports` | planned P1 | Auto-generated post-match reports. |
| `predict` | planned P1 | Daily prediction game (no money). |
| `live` | planned P1 | Live match insights surfacer. |
| `venues` | planned P1 | Pitch + conditions archive per venue. |
| `profiles` | planned P1 | Public claimable player profiles. |
| `comparator` | planned P1 | Visual career side-by-side. |
| `newsletter` | planned P1 | Per-user/team digest engine. |
| `commentary_translate` | planned P1, voice-clone P3 | Live commentary translation into IN regional languages; voice-cloned target-language audio is the final-feature milestone. |
| `api` | shipped v0 (`/health`) | Public REST surface. |

Deferred to year 2: OpenBoundary (Hawk-Eye OSS), ChuckCheck (elbow flex
biomechanics), Voice analyst, ScoutVLM (video → ball-by-ball), Highlight
CV, Tournament B2B.

## Stack

- Python 3.12, `uv` package manager
- DuckDB (analytics) · PyMC (ratings) · Qdrant (vectors) · sentence-transformers MiniLM (embeddings)
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
