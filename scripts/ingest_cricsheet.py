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

app = typer.Typer(add_completion=False)


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

    con = duckdb.connect(str(db_path))
    safe = collection.replace("-", "_")
    con.execute(f"CREATE OR REPLACE TABLE matches_{safe} AS SELECT * FROM read_parquet('{m_path}')")
    con.execute(f"CREATE OR REPLACE TABLE balls_{safe} AS SELECT * FROM read_parquet('{b_path}')")
    con.close()
    logger.info(f"duckdb loaded: {db_path}")


if __name__ == "__main__":
    app()
