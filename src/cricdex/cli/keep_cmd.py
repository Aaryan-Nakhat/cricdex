"""`cricdex keep --team RCB` — Keep or release, the franchise retention calculator.

Reads the exported keep.json + auction_pool.json and computes with `cricdex.web_parity.keep`,
the Python twin of the website's Keep or release page (locked by test_keep_parity.py), so the
table here is the page's table.
"""

from __future__ import annotations

import csv
import difflib
import math
from pathlib import Path

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import EXIT_USER_ERROR, console, die

SORTS = ("surplus", "price", "onfield", "outlook", "salary", "value", "age", "name")
REC_STYLE = {"keep": "green", "release": "red", "borderline": "yellow"}


def _find(rows: list[dict], name: str) -> dict:
    """A squad player by (part of) his name; did-you-mean on a miss, a list on several hits."""
    needle = name.strip().lower()
    exact = [p for p in rows if p["name"].lower() == needle]
    hits = exact or [p for p in rows if needle in p["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        die(
            f"{name!r} matches {len(hits)} players: " + ", ".join(p["name"] for p in hits),
            code=EXIT_USER_ERROR,
        )
    near = difflib.get_close_matches(name, [p["name"] for p in rows], n=3, cutoff=0.5)
    die(
        f"no {name!r} in this squad",
        code=EXIT_USER_ERROR,
        hint=f"did you mean {' / '.join(near)}?" if near else "check the squad below the table",
    )


def keep(
    team: str = typer.Option(..., "--team", "-t", help="Franchise code, e.g. RCB, CSK, MI."),
    keep_names: list[str] = typer.Option(
        [], "--keep", "-k", help="Keep this player whatever the recommendation (repeatable)."
    ),
    release_names: list[str] = typer.Option(
        [], "--release", "-r", help="Release this player (repeatable)."
    ),
    purse: float | None = typer.Option(
        None, "--purse", help="Override the competition's purse (cr)."
    ),
    need: list[str] = typer.Option(
        [],
        "--need",
        help="Role target, e.g. --need spinner=4 (keeper, opener, death, spinner, overseas).",
    ),
    sort: str = typer.Option("surplus", "--sort", help=f"One of {', '.join(SORTS)}."),
    csv_path: Path | None = typer.Option(
        None, "--csv", help="Also write the table to this CSV file."
    ),
    check: bool = typer.Option(
        False, "--check", help="Show the salary data check against the published purses."
    ),
) -> None:
    from cricdex.web_parity import build_pool, load_auction_pool
    from cricdex.web_parity.keep import (
        TAG_ORDER,
        cr,
        cr_exact,
        evaluate,
        fmt_num,
        market_for,
        player_key,
        squad_of,
        to_csv_rows,
    )
    from cricdex.web_parity.loader import load_keep

    if sort not in SORTS:
        die(f"--sort must be one of {', '.join(SORTS)}", code=EXIT_USER_ERROR)
    try:
        data = load_keep("ipl")
        pool = build_pool(load_auction_pool("ipl"))
    except FileNotFoundError as e:
        die(str(e), code=EXIT_USER_ERROR)
    teams = data.get("teams") or []
    code = team.strip().upper()
    if code not in teams:
        near = difflib.get_close_matches(code, teams, n=3, cutoff=0.3)
        die(
            f"unknown team {team!r}",
            code=EXIT_USER_ERROR,
            hint=(f"did you mean {' / '.join(near)}? " if near else "")
            + "teams: "
            + ", ".join(teams),
        )
    comp = data["competition"]
    rules = dict(comp["rules"])
    if purse is not None:
        rules["purse"] = purse
    needs: dict[str, int] = {}
    for n in need:
        k, _, v = n.partition("=")
        if k not in TAG_ORDER or not v.strip().isdigit():
            die(f"--need {n!r}: use tag=N with tag in {', '.join(TAG_ORDER)}", code=EXIT_USER_ERROR)
        needs[k] = int(v)
    squad = squad_of(data, code)
    decisions: dict[str, str] = {}
    for n in keep_names:
        decisions[player_key(_find(squad, n))] = "keep"
    for n in release_names:
        decisions[player_key(_find(squad, n))] = "release"
    market = market_for(code, data["players"], pool, data.get("pool_tags") or {}, data.get("form"))
    res = evaluate(squad, market, rules, decisions, needs, data.get("form"))

    def sort_key(p: dict):
        if sort == "name":
            return (p["name"],)
        v = {
            "surplus": p["surplus"],
            "price": p["price"],
            "onfield": p["onfield"],
            "outlook": p.get("forecast_avg3"),
            "salary": p["salary"],
            "value": p["value"],
            "age": p["age"],
        }[sort]
        return (v is None, -(v if v is not None else 0))

    players = sorted(res["players"], key=sort_key)
    assumed = set(comp.get("assumed") or [])
    _render.header(
        f"Keep or release — {code}, {comp['name']}",
        subtitle=(
            f"retention deadline {comp['retention_deadline']}  ·  auction {comp['auction_date']}"
            f"{' (likely)' if 'auction_date' in assumed else ''}  ·  purse {cr(rules['purse'])} cr"
            f"{' (assumed)' if 'purse' in assumed and purse is None else ''}"
        ),
    )
    _render.intro_panel(_copy.KEEP_INTRO, title="Keep or release")
    _render.pretty_table(
        [
            {
                "player": p["name"]
                + (" ✈" if p.get("overseas") else "")
                + (" (C)" if p.get("captain") else ""),
                "role": p["role"].replace("_", "-"),
                "age": None if p.get("age") is None else math.floor(p["age"]),
                "salary": cr_exact(p["salary"]),
                "value": None
                if p.get("value") is None
                else f"{fmt_num(p['value'], 1)} ± {fmt_num(p['value_sd'], 1)}",
                "market": None
                if p["price"] is None
                else cr(p["price"])
                + ("" if p.get("p_bought") is None else f" ({fmt_num(100 * p['p_bought'], 0)}%)"),
                "on-field": None if p.get("onfield") is None else cr(p["onfield"]),
                "surplus": None if p["surplus"] is None else cr(p["surplus"]),
                "3-season outlook": p.get("forecast_note") or None,
                "call": f"[{REC_STYLE[p['rec']]}]{p['rec']}[/]",
                "decision": ("keep" if p["kept"] else "release")
                + (" *" if p["overridden"] else ""),
                "why": p["reason"],
            }
            for p in players
        ],
        title=f"{code}: {res['kept']} kept, {res['released']} released (sorted by {sort})",
        column_styles={"player": "bold cyan"},
    )
    _render.kv_grid(
        {
            "purse": f"{cr(res['purse'])} cr",
            "kept salaries": f"{cr(res['salary_kept'])} cr",
            "purse left": f"{cr(res['purse_left'])} cr",
            "slots left": f"{res['slots_left']} ({res['overseas_slots_left']} overseas)",
            "replacements": f"{cr(res['replacement_cost'])} cr",
            "after replacements": f"{cr(res['purse_after_replacements'])} cr",
        },
        title="Squad",
        cols=3,
    )
    _render.pretty_table(
        [
            {
                "need": g["label"],
                "target": g["target"],
                "kept": g["kept"],
                "gap": g["gap"],
                "at least": (
                    f"{fmt_num(g['ref_value'], 1)} (best released)"
                    if g["ref_from_release"]
                    else "0 (league average)"
                ),
                "cheapest fits": ", ".join(
                    f"{c['name']} {cr(c['price'])}"
                    + (f" (from {c['from_team']})" if c.get("from_team") else "")
                    for c in g["picks"]
                )
                or ("—" if g["gap"] == 0 else "none found"),
                "cost": cr(g["cost"]),
            }
            for g in res["gaps"]
        ],
        title="Role gaps and what filling them costs (free agents + other teams' release calls)",
        column_styles={"need": "bold"},
    )
    c = console()
    for w in res["warnings"]:
        c.print(f"[yellow]![/yellow] {w}")
    if check:
        pc = data.get("purse_check") or {}
        _render.pretty_table(
            [
                {
                    "team": t,
                    "published": v["published"],
                    "ours": v["ours"],
                    "diff": round(v["ours"] - v["published"], 2),
                }
                for t, v in sorted((pc.get("teams") or {}).items())
            ],
            title="Purse entering the 2026 auction: published vs our salaries",
        )
        c.print(f"[dim]{pc.get('source') or ''}[/dim]")
        if data.get("unmatched"):
            c.print(
                "[dim]Not rated (no Cricsheet match): "
                + ", ".join(f"{u['team']} {u['name']}" for u in data["unmatched"])
                + "[/dim]"
            )
    if assumed:
        c.print(
            f"[dim]Assumed, not confirmed: {', '.join(sorted(assumed))} (config/competitions.toml).[/dim]"
        )
    if csv_path:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(to_csv_rows(res))
        c.print(f"[dim]wrote {csv_path}[/dim]")
    _render.footnote(
        "Same keep.json + pool + calculator as the web page (locked by test_keep_parity.py). "
        "--keep / --release flip a player; --need sets a role target."
    )
