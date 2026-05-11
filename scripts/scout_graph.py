"""CLI: bootstrap + populate the scout Neo4j graph.

Examples:
    uv run python scripts/scout_graph.py bootstrap
    uv run python scripts/scout_graph.py populate --collection ipl
"""

from __future__ import annotations

from pathlib import Path

import typer
from loguru import logger

from cricdex.scout.graph import schema, writer

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Scout Neo4j graph CLI."""


@app.command("bootstrap")
def bootstrap_cmd() -> None:
    schema.bootstrap()
    logger.info("schema constraints + indexes ensured")


@app.command("populate")
def populate_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    db_path: Path | None = typer.Option(None, "--db"),
) -> None:
    summary = writer.populate(
        collection=collection,
        db_path=db_path or writer.DEFAULT_DB_PATH,
    )
    logger.info(f"done: {summary}")


if __name__ == "__main__":
    app()
