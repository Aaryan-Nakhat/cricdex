"""`cricdesk forecast "<name>"` / `cricdesk forecast --team RCB` — Form forecast.

A player's value (runs per 100 balls above the average ball) projected over the next three IPL
seasons, with an 80% range and the chance he is still a regular. Reads the exported
`forecast.json` (the same file as the player profile's Form forecast section); the method is in
docs/METHODOLOGY.md §11 and `cricdesk.scout.forecast`.
"""

from __future__ import annotations

import difflib
import json
import math

import typer

from cricdesk.cli import _render
from cricdesk.cli._shared import (
    EXIT_MISSING_DATA,
    EXIT_USER_ERROR,
    console,
    die,
    load_players,
    match_player,
    player_label,
)
from cricdesk.web_parity.loader import SITE_DATA

ROLE_LABEL = {"batter": "Batting", "bowler": "Bowling"}
FLAG_STYLE = {
    "hold": "green",
    "improve": "bold green",
    "hold_then_decline": "yellow",
    "decline": "red",
}
FLAG_WORD = {
    "hold": "holds",
    "improve": "improves",
    "hold_then_decline": "holds, then declines",
    "decline": "declines",
}


def _num(x: float | None) -> str:
    if x is None:
        return "—"
    r = math.floor(x + 0.5)  # half up, as the site's Math.round
    return "0" if r == 0 else f"{r:+d}"


