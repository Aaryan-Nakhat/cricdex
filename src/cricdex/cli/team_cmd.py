"""`cricdex team xi` / `cricdex team replace` — team building.

Runs the SAME parity-locked engines as the web Team Lab page
(`cricdex.web_parity`: best_xi / analyze_squad / replacement_by_need) on the
SAME exported JSON, so the terminal output matches the site bit-for-bit.
"""

from __future__ import annotations

import json

import typer

from cricdex.cli import _render
from cricdex.cli._shared import EXIT_MISSING_DATA, console, die, resolve_or_die
from cricdex.common import filters as cf
from cricdex.web_parity.loader import SITE_DATA

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("xi", help="Optimal playing XI under budget/overseas/role caps (+ squad balance).")
def xi(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    budget: float = typer.Option(100.0, "--budget", "-b", help="purse in crore"),
    overseas: int = typer.Option(4, "--overseas", "-o", help="max overseas in the XI"),
    batter: int = typer.Option(3, "--batter", help="min batters"),
    bowler: int = typer.Option(3, "--bowler", help="min bowlers"),
    all_rounder: int = typer.Option(1, "--all-rounder", help="min all-rounders"),
    keeper: int = typer.Option(1, "--keeper", help="min keepers"),
) -> None:
    from cricdex.web_parity import analyze_squad, best_xi, est_value, load_auction_pool

    try:
        pool = load_auction_pool(collection)
        ngi = {
            r["cricsheet_id"]: r["ngi_total"] for r in cf.load_leaderboard(collection, "ngi", "all")
        }
    except FileNotFoundError as e:
        die(str(e), code=EXIT_MISSING_DATA, hint="run `uv run python scripts/export_site.py`")

    role_mins = {"batter": batter, "bowler": bowler, "all_rounder": all_rounder, "keeper": keeper}
    players = [
        {
            "cricsheet_id": r["cricsheet_id"],
            "name": r["name"],
            "role": r["role"],
            "is_overseas": r["is_overseas"],
            "ngi": ngi[r["cricsheet_id"]],
            "price": est_value(r["value"], r["role"], "ipl"),
        }
        for r in pool
        if r["cricsheet_id"] in ngi
    ]
    res = best_xi(players, float(budget), overseas, role_mins, 11, 40)
    _render.header(
        "Team Lab — optimal XI",
        subtitle=f"{collection} · budget {budget:.0f}cr · overseas ≤ {overseas}",
    )
    if not res["feasible"]:
        die("no valid XI under these constraints — loosen the budget/overseas/role minimums")
    _render.pretty_table(
        [
            {
                "player": p["name"],
                "role": p["role"],
                "o/s": "✈" if p["is_overseas"] else "",
                "ngi": round(p["ngi"], 2),
                "cr": round(p["price"], 1),
            }
            for p in res["players"]
        ],
        title=(
            f"Optimal XI · NGI {res['total_ngi']:.2f} · "
            f"{res['total_price']:.1f}cr · {res['overseas']} overseas"
        ),
        column_styles={"player": "bold cyan"},
    )
    ppath = SITE_DATA / collection / "players.json"
    pos = (
        {p["cricsheet_id"]: p.get("batting_position") for p in json.loads(ppath.read_text())}
        if ppath.exists()
        else {}
    )
    squad = analyze_squad(
        [
            {
                "role": p["role"],
                "is_overseas": p["is_overseas"],
                "batting_position": pos.get(p["cricsheet_id"]),
            }
            for p in res["players"]
        ],
        role_mins,
        overseas,
    )
    role_bits = " · ".join(f"{k}:{v}" for k, v in squad["roles"].items())
    if squad["balanced"]:
        console().print(f"[green]Balanced[/green] — {role_bits}")
    else:
        console().print(
            f"[yellow]{len(squad['gaps'])} gap(s)[/yellow]: "
            + "; ".join(squad["gaps"])
            + f"  ({role_bits})"
        )
    _render.footnote("Exact knapsack on NGI (parity-locked web_parity.best_xi).")


@app.command("replace", help="Cheaper same-mould replacements for an IPL player across leagues.")
def replace(
    name: str = typer.Argument(..., help="IPL player to replace (fuzzy-matched)"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top: int = typer.Option(12, "--top", "-n"),
) -> None:
    from cricdex.web_parity import est_value, load_scout_index, replacement_by_need

    try:
        idx = load_scout_index(collection)
    except FileNotFoundError as e:
        die(str(e), code=EXIT_MISSING_DATA, hint="run `uv run python scripts/export_site.py`")

    name = resolve_or_die(name, collection=collection)
    sel = next((p for p in idx["ipl"] if p["name"] == name), None)
    if sel is None:
        die(f"{name} isn't in the active IPL scout index (too few balls / inactive).")
    sel_price = est_value(sel["value"], sel["role"], "ipl")
    _render.header(
        f"Replacement by need — {name}",
        subtitle=f"≈ {sel_price:.1f}cr · cheaper same-mould options",
    )
    merged = []
    for tier in ("smat", "bbl", "sa20", "cpl", "blast"):
        for r in replacement_by_need(sel, idx[tier], tier):
            merged.append(
                {
                    "player": r["name"],
                    "league": tier.upper(),
                    "country": r.get("country") or "—",
                    "sim%": round(r["sim"] * 100),
                    "est_cr": r["est_cr"],
                    "save_cr": r["saving"] if r["saving"] > 0 else "",
                }
            )
    merged.sort(key=lambda r: (-(r["save_cr"] or 0), -r["sim%"]))
    if merged:
        _render.pretty_table(
            merged[:top], title="Cheaper same-mould options", column_styles={"player": "bold cyan"}
        )
    else:
        console().print("[dim]No cheaper same-mould option found.[/dim]")
    _render.footnote("Parity-locked web_parity.replacement_by_need (similar_to + tier price).")
