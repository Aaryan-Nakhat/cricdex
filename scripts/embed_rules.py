"""CLI: embed parsed rule clauses + run ad-hoc rule queries.

Examples:
    uv run python scripts/embed_rules.py embed
    uv run python scripts/embed_rules.py query "impact player rule" --formats ipl
"""

from __future__ import annotations

import typer
from loguru import logger

from cricdex.rules.embed import embed_all
from cricdex.rules.qa import answer

app = typer.Typer(add_completion=False)


@app.command()
def embed() -> None:
    n = embed_all()
    logger.info(f"embedded {n} clauses")


@app.command()
def query(
    q: str,
    formats: str = typer.Option(
        "", "--formats", help="Comma-sep formats (test, odi, t20i, ipl, hundred, ...)"
    ),
    top_k: int = typer.Option(8, "--top-k"),
) -> None:
    fmts = [f.strip() for f in formats.split(",") if f.strip()] or None
    result = answer(q, formats=fmts, top_k=top_k)
    typer.echo("=== ANSWER ===")
    typer.echo(result["answer"])
    typer.echo("\n=== CITATIONS ===")
    for src, law in result["citations"]:
        typer.echo(f"  [{src} §{law}]")


if __name__ == "__main__":
    app()
