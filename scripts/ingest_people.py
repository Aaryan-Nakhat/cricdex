"""CLI: download + load Cricsheet's People Register.

Usage:
    uv run python scripts/ingest_people.py
    uv run python scripts/ingest_people.py --force         # refresh CSVs
    uv run python scripts/ingest_people.py --db custom.duckdb
"""

from __future__ import annotations

from pathlib import Path

import typer
from loguru import logger

from cricdex.scout.ingest import people_register

app = typer.Typer(add_completion=False)


@app.command()
def ingest(
    out_dir: Path | None = typer.Option(None, "--out"),
    db_path: Path | None = typer.Option(None, "--db"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    db = db_path or people_register.DEFAULT_DB_PATH
    n_people, n_names = people_register.ingest(out_dir=out_dir, db_path=db, force=force)
    logger.info(f"people={n_people:,} people_names={n_names:,}")


if __name__ == "__main__":
    app()
