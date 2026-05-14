"""CLI: compute novel CricMetrics over an ingested Cricsheet collection.

Each subcommand writes the leaderboard to
`data/metrics/<metric>_<collection>.json` and also prints a tabular
view to stdout.

Examples:
    uv run python scripts/compute_metrics.py pressure-runs --collection ipl
    uv run python scripts/compute_metrics.py intent-curve --collection ipl
    uv run python scripts/compute_metrics.py recoverability --collection ipl
    uv run python scripts/compute_metrics.py counter-attack --collection ipl
    uv run python scripts/compute_metrics.py boundary-dependency --collection ipl
    uv run python scripts/compute_metrics.py sticky-dots --collection ipl
    uv run python scripts/compute_metrics.py all --collection ipl
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.metrics import batter as batter_metrics
from cricdex.metrics import bowler as bowler_metrics
from cricdex.metrics import bowler_wicket_quality

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """CricMetrics CLI — novel batter / bowler / composite ratings."""


def _emit(df: pl.DataFrame, metric: str, collection: str, out_json: Path | None) -> Path:
    typer.echo(f"\n=== {metric} — {collection} ({df.height} rows) ===\n")
    typer.echo(df.to_pandas().to_string(index=False))
    out_path = out_json or (DATA_DIR / "metrics" / f"{metric}_{collection}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_json(str(out_path))
    logger.info(f"wrote {out_path}")
    return out_path


@app.command("pressure-runs")
def pressure_runs_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    pressure_multiplier: float = typer.Option(
        batter_metrics.DEFAULT_PRESSURE_MULTIPLIER, "--multiplier"
    ),
    min_balls: int = typer.Option(batter_metrics.DEFAULT_MIN_BALLS_FACED, "--min-balls"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.pressure_runs(
        collection=collection,
        pressure_multiplier=pressure_multiplier,
        min_balls_faced=min_balls,
        top_n=top_n,
    )
    _emit(df, "pressure_runs", collection, out_json)


@app.command("intent-curve")
def intent_curve_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    min_balls: int = typer.Option(200, "--min-balls"),
    top_n: int = typer.Option(300, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.intent_curve(
        collection=collection,
        min_balls_in_bucket=min_balls,
        top_n=top_n,
    )
    _emit(df, "intent_curve", collection, out_json)


@app.command("recoverability")
def recoverability_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    min_dots: int = typer.Option(100, "--min-dots"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.recoverability_index(
        collection=collection,
        min_dot_balls=min_dots,
        top_n=top_n,
    )
    _emit(df, "recoverability", collection, out_json)


@app.command("counter-attack")
def counter_attack_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    min_balls: int = typer.Option(20, "--min-balls"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.counter_attack_coefficient(
        collection=collection,
        min_partner_wickets=min_balls,
        top_n=top_n,
    )
    _emit(df, "counter_attack", collection, out_json)


@app.command("boundary-dependency")
def boundary_dependency_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    min_runs: int = typer.Option(200, "--min-runs"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.boundary_dependency(
        collection=collection,
        min_runs=min_runs,
        top_n=top_n,
    )
    _emit(df, "boundary_dependency", collection, out_json)


@app.command("phase-dilation")
def phase_dilation_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    min_dismissals: int = typer.Option(10, "--min-dismissals"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.phase_dilation(
        collection=collection, min_dismissals=min_dismissals, top_n=top_n
    )
    _emit(df, "phase_dilation", collection, out_json)


@app.command("setting-tax")
def setting_tax_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    min_career_balls: int = typer.Option(200, "--min-career-balls"),
    min_setting_balls: int = typer.Option(50, "--min-setting-balls"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.setting_tax(
        collection=collection,
        min_career_balls=min_career_balls,
        min_setting_balls=min_setting_balls,
        top_n=top_n,
    )
    _emit(df, "setting_tax", collection, out_json)


@app.command("wicket-quality")
def wicket_quality_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    min_wickets: int = typer.Option(15, "--min-wickets"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = bowler_wicket_quality.wicket_quality(
        collection=collection,
        min_wickets=min_wickets,
        top_n=top_n,
    )
    _emit(df, "wicket_quality", collection, out_json)


@app.command("ngi")
def ngi_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    min_matches: int = typer.Option(20, "--min-matches"),
    top_n: int = typer.Option(100, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    from cricdex.metrics import ngi

    res = ngi.compute(collection=collection)
    df = res["career"]
    if df.is_empty():
        typer.echo("no usable balls for this collection")
        raise typer.Exit(code=1)
    df = df.filter(__import__("polars").col("matches") >= min_matches).head(top_n)
    _emit(df, "ngi", collection, out_json)
    typer.echo(
        f"WP model — val_acc={res['val_acc']:.3f}  brier={res['brier']:.4f}  "
        f"log_loss={res['log_loss']:.4f}  on {res['n_val_balls']:,} balls "
        f"from {res['n_val_matches']} held-out matches "
        f"({res['n_train_matches']} train matches, {res['n_balls']:,} total balls)"
    )


@app.command("sticky-dots")
def sticky_dots_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    threshold: int = typer.Option(4, "--threshold"),
    min_balls: int | None = typer.Option(
        None,
        "--min-balls",
        help="Min pressure-balls. Omit to auto-pick from collection's p75 (works on small corpora).",
    ),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = bowler_metrics.sticky_dot_pressure(
        collection=collection,
        consecutive_dot_threshold=threshold,
        min_pressure_balls=min_balls,
        top_n=top_n,
    )
    _emit(df, "sticky_dot_pressure", collection, out_json)


@app.command("all")
def all_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    top_n: int = typer.Option(
        500,
        "--top-n",
        help="Per-metric row cap. Default 500 — keeps the JSON files small but big enough that Profile/Compare lookups for any reasonably-active player succeed.",
    ),
) -> None:
    """Compute every metric for a collection and dump all JSON outputs."""
    _emit(
        batter_metrics.pressure_runs(collection=collection, top_n=top_n),
        "pressure_runs",
        collection,
        None,
    )
    _emit(
        batter_metrics.intent_curve(collection=collection, top_n=top_n * 6),
        "intent_curve",
        collection,
        None,
    )
    _emit(
        batter_metrics.recoverability_index(collection=collection, top_n=top_n),
        "recoverability",
        collection,
        None,
    )
    _emit(
        batter_metrics.counter_attack_coefficient(collection=collection, top_n=top_n),
        "counter_attack",
        collection,
        None,
    )
    _emit(
        batter_metrics.boundary_dependency(collection=collection, top_n=top_n),
        "boundary_dependency",
        collection,
        None,
    )
    _emit(
        bowler_metrics.sticky_dot_pressure(collection=collection, top_n=top_n),
        "sticky_dot_pressure",
        collection,
        None,
    )
    from cricdex.metrics import ngi as _ngi

    _emit(
        _ngi.compute(collection=collection)["career"].head(top_n),
        "ngi",
        collection,
        None,
    )
    _emit(
        bowler_wicket_quality.wicket_quality(collection=collection, top_n=top_n),
        "wicket_quality",
        collection,
        None,
    )
    _emit(
        batter_metrics.phase_dilation(collection=collection, top_n=top_n),
        "phase_dilation",
        collection,
        None,
    )
    _emit(
        batter_metrics.setting_tax(collection=collection, top_n=top_n),
        "setting_tax",
        collection,
        None,
    )


if __name__ == "__main__":
    app()
