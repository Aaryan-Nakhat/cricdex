"""CLI: find the closest style-twins of a player by k-NN over CricMetrics.

Examples:
    uv run python scripts/style_twin.py "MS Dhoni" --collection ipl
    uv run python scripts/style_twin.py "JJ Bumrah" --role bowler -k 15
"""

from __future__ import annotations

import typer
from loguru import logger

from cricdex.scout.search import style_twin as twin

app = typer.Typer(add_completion=False)


@app.command()
def find(
    name: str = typer.Argument(..., help="Player unique_name (e.g. 'MS Dhoni')"),
    role: str = typer.Option("batter", "--role", help="batter | bowler"),
    k: int = typer.Option(10, "-k", "--top-k"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    df = twin.style_twin(name, role=role, k=k, collection=collection)
    if df.is_empty():
        logger.warning("no neighbours — collection metrics may be missing")
        raise typer.Exit(code=1)
    typer.echo(f"\n=== Style-twins of {name} ({role}, {collection}, top {k}) ===\n")
    typer.echo(df.to_pandas().to_string(index=False))


if __name__ == "__main__":
    app()
