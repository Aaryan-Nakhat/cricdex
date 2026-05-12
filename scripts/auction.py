"""CLI: auction squad solver.

Examples:
    uv run python scripts/auction.py demo
    uv run python scripts/auction.py solve --csv my_pool.csv --purse 120
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import typer
from loguru import logger

from cricdex.auction import solver

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """CricDex auction CLI."""


@app.command()
def demo(
    purse: float = typer.Option(200.0, "--purse"),
    squad_size: int = typer.Option(20, "--squad-size"),
) -> None:
    pool = solver.sample_pool()
    typer.echo("=== Pool (head) ===")
    typer.echo(pool.head(10).to_pandas().to_string(index=False))
    result = solver.solve(pool, purse=purse, squad_size=squad_size)
    if not result["feasible"]:
        logger.warning(f"infeasible: {result.get('reason')}")
        raise typer.Exit(code=1)
    typer.echo(
        f"\n=== Selected squad (price {result['total_price']:.2f}, "
        f"value {result['total_value']:.2f}) ===\n"
    )
    typer.echo(result["selected"].to_pandas().to_string(index=False))


@app.command()
def solve(
    csv: Path = typer.Option(..., "--csv"),
    purse: float = typer.Option(120.0, "--purse"),
    squad_size: int = typer.Option(25, "--squad-size"),
    overseas_cap: int = typer.Option(8, "--overseas-cap"),
) -> None:
    pool = pl.read_csv(csv)
    result = solver.solve(pool, purse=purse, squad_size=squad_size, overseas_cap=overseas_cap)
    if not result["feasible"]:
        logger.warning(f"infeasible: {result.get('reason')}")
        raise typer.Exit(code=1)
    typer.echo(
        f"\n=== Selected squad (price {result['total_price']:.2f}, "
        f"value {result['total_value']:.2f}) ===\n"
    )
    typer.echo(result["selected"].to_pandas().to_string(index=False))


if __name__ == "__main__":
    app()
