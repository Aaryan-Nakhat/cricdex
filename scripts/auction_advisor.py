"""CLI: auction strategy advisor — pick budget-fit replacements.

Examples:
    uv run python scripts/auction_advisor.py "JJ Bumrah" --budget 18 --role bowler -n 5
    uv run python scripts/auction_advisor.py "V Kohli" --budget 25 --role batter -n 10
"""

from __future__ import annotations

import typer
from loguru import logger

from cricdex.auction import advisor

app = typer.Typer(add_completion=False)


@app.command()
def recommend(
    target: str = typer.Argument(..., help="unavailable player's unique_name"),
    budget: float = typer.Option(..., "--budget", help="remaining purse (cr)"),
    role: str | None = typer.Option(
        None, "--role", help="bowler|batter|all_rounder; default = auto from target"
    ),
    n: int = typer.Option(5, "-n", "--top-n"),
    min_last_match: str = typer.Option(
        "2023-01-01", "--min-last-match", help="YYYY-MM-DD active-after filter"
    ),
) -> None:
    df = advisor.recommend_substitutes(
        target,
        budget=budget,
        role=role,
        n=n,
        min_last_match_date=min_last_match,
    )
    if df.is_empty():
        logger.warning(
            "No affordable graph-similar candidates. Try widening filters or "
            "checking the target's unique_name (case sensitive)."
        )
        raise typer.Exit(code=1)
    typer.echo(f"Top-{n} substitutes for {target} (budget {budget:.1f} cr):")
    typer.echo(df.to_pandas().to_string(index=False))


if __name__ == "__main__":
    app()