def load_forecast(collection: str = "ipl") -> dict:
    path = SITE_DATA / collection / "forecast.json"
    if not path.exists():
        die(
            f"no forecast.json at {path}",
            code=EXIT_MISSING_DATA,
            hint="run `uv run python scripts/form_forecast.py build` then "
            "`uv run python scripts/form_forecast.py export`",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(role: dict, cols: list[str]) -> list[dict]:
    """The three seasons of one role as table rows."""
    out = []
    for s in role["s"]:
        r = dict(zip(cols, s, strict=True))
        out.append(
            {
                "season": r["season"],
                "median": _num(r["median"]),
                "80% range (level)": f"{_num(r['lo'])} to {_num(r['hi'])}",
                "80% range (one season)": f"{_num(r['season_lo'])} to {_num(r['season_hi'])}",
                "P(regular)": f"{round(r['p_regular'] * 100)}%",
            }
        )
    return out


def forecast(
    name: str = typer.Argument("", help='Player name (any part of it), e.g. "Kohli".'),
    team: str = typer.Option("", "--team", "-t", help="A franchise's squad table, e.g. RCB."),
    output_json: bool = typer.Option(False, "--json", help="Print the raw forecast JSON."),
) -> None:
    """Form forecast: value over the next three seasons, with an 80% range and P(regular)."""
    if not name and not team:
        die('give a player name or --team, e.g. cricdesk forecast "Kohli"', code=EXIT_USER_ERROR)
    data = load_forecast("ipl")
    players = load_players("ipl") or []
    cols = data["columns"]
    fc = data["players"]
    first = data["as_of_season"] + 1
    if team:
        _team(team.strip().upper(), data, players, output_json)
        return
    row, candidates = match_player(name, players)
    if row is None:
        # several namesakes: the one with a forecast (an active IPL player) wins
        with_fc = [p for p in candidates if p["cricsheet_id"] in fc]
        if len(with_fc) == 1:
            row, candidates = with_fc[0], []
    if row is None:
        if candidates:
            die(
                f"{name!r} matches {len(candidates)} players: "
                + ", ".join(player_label(p) for p in candidates[:8]),
                code=EXIT_USER_ERROR,
                hint="type more of the name",
            )
        near = difflib.get_close_matches(
            name, [p.get("display_name") or p["name"] for p in players], n=3, cutoff=0.5
        )
        die(
            f"no IPL player matching {name!r}",
            code=EXIT_USER_ERROR,
            hint=f"did you mean {' / '.join(near)}?" if near else None,
        )
    cid = row["cricsheet_id"]
    label = row.get("display_name") or row["name"]
    roles = fc.get(cid)
    if output_json:
        typer.echo(json.dumps({cid: roles}, indent=2))
        return
    if not roles:
        why = (
            "retired"
            if row.get("retired")
            else "no IPL season in the last two, or too few balls a season in a role"
        )
        die(f"no forecast for {label} ({why})", code=EXIT_USER_ERROR)
    _render.header(
        f"Form forecast — {label}",
        subtitle=f"IPL {first}–{first + 2}  ·  value = runs per 100 balls above the average ball",
    )
    c = console()
    for role_key in ("batter", "bowler"):
        r = roles.get(role_key)
        if not r:
            continue
        style = FLAG_STYLE.get(r["flag"], "")
        _render.section(
            f"{ROLE_LABEL[role_key]}  ·  current level {_num(r.get('level', r['now']))}"
            f"  ·  career rating {_num(r['now'])}"
        )
        if r.get("recent"):
            c.print(
                "[dim]last seasons: "
                + " · ".join(f"{s} {_num(v)} ({b} balls)" for s, v, b in r["recent"])
                + "[/dim]"
            )
        c.print(f"[{style}]{r['text']}[/{style}]")
        _render.pretty_table(_rows(r, cols), column_styles={"season": "bold cyan"})
    _render.footnote(
        "Median = the expected value if he plays; the level range is where his true level "
        "probably sits, the one-season range adds a season's luck at his usual workload "
        "(the backtest checks this one: about three in four seasons landed inside). P(regular) = the chance "
        f"he faces or bowls {data['regular_balls']}+ balls that season. Method: METHODOLOGY §11."
    )


def _team(code: str, data: dict, players: list[dict], output_json: bool) -> None:
    teams = sorted({p.get("team") for p in players if p.get("team")})
    if code not in teams:
        near = difflib.get_close_matches(code, teams, n=3, cutoff=0.3)
        die(
            f"unknown team {code!r}",
            code=EXIT_USER_ERROR,
            hint=(f"did you mean {' / '.join(near)}? " if near else "")
            + "teams: "
            + ", ".join(teams),
        )
    cols = data["columns"]
    first = data["as_of_season"] + 1
    rows = []
    for p in players:
        if p.get("team") != code:
            continue
        for role_key, r in (data["players"].get(p["cricsheet_id"]) or {}).items():
            s = [dict(zip(cols, x, strict=True)) for x in r["s"]]
            rows.append(
                {
                    "player": p.get("display_name") or p["name"],
                    "role": ROLE_LABEL[role_key].lower(),
                    "level": r.get("level", r["now"]),
                    "rating": r["now"],
                    **{str(x["season"]): x["median"] for x in s},
                    "avg": r.get("avg3"),
                    f"P(reg) {first + 2}": s[-1]["p_regular"],
                    "outlook": r["flag"],
                }
            )
    rows.sort(key=lambda x: -(x["avg"] if x["avg"] is not None else -1e9))
    if output_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    _render.header(
        f"Form forecast — {code}",
        subtitle=f"IPL {first}–{first + 2}  ·  median value (runs per 100 balls above average)",
    )
    _render.pretty_table(
        rows,
        column_styles={"player": "bold"},
        formatters={
            "level": _num,
            "rating": _num,
            **{str(first + i): _num for i in range(3)},
            "avg": _num,
            f"P(reg) {first + 2}": lambda v: f"{round(v * 100)}%",
            "outlook": lambda f: f"[{FLAG_STYLE.get(f, '')}]{FLAG_WORD.get(f, f)}[/]",
        },
        empty_msg=f"no forecast rows for {code} (export forecast.json first)",
    )
    _render.footnote(
        "Players with an IPL season in the last two and 60+ balls a season in the role. "
        'One player\'s ranges and plain-English outlook: cricdesk forecast "<name>".'
    )
