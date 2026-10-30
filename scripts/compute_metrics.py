"""CLI: compute novel CricMetrics over an ingested Cricsheet collection.

Each subcommand writes the leaderboard to
`data/metrics/<metric>_<collection>.json` and also prints a tabular
view to stdout.

Examples:
    uv run python scripts/compute_metrics.py pressure-runs --collection ipl
    uv run python scripts/compute_metrics.py intent-curve --collection ipl
    uv run python scripts/compute_metrics.py dot-ball-recovery --collection ipl
    uv run python scripts/compute_metrics.py counter-attack --collection ipl
    uv run python scripts/compute_metrics.py boundary-dependency --collection ipl
    uv run python scripts/compute_metrics.py pressure-conversion --collection ipl
    uv run python scripts/compute_metrics.py all --collection ipl
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl
import typer
from loguru import logger

from cricdex.common.sql import is_window
from cricdex.config import DATA_DIR
from cricdex.metrics import batter as batter_metrics
from cricdex.metrics import bowler as bowler_metrics
from cricdex.metrics import bowler_wicket_quality, provenance, splits
from cricdex.metrics import fielding as fielding_metrics

DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """CricMetrics CLI — novel batter / bowler / composite ratings."""


def _emit(df: pl.DataFrame, metric: str, collection: str, out_json: Path | None) -> Path:
    typer.echo(f"\n=== {metric} — {collection} ({df.height} rows) ===\n")
    typer.echo(df.to_pandas().to_string(index=False))
    out_path = out_json or (DATA_DIR / "metrics" / f"{metric}_{collection}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # SQL SUMs come back as HUGEINT / Decimal, which write_json stores as strings: write numbers
    df = df.with_columns(
        pl.col(c).cast(pl.Int64 if dt.scale == 0 else pl.Float64)
        if isinstance(dt, pl.Decimal)
        else pl.col(c).cast(pl.Int64)
        if dt == pl.Int128
        else pl.col(c)
        for c, dt in df.schema.items()
    )
    df.write_json(str(out_path))
    if out_json is None:
        # what it was computed from, so the export can refuse it once the data or code moves on
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            provenance.write_stamp(out_path, provenance.fingerprint(con, collection, metric))
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


@app.command("dot-ball-recovery")
def dot_ball_recovery_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    min_dots: int = typer.Option(100, "--min-dots"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.dot_ball_recovery(
        collection=collection,
        min_dot_balls=min_dots,
        top_n=top_n,
    )
    _emit(df, "dot_ball_recovery", collection, out_json)


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


@app.command("crease-longevity")
def crease_longevity_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    min_dismissals: int = typer.Option(10, "--min-dismissals"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.crease_longevity(
        collection=collection, min_dismissals=min_dismissals, top_n=top_n
    )
    _emit(df, "crease_longevity", collection, out_json)


@app.command("slow-start-cost")
def slow_start_cost_cmd(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    min_career_balls: int = typer.Option(200, "--min-career-balls"),
    min_setting_balls: int = typer.Option(50, "--min-setting-balls"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    df = batter_metrics.slow_start_cost(
        collection=collection,
        min_career_balls=min_career_balls,
        min_setting_balls=min_setting_balls,
        top_n=top_n,
    )
    _emit(df, "slow_start_cost", collection, out_json)


def _warn_if_no_ratings(collection: str) -> None:
    """Wicket Quality weights each wicket by the batter's fitted scout rating. Without the ratings
    file its board comes out empty, so say so (fit them first: `scripts/scout_rate.py`)."""
    path = DATA_DIR / "metrics" / f"scout_ratings_{collection}.json"
    if not path.exists():
        logger.warning(
            f"{path} not found — the Wicket Quality board will be empty. "
            f"Run `scripts/scout_rate.py --collection {collection}` before compute_metrics."
        )


@app.command("wicket-quality")
def wicket_quality_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    min_wickets: int = typer.Option(15, "--min-wickets"),
    top_n: int = typer.Option(50, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    _warn_if_no_ratings(collection)
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
        f"log_loss={res['log_loss']:.4f}  ece={res['ece']:.4f}  on {res['n_val_balls']:,} balls "
        f"from {res['n_val_matches']} held-out matches "
        f"({res['n_train_matches']} train matches, {res['n_balls']:,} balls scored out of fold)"
    )


@app.command("ngi-diagnostics")
def ngi_diagnostics_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    """Before / after numbers for the win-probability model: isotonic vs smooth calibration, with
    vs without monotone constraints, with vs without the era feature (latest season held out) and
    in-sample vs out-of-fold NGI."""
    import json

    from cricdex.metrics import ngi

    res = ngi.diagnose(collection)
    text = json.dumps(res, indent=2)
    typer.echo(text)
    path = out_json or (DATA_DIR / "metrics" / f"ngi_diagnostics_{collection}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@app.command("pressure-conversion")
def pressure_conversion_cmd(
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
    df = bowler_metrics.pressure_conversion(
        collection=collection,
        consecutive_dot_threshold=threshold,
        min_pressure_balls=min_balls,
        top_n=top_n,
    )
    _emit(df, "pressure_conversion", collection, out_json)


def _window_value(collection: str, by_window: dict[str, int], default: int) -> int:
    """A threshold for a windowed collection: last1y / last3y have their own, an era window (a few
    seasons, `<col>_era_<key>`) uses the last-3-years one, the whole collection the default."""
    for suf, v in by_window.items():
        if collection.endswith(f"_{suf}"):
            return v
    if is_window(collection):
        return by_window.get("last3y", default)
    return default


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
    # Intent-Curve gates on balls-per-bucket (default 200, tuned for all-time).
    # Over a short time window that bar is unreachable — a 1-yr collection has
    # ~14 innings, so even the 0-5 bucket tops out ~70 balls — which left
    # intent_curve.last1y empty. Scale the threshold down for the windowed
    # collections (the all-time board keeps 200, so the web base is unchanged).
    _window_bucket_min = {"last1y": 25, "last3y": 80}
    intent_bucket_min = _window_value(collection, _window_bucket_min, 200)
    _emit(
        batter_metrics.pressure_runs(collection=collection, top_n=top_n),
        "pressure_runs",
        collection,
        None,
    )
    _emit(
        batter_metrics.intent_curve(
            collection=collection, top_n=top_n * 6, min_balls_in_bucket=intent_bucket_min
        ),
        "intent_curve",
        collection,
        None,
    )
    _emit(
        batter_metrics.dot_ball_recovery(collection=collection, top_n=top_n),
        "dot_ball_recovery",
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
    # the four context splits of 2026-10-29 (metrics/splits.py; each passed the split-half test that
    # Pressure Conversion failed), with lower ball minimums for the short windows
    _emit(
        splits.dot_avoidance(
            collection=collection,
            top_n=top_n,
            min_balls=_window_value(collection, {"last1y": 60, "last3y": 100}, 150),
        ),
        "dot_avoidance",
        collection,
        None,
    )
    _emit(
        splits.pace_spin(
            collection=collection,
            top_n=top_n,
            min_balls=_window_value(collection, {"last1y": 40, "last3y": 70}, 100),
        ),
        "pace_spin",
        collection,
        None,
    )
    _emit(
        splits.finisher(
            collection=collection,
            top_n=top_n,
            min_balls=_window_value(collection, {"last1y": 15, "last3y": 25}, 40),
        ),
        "finisher",
        collection,
        None,
    )
    _emit(
        splits.hand_split(
            collection=collection,
            top_n=top_n,
            min_balls=_window_value(collection, {"last1y": 36, "last3y": 60}, 90),
        ),
        "hand_split",
        collection,
        None,
    )
    from cricdex.metrics import ngi as _ngi

    # NGI is per-match, so a player with one great game would top the board — keep a matches floor
    # (lower for the time windows, which hold far fewer games).
    _ngi_min_matches = {"last1y": 3, "last3y": 6}
    ngi_min = _window_value(collection, _ngi_min_matches, 25)
    _ngi_career = _ngi.compute(collection=collection)["career"]
    if not _ngi_career.is_empty():
        _ngi_career = _ngi_career.filter(pl.col("matches") >= ngi_min)
    _emit(
        _ngi_career.head(top_n),
        "ngi",
        collection,
        None,
    )
    _warn_if_no_ratings(collection)
    _emit(
        bowler_wicket_quality.wicket_quality(collection=collection, top_n=top_n),
        "wicket_quality",
        collection,
        None,
    )
    _emit(
        batter_metrics.crease_longevity(collection=collection, top_n=top_n),
        "crease_longevity",
        collection,
        None,
    )
    _emit(
        batter_metrics.slow_start_cost(collection=collection, top_n=top_n),
        "slow_start_cost",
        collection,
        None,
    )
    _emit(fielding_metrics.keeping(collection=collection, top_n=top_n), "keeping", collection, None)
    _emit(
        fielding_metrics.fielding(collection=collection, top_n=top_n), "fielding", collection, None
    )


@app.command("keeping")
def keeping_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top_n: int = typer.Option(500, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    _emit(
        fielding_metrics.keeping(collection=collection, top_n=top_n),
        "keeping",
        collection,
        out_json,
    )


@app.command("fielding")
def fielding_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top_n: int = typer.Option(500, "--top-n"),
    out_json: Path | None = typer.Option(None, "--json"),
) -> None:
    _emit(
        fielding_metrics.fielding(collection=collection, top_n=top_n),
        "fielding",
        collection,
        out_json,
    )


if __name__ == "__main__":
    app()
