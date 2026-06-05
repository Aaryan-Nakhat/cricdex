"""`cricdex phase [powerplay|middle|death]` — phase specialists.

Reads the SAME exported `phase.json` the web Phase page does.
"""

from __future__ import annotations

import json

import typer

from cricdex.cli import _render
from cricdex.cli._shared import EXIT_MISSING_DATA, die
from cricdex.web_parity.loader import SITE_DATA

PHASES = ("powerplay", "middle", "death")


def phase(
    which: str = typer.Argument("powerplay", help=f"one of: {list(PHASES)}"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top: int = typer.Option(15, "--top", "-n"),
    output_json: bool = typer.Option(False, "--json", help="emit raw JSON for piping"),
) -> None:
    if which not in PHASES:
        die(f"unknown phase — choose from {list(PHASES)}")
    path = SITE_DATA / collection / "phase.json"
    if not path.exists():
        die(
            f"no phase.json at {path}",
            code=EXIT_MISSING_DATA,
            hint="run `uv run python scripts/export_site.py`",
        )
    board = (json.loads(path.read_text()) or {}).get(which) or {}
    if output_json:
        typer.echo(json.dumps(board, indent=2))
        return

    _render.header(f"Phase specialists — {which}", subtitle=f"collection: {collection}")
    batters = (board.get("batters") or [])[:top]
    bowlers = (board.get("bowlers") or [])[:top]
    if batters:
        _render.pretty_table(
            [
                {"batter": r["name"], "runs": r["runs"], "balls": r["balls"], "sr": r["sr"]}
                for r in batters
            ],
            title="Best strike rates",
            column_styles={"batter": "bold cyan"},
        )
    if bowlers:
        _render.pretty_table(
            [
                {
                    "bowler": r["name"],
                    "wkts": r["wickets"],
                    "balls": r["balls"],
                    "runs": r["runs"],
                    "econ": r["econ"],
                }
                for r in bowlers
            ],
            title="Tightest economies",
            column_styles={"bowler": "bold cyan"},
        )
    _render.footnote("Same exported phase.json as the web app.")
