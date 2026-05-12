"""CLI: download a Cricsheet collection, write Parquet, load into DuckDB.

Usage:
    uv run python scripts/ingest_cricsheet.py --collection recently_played_30_male
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.scout.ingest import cricsheet

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Cricsheet ETL — single collection or Indian-domestic aggregator."""


def _load_to_duckdb(matches_path: Path, balls_path: Path, collection: str, db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    safe = collection.replace("-", "_")
    con.execute(
        f"CREATE OR REPLACE TABLE matches_{safe} AS SELECT * FROM read_parquet('{matches_path}')"
    )
    con.execute(
        f"CREATE OR REPLACE TABLE balls_{safe} AS SELECT * FROM read_parquet('{balls_path}')"
    )
    con.close()


@app.command()
def ingest(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    out: Path | None = typer.Option(None, "--out"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    base = out or (DATA_DIR / "cricsheet")
    raw_dir = base / "raw"
    extracted_dir = base / "extracted"
    parquet_dir = base / "parquet"
    db_path = base / "cricsheet.duckdb"

    zip_path = cricsheet.download(collection, raw_dir, force=force)
    out_extracted = cricsheet.extract(zip_path, extracted_dir)
    matches, balls = cricsheet.parse_collection(out_extracted)
    m_path, b_path = cricsheet.write_parquet(matches, balls, parquet_dir, collection)
    _load_to_duckdb(m_path, b_path, collection, db_path)
    logger.info(f"duckdb loaded: {db_path}")


@app.command("indian-domestic")
def indian_domestic(
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Download all 35 Indian state-team zips, dedupe by match_id, and
    ingest as a single `indian_domestic_male` collection."""
    base = out or (DATA_DIR / "cricsheet")
    raw_dir = base / "raw"
    extracted_dir = base / "extracted"
    parquet_dir = base / "parquet"
    db_path = base / "cricsheet.duckdb"

    merged_dir = cricsheet.aggregate_indian_domestic(raw_dir, extracted_dir)
    matches, balls = cricsheet.parse_collection(merged_dir)
    m_path, b_path = cricsheet.write_parquet(matches, balls, parquet_dir, "indian_domestic_male")
    _load_to_duckdb(m_path, b_path, "indian_domestic_male", db_path)
    logger.info(
        f"duckdb loaded: {db_path} (indian_domestic_male — "
        f"{len(matches)} matches, {len(balls)} balls)"
    )


if __name__ == "__main__":
    app()
