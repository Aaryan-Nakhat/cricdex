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
    send_to: str = typer.Option(
        "", "--send-to", help="Comma-sep emails. If set, ships via Resend."
    ),
    subject: str = typer.Option("", "--subject"),
) -> None:
    when = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    path = digest.compile(
        collection=collection, as_of=when, include_match_report=include_match_report
    )
    logger.info(f"wrote {path}")
    typer.echo(path.read_text())
    if send_to:
        recipients = [s.strip() for s in send_to.split(",") if s.strip()]
        subj = subject or f"CricDex Digest — {collection} — {when.isoformat()}"
        digest.send_via_resend(path, to=recipients, subject=subj)


if __name__ == "__main__":
    app()
