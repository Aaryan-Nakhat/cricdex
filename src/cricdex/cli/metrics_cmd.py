"""`cricdex leaderboard <metric>` — rich-rendered novel-metric leaderboards."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cricdex.cli._shared import EXIT_MISSING_DATA, die, render_table
from cricdex.config import DATA_DIR

# Metric slug → primary sort column. Matches the data/metrics/<slug>_<col>.json
# emitted by scripts/compute_metrics.py / cricdex data ingest metrics.
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
    top: int = typer.Option(15, "--top", "-n"),
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

    # Trim to a useful preview: primary key + sort col + 3-4 extras.
    extras = [k for k in rows[0].keys() if k not in {primary_key, sort_col}][:4]
    cols = [primary_key, sort_col, *extras]
    pruned = [{c: r.get(c) for c in cols} for r in rows]
    render_table(pruned, title=f"{metric} top-{top} ({collection})")
