"""CLI: compile the CricDex daily digest into Markdown.

Examples:
    uv run python scripts/newsletter.py --collection ipl
    uv run python scripts/newsletter.py --collection ipl --no-report
"""

from __future__ import annotations

import datetime as dt

import typer
from loguru import logger

from cricdex.newsletter import digest

app = typer.Typer(add_completion=False)


@app.command()
def compile(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    as_of: str = typer.Option("", "--as-of", help="YYYY-MM-DD; default = today"),
    include_match_report: bool = typer.Option(True, "--report/--no-report"),
) -> None:
    when = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    path = digest.compile(
        collection=collection, as_of=when, include_match_report=include_match_report
    )
    logger.info(f"wrote {path}")
    typer.echo(path.read_text())


if __name__ == "__main__":
    app()
