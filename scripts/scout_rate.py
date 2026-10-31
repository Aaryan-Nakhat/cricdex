"""CLI: fit Bayesian opponent-adjusted batter / bowler ratings.

Example:
    uv run python scripts/scout_rate.py --collection ipl --advi-steps 12000
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl
import typer
from loguru import logger

from cricdesk.config import DATA_DIR
from cricdesk.scout.ratings import bayesian


def _attach_names(df: pl.DataFrame, db_path: Path) -> pl.DataFrame:
    # bayesian.fit already attaches unique_name; joining again wrote a duplicate `unique_name_right` column.
    if "unique_name" in df.columns or not db_path.exists():
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
    min_balls: int = typer.Option(
        0, "--min-balls", help="speed knob: fit only matchups this long (reported balls stay true)"
    ),
    advi_steps: int = typer.Option(12000, "--advi-steps"),
    seed: int = typer.Option(42, "--seed"),
    sampler: str = typer.Option(
        "advi", "--sampler", help="advi (default; checked against nuts) | nuts (logs r-hat / ESS)"
    ),
    nuts_draws: int = typer.Option(1000, "--nuts-draws"),
    nuts_chains: int = typer.Option(2, "--nuts-chains"),
    nuts_tune: int = typer.Option(500, "--nuts-tune"),
    variant: str = typer.Option(
        "v2", "--variant", help="v2 (context-adjusted, default) | legacy (the earlier model)"
    ),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df, res, _ = bayesian.fit(
        collection=collection,
        min_balls=min_balls,
        advi_steps=advi_steps,
        seed=seed,
        sampler=sampler,
        nuts_draws=nuts_draws,
        nuts_chains=nuts_chains,
        nuts_tune=nuts_tune,
        variant=variant,
        return_fit=True,
    )
    if df.is_empty():
        logger.warning("no matchups to fit")
        raise typer.Exit(code=1)
    df = _attach_names(df, bayesian.DEFAULT_DB_PATH)
    out_path = out_json or (DATA_DIR / "metrics" / f"scout_ratings_{collection}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_json(str(out_path))
    logger.info(f"wrote {out_path} ({df.height} rows)")
    # the fitted context: season / phase / innings levels, venue spread, batting-slot means
    ctx_path = out_path.with_name(f"scout_context_{collection}.json")
    ctx_path.write_text(json.dumps({"variant": variant, **res.context}, indent=1))
    logger.info(f"wrote {ctx_path}")
    rank_by = "value" if "value" in df.columns else "skill"
    top_batters = (
        df.filter((pl.col("role") == "batter") & (pl.col("balls") >= 200))
        .sort(rank_by, descending=True)
        .head(15)
    )
    top_bowlers = (
        df.filter((pl.col("role") == "bowler") & (pl.col("balls") >= 200))
        .sort(rank_by, descending=True)
        .head(15)
    )
    typer.echo(f"\n=== Top 15 batters by {rank_by} ===")
    typer.echo(top_batters.to_pandas().to_string(index=False))
    typer.echo(f"\n=== Top 15 bowlers by {rank_by} ===")
    typer.echo(top_bowlers.to_pandas().to_string(index=False))


if __name__ == "__main__":
    app()
