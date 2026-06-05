"""`cricdex matchups <name>` — batter vs bowler head-to-heads + pace/spin splits.

Reads the SAME exported `matchups/<cid>.json` the web Matchups page does, so the
terminal output matches the live site.
"""

from __future__ import annotations

import json

import typer

from cricdex.cli import _render
from cricdex.cli._shared import EXIT_MISSING_DATA, console, die, resolve_or_die
from cricdex.web_parity.loader import SITE_DATA


def _cid_for(collection: str, name: str) -> str | None:
    path = SITE_DATA / collection / "players.json"
    if not path.exists():
        return None
    for p in json.loads(path.read_text()):
        if p.get("name") == name:
            return p.get("cricsheet_id")
    return None


def matchups(
    name: str = typer.Argument(..., help="player (fuzzy-matched)"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top: int = typer.Option(15, "--top", "-n", help="rows per head-to-head table"),
    output_json: bool = typer.Option(False, "--json", help="emit raw JSON for piping"),
) -> None:
    name = resolve_or_die(name, collection=collection)
    cid = _cid_for(collection, name)
    if cid is None:
        die(f"no exported player matching {name!r} in {collection}", code=EXIT_MISSING_DATA)
    path = SITE_DATA / collection / "matchups" / f"{cid}.json"
    if not path.exists():
        die(
            f"no matchup data for {name} (needs enough balls faced/bowled)",
            code=EXIT_MISSING_DATA,
            hint="run `uv run python scripts/export_site.py`",
        )
    data = json.loads(path.read_text())
    if output_json:
        typer.echo(json.dumps(data, indent=2))
        return

    _render.header(f"Matchups — {name}", subtitle=f"collection: {collection}")

    splits = data.get("splits") or {}
    seam, spin = splits.get("vs_seam"), splits.get("vs_spin")
    if seam or spin:
        srows = []
        for label, s in (("pace", seam), ("spin", spin)):
            if s:
                srows.append(
                    {
                        "vs": label,
                        "balls": s["balls"],
                        "runs": s["runs"],
                        "sr": s["sr"],
                        "out_rate%": s["out_rate"],
                    }
                )
        _render.pretty_table(srows, title="Pace vs spin", column_styles={"vs": "bold cyan"})
        if seam and spin:
            weaker = (
                "pace" if seam["sr"] < spin["sr"] else "spin" if spin["sr"] < seam["sr"] else None
            )
            if weaker:
                console().print(f"[yellow]Weaker against {weaker} (lower strike rate).[/yellow]")

    bat = data.get("as_batter") or []
    if bat:
        _render.pretty_table(
            [
                {
                    "bowler": r["bowler"],
                    "balls": r["balls"],
                    "runs": r["runs"],
                    "sr": r["sr"],
                    "dot%": r["dot_pct"],
                    "outs": r["outs"],
                }
                for r in bat[:top]
            ],
            title="As batter — opponents faced",
            column_styles={"bowler": "bold cyan"},
        )

    bowl = data.get("as_bowler") or []
    if bowl:
        _render.pretty_table(
            [
                {
                    "batter": r["batter"],
                    "balls": r["balls"],
                    "runs": r["runs"],
                    "sr_conceded": r["sr"],
                    "dot%": r["dot_pct"],
                    "wkts": r["outs"],
                }
                for r in bowl[:top]
            ],
            title="As bowler — batters faced",
            column_styles={"batter": "bold cyan"},
        )

    if not bat and not bowl:
        console().print("[dim]No qualifying head-to-heads.[/dim]")
    _render.footnote("Same exported matchups JSON as the web app.")
