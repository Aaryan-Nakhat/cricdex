"""`cricdex aging` — performance vs age curves.

Reads the SAME exported `aging.json` the web Aging page does.
"""

from __future__ import annotations

import json

import typer

from cricdex.cli import _render
from cricdex.cli._shared import EXIT_MISSING_DATA, console, die
from cricdex.web_parity.loader import SITE_DATA

_VALID = {"batting": ("sr", "average"), "bowling": ("economy", "strike_rate")}


def aging(
    role: str = typer.Option("batting", "--role", help="batting | bowling"),
    metric: str = typer.Option(
        "", "--metric", help="sr/average (bat) · economy/strike_rate (bowl)"
    ),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    if role not in _VALID:
        die("--role must be batting or bowling")
    path = SITE_DATA / collection / "aging.json"
    if not path.exists():
        die(
            f"no aging.json at {path}",
            code=EXIT_MISSING_DATA,
            hint="run `uv run python scripts/export_site.py`",
        )
    data = json.loads(path.read_text())
    curve = data.get(role) or []
    if output_json:
        typer.echo(json.dumps(curve, indent=2))
        return
    if not curve:
        die(f"no aging data for {collection} (needs player dates of birth)")
    mkey = metric if metric in _VALID[role] else _VALID[role][0]

    _render.header(
        f"Aging curve — {role} {mkey}",
        subtitle=f"collection: {collection}  ·  per-age mean over player-seasons (≥60 balls)",
    )
    spark = _render.sparkline([r.get(mkey) or 0 for r in curve])
    if spark:
        console().print(f"[dim]{mkey} by age:[/dim] [cyan]{spark}[/cyan]")
    _render.pretty_table(
        [{"age": r["age"], mkey: r.get(mkey), "players": r["n"]} for r in curve],
        title=f"{role} {mkey}",
        column_styles={"age": "bold cyan"},
    )
    _render.footnote(
        "Ages from Wikidata dob (~a third of players, elite-skewed); survivorship not "
        "corrected — indicative, not definitive."
    )
