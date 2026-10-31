"""`cricdesk form <metric>` — recent-window form vs career baseline.

Each metric recomputed over the recent window (last 1y, else last 3y) and
compared against career. Positive form Δ = improving (direction-corrected for
'lower is better' metrics; a descriptive one like Boundary Dependency is noted).
Reads the same exported leaderboards as the web.
"""

from __future__ import annotations

import typer

from cricdesk.cli import _render
from cricdesk.cli._shared import coll_subtitle, console, die, form_display, form_note
from cricdesk.common import filters as cf
from cricdesk.common.metrics import METRIC_BY_SLUG


def form(
    metric: str = typer.Argument("ngi", help=f"one of: {sorted(METRIC_BY_SLUG)}"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top: int = typer.Option(15, "--top", "-n"),
    window: str = typer.Option("", "--window", "-w", help="recent window: last1y | last3y"),
    role: str = typer.Option("", "--role", help="primary_role: batter/bowler/allrounder/wk_batter"),
    bowling: str = typer.Option("", "--bowling", help="seam | spin"),
    position: str = typer.Option(
        "", "--position", help="opener/no3/middle/finisher/lower/tailender"
    ),
    activity: str = typer.Option("all", "--activity", help="all | active | retired"),
    country: str = typer.Option("", "--country", help="ISO-3, e.g. IND"),
    min_matches: int = typer.Option(0, "--min-matches", help="drop small samples"),
) -> None:
    if metric not in METRIC_BY_SLUG:
        die(f"unknown metric — choose from {sorted(METRIC_BY_SLUG)}")
    m = METRIC_BY_SLUG[metric]

    def _load(win: str) -> list[dict]:
        try:
            return cf.load_leaderboard(collection, metric, win)
        except FileNotFoundError:
            return []

    # Chosen window (if it exists), else whichever recent window is available.
    recent_win = (
        window
        if (window and _load(window))
        else next((w for w in ("last1y", "last3y") if _load(w)), None)
    )
    career = _load("all")
    if recent_win is None or not career:
        die(
            f"no recent window for {metric} in {collection}",
            hint="export a last-1y/3y leaderboard (`data ingest metrics` then export_site.py)",
        )

    filters = cf.Filters(
        min_matches=min_matches,
        role=role,
        bowling=bowling,
        position=position,
        activity=activity,
        country=country.strip(),
    )
    val, name_col = m.sort_col, m.name_col
    career_by = {r[name_col]: r for r in career if r.get(name_col) is not None}
    rows = []
    for rr in cf.apply_filters(_load(recent_win), filters):
        nm = rr.get(name_col)
        cr = career_by.get(nm)
        if cr is None or rr.get(val) is None or cr.get(val) is None:
            continue
        cv, rv = float(cr[val]), float(rr[val])
        mv = (rv - cv) if m.higher_is_better else (cv - rv)
        pct = any(c.primary and c.fmt == "pct" for c in m.columns)
        nd = 4 if pct else 2  # a pct headline keeps its precision until it's shown as a %
        rows.append(
            {
                "player": nm,
                "career": round(cv, nd),
                "recent": round(rv, nd),
                "form_Δ": round(mv, nd),
            }
        )
    if not rows:
        die("no players appear in both the career and recent boards")

    rows.sort(key=lambda r: r["form_Δ"], reverse=True)
    _render.header(
        f"Form — {m.name}",
        subtitle=f"{cf.WINDOW_LABELS[recent_win].lower()} vs career · {coll_subtitle(collection)}",
    )
    console().print(f"[dim]{form_note(m)}[/dim]")
    _render.pretty_table(
        form_display(rows[:top], m), title="Heating up ▲", column_styles={"player": "bold cyan"}
    )
    _render.pretty_table(
        form_display(list(reversed(rows))[:top], m),
        title="Cooling down ▼",
        column_styles={"player": "bold cyan"},
    )
    _render.footnote("Recent window vs career, from the same exported leaderboards.")
