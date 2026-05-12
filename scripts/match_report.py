"""CLI: generate an auto-written match report Markdown for a Cricsheet match_id.

Examples:
    uv run python scripts/match_report.py 1473489 --collection ipl
"""

from __future__ import annotations

import typer
from loguru import logger

from cricdex.reports import match_report

app = typer.Typer(add_completion=False)


@app.command()
def generate(
    match_id: str,
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    path = match_report.generate(match_id=match_id, collection=collection)
    logger.info(f"wrote {path}")
    typer.echo(path.read_text())


if __name__ == "__main__":
    app()
