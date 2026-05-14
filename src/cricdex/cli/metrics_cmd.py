"""`cricdex leaderboard <metric>` — rich-rendered novel-metric leaderboards.

Renderer mirrors the Streamlit Leaderboards page: explainer panel +
per-metric "what it captures" line + pruned headline columns.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import EXIT_MISSING_DATA, die
from cricdex.config import DATA_DIR

# Metric slug → (primary sort column, primary key column). Matches
# data/metrics/<slug>_<col>.json emitted by compute_metrics.py.
METRICS: dict[str, tuple[str, str]] = {
    "ngi": ("ngi_per_match", "name"),
    "pressure_runs": ("pressure_sr_per_100_balls", "batter"),
    "intent_curve": ("intent", "batter"),
    "recoverability": ("recoverability", "batter"),
    "counter_attack": ("counter_attack", "batter"),
    "boundary_dependency": ("boundary_dependency", "batter"),
    "sticky_dot_pressure": ("wicket_rate_pct", "bowler"),
    "wicket_quality": ("wicket_quality", "bowler"),
    "phase_dilation": ("phase_dilation", "batter"),
    "setting_tax": ("setting_tax", "batter"),
}


def leaderboard(
    metric: str = typer.Argument(..., help=f"one of: {sorted(METRICS)}"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top: int = typer.Option(
        15,
        "--top",
        "-n",
        help="How many top-scoring rows to render. Higher = fuller list.",
    ),
    output_json: bool = typer.Option(False, "--json", help="emit raw JSON for piping"),
) -> None:
    if metric not in METRICS:
        die(f"unknown metric — choose from {sorted(METRICS)}")
    sort_col, primary_key = METRICS[metric]
    path = Path(DATA_DIR) / "metrics" / f"{metric}_{collection}.json"
    if not path.exists():
        die(
            f"no leaderboard at {path}",
            code=EXIT_MISSING_DATA,
            hint=f"run `cricdex data ingest metrics -c {collection}`",
        )
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        rows = rows.get("rows", []) if isinstance(rows, dict) else []
    rows = sorted(rows, key=lambda r: r.get(sort_col, 0) or 0, reverse=True)[:top]

    if output_json:
        typer.echo(json.dumps(rows, indent=2))
        return

    pretty = metric.replace("_", " ").title()
    _render.header(f"{pretty} — top {top}", subtitle=f"collection: {collection}")
    _render.intro_panel(_copy.LEADERBOARD_INTRO, title="Leaderboards")

    hint = _copy.METRIC_HINTS.get(metric)
    if hint:
        _render.intro_panel(hint, title=f"What this captures — {pretty}")

    # Trim to a useful preview: primary key + sort col + 3-4 extras.
    if rows:
        # Sparkline over the sort_col values gives an at-a-glance
        # distribution shape (steep top tail vs flat plateau etc).
        spark_vals = [r.get(sort_col) or 0 for r in rows]
        spark = _render.sparkline(spark_vals)
        if spark:
            from cricdex.cli._shared import console as _c

            _c().print(f"[dim]{sort_col} shape:[/dim] [cyan]{spark}[/cyan]")
        extras = [k for k in rows[0].keys() if k not in {primary_key, sort_col}][:4]
        cols = [primary_key, sort_col, *extras]
        pruned = [{c: r.get(c) for c in cols} for r in rows]
        _render.pretty_table(
            pruned,
            columns=cols,
            column_styles={primary_key: "bold cyan", sort_col: "bold"},
        )
    _render.footnote(
        f"Path: {path.relative_to(Path.cwd()) if path.is_absolute() and Path.cwd() in path.parents else path}  "
        f"·  refresh with `cricdex data ingest metrics -c {collection} --force`"
    )
