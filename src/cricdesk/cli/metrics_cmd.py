"""`cricdesk leaderboard <metric>` — rich-rendered novel-metric leaderboards.

Renderer mirrors the Streamlit Leaderboards page: explainer panel +
per-metric "what it captures" line + pruned headline columns.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cricdesk.cli import _copy, _render
from cricdesk.cli._shared import (
    EXIT_MISSING_DATA,
    catalog_view,
    coll_subtitle,
    die,
    metric_explainer,
    sort_missing_last,
)
from cricdesk.common.metrics import METRIC_BY_SLUG
from cricdesk.web_parity.loader import SITE_DATA

# Metric slug → (primary sort column, name column, higher_is_better), derived
# from the shared catalog (cricdesk.common.metrics) so the CLI can't drift from
# the web/Streamlit/TUI. Reads the SAME exported leaderboard JSON.
METRICS: dict[str, tuple[str, str, bool]] = {
    slug: (m.sort_col, m.name_col, m.higher_is_better) for slug, m in METRIC_BY_SLUG.items()
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
    sort_col, primary_key, higher = METRICS[metric]
    path = SITE_DATA / collection / "leaderboards" / f"{metric}.json"
    if not path.exists():
        die(
            f"no leaderboard at {path}",
            code=EXIT_MISSING_DATA,
            hint="run `uv run python scripts/export_site.py` (after `data ingest metrics`)",
        )
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        rows = rows.get("rows", []) if isinstance(rows, dict) else []
    rows = sort_missing_last(rows, sort_col, higher)[:top]

    if output_json:
        typer.echo(json.dumps(rows, indent=2))
        return

    m = METRIC_BY_SLUG[metric]
    pretty = m.name
    _render.header(f"{pretty} — top {top}", subtitle=coll_subtitle(collection))
    _render.intro_panel(_copy.LEADERBOARD_INTRO, title="Leaderboards")

    hint = _copy.METRIC_HINTS.get(metric) or m.one_liner
    _render.intro_panel(f"{hint}\n\n{metric_explainer(m)}", title=f"What this captures — {pretty}")

    # Trim to a useful preview: primary key + sort col + 3-4 extras.
    if rows:
        # Sparkline over the sort_col values gives an at-a-glance
        # distribution shape (steep top tail vs flat plateau etc).
        spark_vals = [r.get(sort_col) or 0 for r in rows]
        spark = _render.sparkline(spark_vals)
        if spark:
            from cricdesk.cli._shared import console as _c

            label = next((c.label for c in m.columns if c.key == sort_col), sort_col)
            _c().print(f"[dim]{label} shape:[/dim] [cyan]{spark}[/cyan]")
        pruned, cols, headline = catalog_view(rows, m)
        name_label = next((c.label for c in m.columns if c.key == primary_key), primary_key)
        _render.pretty_table(
            pruned,
            columns=cols,
            column_styles={name_label: "bold cyan", headline: "bold"},
        )
    _render.footnote(
        f"Path: {path.relative_to(Path.cwd()) if path.is_absolute() and Path.cwd() in path.parents else path}  "
        f"·  refresh with `cricdesk data ingest metrics -c {collection} --force`"
    )
