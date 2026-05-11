"""CLI: compute novel CricMetrics over an ingested Cricsheet collection.

Examples:
    uv run python scripts/compute_metrics.py pressure-runs \\
        --collection recently_played_30_male
    uv run python scripts/compute_metrics.py pressure-runs \\
        --collection ipl --top-n 50 --json data/metrics/pressure_runs_ipl.json
"""

from __future__ import annotations

from pathlib import Path

import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.metrics import batter as batter_metrics

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """CricMetrics CLI — novel batter / bowler / composite ratings."""


@app.command("pressure-runs")
def pressure_runs_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    pressure_multiplier: float = typer.Option(
        batter_metrics.DEFAULT_PRESSURE_MULTIPLIER, "--multiplier"
    ),
    min_balls: int = typer.Option(batter_metrics.DEFAULT_MIN_BALLS_FACED, "--min-balls"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json", help="Optional JSON output path"),
    db_path: Path | None = typer.Option(None, "--db"),
) -> None:
    df = batter_metrics.pressure_runs(
        collection=collection,
        db_path=db_path or batter_metrics.DEFAULT_DB_PATH,
        pressure_multiplier=pressure_multiplier,
        min_balls_faced=min_balls,
        top_n=top_n,
    )

    typer.echo(f"\n=== Pressure Runs — {collection} (top {top_n}) ===\n")
    typer.echo(df.to_pandas().to_string(index=False))

    if out_json is not None:
        out_path = out_json
    else:
        out_path = DATA_DIR / "metrics" / f"pressure_runs_{collection}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # polars.write_json handles DuckDB-derived Decimals + nulls cleanly,
    # unlike stdlib json on raw .to_dicts() output.
    df.write_json(str(out_path))
    logger.info(f"wrote {out_path}")


if __name__ == "__main__":
    app()
