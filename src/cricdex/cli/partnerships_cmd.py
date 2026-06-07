"""`cricdex partnerships <name>` — batter-pair stands.

Reads the SAME exported `partnerships.json` the web Partnerships page does.
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


def partnerships(
    name: str = typer.Argument(None, help="player (fuzzy-matched); omit for the best-stands board"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top: int = typer.Option(15, "--top", "-n"),
    min_runs: int = typer.Option(50, "--min-runs", help="aggregate runs for the pair"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    path = SITE_DATA / collection / "partnerships.json"
    if not path.exists():
        die(
            f"no partnerships.json at {path}",
            code=EXIT_MISSING_DATA,
            hint="run `uv run python scripts/export_site.py`",
        )
    pairs = [p for p in json.loads(path.read_text()).get("pairs", []) if p["runs"] >= min_runs]
    if output_json:
        typer.echo(json.dumps(pairs, indent=2))
        return

    if name:
        name = resolve_or_die(name, collection=collection)
        cid = _cid_for(collection, name)
        mine = sorted(
            (p for p in pairs if cid and cid in (p.get("a_cid"), p.get("b_cid"))),
            key=lambda p: p["runs"],
            reverse=True,
        )
        _render.header(f"Partnerships — {name}", subtitle=f"collection: {collection}")
        if mine:
            _render.pretty_table(
                [
                    {
                        "partner": p["b"] if p.get("a_cid") == cid else p["a"],
                        "runs": p["runs"],
                        "inns": p["innings"],
                        "best": p["best"],
                        "avg": p["avg"],
                        "sr": p["sr"],
                        "50+": p["fifties"],
                        "100+": p["hundreds"],
                    }
                    for p in mine[:top]
                ],
                title="Most productive partners",
                column_styles={"partner": "bold cyan"},
            )
        else:
            console().print(f"[dim]No partnerships ≥ {min_runs} runs for {name}.[/dim]")

    _render.header("Best partnerships (all-time)", subtitle=f"collection: {collection}")
    _render.pretty_table(
        [
            {
                "partnership": f"{p['a']} & {p['b']}",
                "runs": p["runs"],
                "inns": p["innings"],
                "best": p["best"],
                "avg": p["avg"],
                "sr": p["sr"],
                "100+": p["hundreds"],
            }
            for p in pairs[:top]
        ],
        title="Best stands",
        column_styles={"partnership": "bold cyan"},
    )
    _render.footnote("Same exported partnerships JSON as the web app.")
