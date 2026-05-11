"""CLI: pull cricket-player enrichment from Wikidata into DuckDB.

Single SPARQL call (~10-20 MB JSON). Re-run as needed; the table is
fully replaced.

Usage:
    uv run python scripts/ingest_wikidata.py
"""

from __future__ import annotations

from pathlib import Path

import typer
from loguru import logger

from cricdex.scout.ingest import wikidata

app = typer.Typer(add_completion=False)


@app.command()
def ingest(db_path: Path | None = typer.Option(None, "--db")) -> None:
    n = wikidata.ingest(db_path=db_path or wikidata.DEFAULT_DB_PATH)
    logger.info(f"wikidata_players rows: {n:,}")


if __name__ == "__main__":
    app()
