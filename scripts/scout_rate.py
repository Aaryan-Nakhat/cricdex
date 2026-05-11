"""CLI: fit Bayesian opponent-adjusted batter / bowler ratings.

Example:
    uv run python scripts/scout_rate.py --collection ipl --advi-steps 12000
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl
import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.scout.ratings import bayesian


def _attach_names(df: pl.DataFrame, db_path: Path) -> pl.DataFrame:
    if not db_path.exists():
        return df
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "people" not in tables:
            return df
        people = con.execute("SELECT identifier AS cricsheet_id, unique_name FROM people").pl()
    return df.join(people, on="cricsheet_id", how="left")


app = typer.Typer(add_completion=False)


@app.command()
def fit(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    min_balls: int = typer.Option(6, "--min-balls"),
    advi_steps: int = typer.Option(12000, "--advi-steps"),
    seed: int = typer.Option(42, "--seed"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = bayesian.fit(
        collection=collection,
        min_balls=min_balls,
        advi_steps=advi_steps,
        seed=seed,
    )
    if df.is_empty():
        logger.warning("no edges met the min_balls filter — nothing to fit")
        raise typer.Exit(code=1)
    df = _attach_names(df, bayesian.DEFAULT_DB_PATH)
    out_path = out_json or (DATA_DIR / "metrics" / f"scout_ratings_{collection}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_json(str(out_path))
    logger.info(f"wrote {out_path} ({df.height} rows)")
    top_batters = (
        df.filter((pl.col("role") == "batter") & (pl.col("balls") >= 200))
        .sort("skill", descending=True)
        .head(15)
    )
    top_bowlers = (
        df.filter((pl.col("role") == "bowler") & (pl.col("balls") >= 200))
        .sort("skill", descending=True)
        .head(15)
    )
    typer.echo("\n=== Top 15 batters by skill ===")
    typer.echo(top_batters.to_pandas().to_string(index=False))
    typer.echo("\n=== Top 15 bowlers by skill ===")
    typer.echo(top_bowlers.to_pandas().to_string(index=False))


if __name__ == "__main__":
    app()
