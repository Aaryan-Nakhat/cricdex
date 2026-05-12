.PHONY: install dev lint format format-check check fix test clean api \
        docker-build docker-up docker-down docker-logs docker-shell \
        docker-ingest-cricsheet docker-ingest-rules-download docker-ingest-rules-parse \
        docker-embed-rules docker-test docker-query

install:
	uv sync

dev:
	uv sync --all-extras --group dev
	uv run playwright install chromium

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

format:
	uv run ruff format .

check: lint format-check

fix:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

api:
	uv run uvicorn cricdex.api.main:app --reload --port 8080

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build

# ---------------------------------------------------------------------------
# Docker workflow
# ---------------------------------------------------------------------------
# Anyone with Docker + Docker Compose can run the full stack with `make
# docker-up`. Pipelines are exposed as one-shot `docker compose run` targets
# so contributors don't have to memorize CLI invocations.

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f cricdex

docker-shell:
	docker compose exec cricdex bash

docker-test:
	docker compose run --rm cricdex uv run pytest -q

docker-ingest-cricsheet:
	docker compose run --rm cricdex uv run python scripts/ingest_cricsheet.py ingest --collection "$${COLLECTION:-recently_played_30_male}"

docker-ingest-indian-domestic:
	docker compose run --rm cricdex uv run python scripts/ingest_cricsheet.py indian-domestic

docker-ingest-people:
	docker compose run --rm cricdex uv run python scripts/ingest_people.py

docker-ingest-wikidata:
	docker compose run --rm cricdex uv run python scripts/ingest_wikidata.py

docker-scout-up:
	docker compose --profile scout up -d neo4j
	@echo "Neo4j UI on http://localhost:7474 (user neo4j / pass cricdex_dev)"

docker-scout-down:
	docker compose --profile scout stop neo4j

docker-scout-bootstrap:
	docker compose --profile scout run --rm -e NEO4J_URI=bolt://neo4j:7687 -e NEO4J_PASSWORD=cricdex_dev cricdex uv run python scripts/scout_graph.py bootstrap

docker-scout-populate:
	docker compose --profile scout run --rm -e NEO4J_URI=bolt://neo4j:7687 -e NEO4J_PASSWORD=cricdex_dev cricdex uv run python scripts/scout_graph.py populate --collection "$${COLLECTION:-ipl}"

docker-scout-rate:
	docker compose run --rm cricdex uv run python scripts/scout_rate.py --collection "$${COLLECTION:-ipl}" --advi-steps "$${STEPS:-12000}"

docker-style-twin:
	@if [ -z "$$NAME" ]; then echo 'usage: make docker-style-twin NAME="MS Dhoni" [ROLE=batter|bowler] [K=10] [COLLECTION=ipl]'; exit 2; fi
	docker compose run --rm cricdex uv run python scripts/style_twin.py "$$NAME" --role "$${ROLE:-batter}" -k "$${K:-10}" --collection "$${COLLECTION:-ipl}"

docker-ingest-rules-download:
	docker compose run --rm cricdex uv run python scripts/ingest_rules.py download

docker-ingest-rules-parse:
	docker compose run --rm cricdex uv run python scripts/ingest_rules.py parse-pdfs

docker-embed-rules:
	docker compose run --rm cricdex uv run python scripts/embed_rules.py embed

docker-query:
	@if [ -z "$$Q" ]; then echo 'usage: make docker-query Q="<your question>" [FORMATS=ipl,t20i]'; exit 2; fi
	docker compose run --rm cricdex uv run python scripts/embed_rules.py query "$$Q" --formats "$${FORMATS:-}"

docker-pressure-runs:
	docker compose run --rm cricdex uv run python scripts/compute_metrics.py pressure-runs --collection "$${COLLECTION:-recently_played_30_male}" --top-n "$${TOP_N:-50}"

docker-metrics-all:
	docker compose run --rm cricdex uv run python scripts/compute_metrics.py all --collection "$${COLLECTION:-recently_played_30_male}" --top-n "$${TOP_N:-100}"

docker-dashboard-up:
	docker compose --profile dashboard up -d dashboard
	@echo "Streamlit on http://localhost:8511"

docker-dashboard-down:
	docker compose --profile dashboard stop dashboard
	docker compose --profile dashboard rm -f dashboard

dashboard:
	uv run streamlit run src/cricdex/dashboard/app.py
