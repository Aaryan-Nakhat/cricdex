.PHONY: install dev precommit lint format format-check check fix test clean api dashboard refresh \
        docker-build docker-up docker-down docker-logs docker-shell docker-test \
        docker-ingest-cricsheet docker-ingest-indian-domestic docker-ingest-people docker-ingest-wikidata \
        docker-scout-rate docker-style-twin docker-records-all docker-records-today docker-pressure-runs \
        docker-export docker-metrics-all docker-dashboard-up docker-dashboard-down

install:
	uv sync

dev:
	uv sync --all-extras --group dev
	uv run pre-commit install

precommit:
	uv run pre-commit run --all-files

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
	uv run python -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in [*pathlib.Path('.').rglob('__pycache__'), *map(pathlib.Path, ['.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'dist', 'build'])]]"

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

docker-scout-rate:
	docker compose run --rm cricdex uv run python scripts/scout_rate.py --collection "$${COLLECTION:-ipl}" --advi-steps "$${STEPS:-12000}"

docker-style-twin:
	@if [ -z "$$NAME" ]; then echo 'usage: make docker-style-twin NAME="MS Dhoni" [ROLE=batter|bowler] [K=10] [COLLECTION=ipl]'; exit 2; fi
	docker compose run --rm cricdex uv run python scripts/style_twin.py "$$NAME" --role "$${ROLE:-batter}" -k "$${K:-10}" --collection "$${COLLECTION:-ipl}"

docker-records-all:
	docker compose run --rm cricdex uv run python scripts/records.py all --collection "$${COLLECTION:-ipl}" --top-n "$${TOP_N:-25}"

docker-records-today:
	docker compose run --rm cricdex uv run python scripts/records.py today --collection "$${COLLECTION:-ipl}"

docker-pressure-runs:
	docker compose run --rm cricdex uv run python scripts/compute_metrics.py pressure-runs --collection "$${COLLECTION:-recently_played_30_male}" --top-n "$${TOP_N:-50}"

docker-export:
	docker compose run --rm cricdex uv run python scripts/export_site.py $${COLLECTION:+-c "$$COLLECTION"}

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

# Refresh one collection end to end on this machine: download → metrics → ratings → site data.
refresh:
	uv run python scripts/ingest_cricsheet.py ingest --collection "$${COLLECTION:-ipl}" --force
	uv run python scripts/compute_metrics.py all --collection "$${COLLECTION:-ipl}"
	uv run python scripts/scout_rate.py --collection "$${COLLECTION:-ipl}" --advi-steps 12000
	uv run python scripts/export_site.py -c "$${COLLECTION:-ipl}"
