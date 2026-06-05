"""`cricdex form <metric>` — recent-window form vs career baseline.

Each metric recomputed over the recent window (last 1y, else last 3y) and
compared against career. Positive form Δ = improving (direction-corrected for
'lower is better' metrics). Reads the same exported leaderboards as the web.
"""

from __future__ import annotations

import typer

from cricdex.cli import _render
from cricdex.cli._shared import console, die
from cricdex.common import filters as cf
from cricdex.common.metrics import METRIC_BY_SLUG


def form(
    metric: str = typer.Argument("ngi", help=f"one of: {sorted(METRIC_BY_SLUG)}"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top: int = typer.Option(15, "--top", "-n"),
) -> None:
    if metric not in METRIC_BY_SLUG:
        die(f"unknown metric — choose from {sorted(METRIC_BY_SLUG)}")
    m = METRIC_BY_SLUG[metric]

    def _load(window: str) -> list[dict]:
        try:
            return cf.load_leaderboard(collection, metric, window)
        except FileNotFoundError:
            return []

    recent_win = next((w for w in ("last1y", "last3y") if _load(w)), None)
    career = _load("all")
    if recent_win is None or not career:
        die(
            f"no recent window for {metric} in {collection}",
            hint="export a last-1y/3y leaderboard (`data ingest metrics` then export_site.py)",
        )

    val, name_col = m.sort_col, m.name_col
    career_by = {r[name_col]: r for r in career if r.get(name_col) is not None}
    rows = []
    for rr in _load(recent_win):
        nm = rr.get(name_col)
        cr = career_by.get(nm)
        if cr is None or rr.get(val) is None or cr.get(val) is None:
            continue
        cv, rv = float(cr[val]), float(rr[val])
        mv = (rv - cv) if m.higher_is_better else (cv - rv)
        rows.append(
            {"player": nm, "career": round(cv, 2), "recent": round(rv, 2), "form_Δ": round(mv, 2)}
        )
    if not rows:
        die("no players appear in both the career and recent boards")

    rows.sort(key=lambda r: r["form_Δ"], reverse=True)
    _render.header(
        f"Form — {m.name}",
        subtitle=f"{cf.WINDOW_LABELS[recent_win].lower()} vs career · {collection}",
    )
    if not m.higher_is_better:
        console().print(
            "[dim]lower-is-better metric → form Δ sign-flipped (positive = improving)[/dim]"
        )
    _render.pretty_table(rows[:top], title="Heating up ▲", column_styles={"player": "bold cyan"})
    _render.pretty_table(
        list(reversed(rows))[:top], title="Cooling down ▼", column_styles={"player": "bold cyan"}
    )
    _render.footnote("Recent window vs career, from the same exported leaderboards.")
