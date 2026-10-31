"""The 2027 Bid plan sheets table of docs/METHODOLOGY.md §12, generated from the exported data (METHODOLOGY §12).

Builds every franchise's default plan exactly as the page and `cricdesk bidplan` do and writes the table
between the `<!-- bidplan-sheets:start -->` / `<!-- bidplan-sheets:end -->` markers, so the docs can't
drift from the site. `tests/test_reality_gate.py` rebuilds it from the same plans and fails when they
differ.

    uv run python scripts/bidplan_sheets.py          # rewrite the table in docs/METHODOLOGY.md
    uv run python scripts/bidplan_sheets.py --check  # exit 1 if the docs table is stale
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import typer

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "METHODOLOGY.md"
START, END = "<!-- bidplan-sheets:start -->", "<!-- bidplan-sheets:end -->"
TOP = 5


def ages() -> dict[str, float | None]:
    """cid → age, from the exported pool and squads."""
    from cricdesk.web_parity import load_auction_pool
    from cricdesk.web_parity.loader import load_keep

    players = load_keep("ipl")["players"]
    players = players.values() if isinstance(players, dict) else players
    out = {r["cricsheet_id"]: r.get("age") for r in load_auction_pool("ipl")}
    out.update({p["id"]: p.get("age") for p in players if p.get("id")})
    return out


def build_plans() -> dict:
    """team → {"ctx", "res"} for the ten default 2027 plans, as the page and the CLI build them."""
    from cricdesk.web_parity import build_pool, load_auction_pool
    from cricdesk.web_parity.bidplan import OPEN_SLOTS, TRIALS, build_context, plan, rival_runs
    from cricdesk.web_parity.loader import load_auction_register, load_bidplan_rivals, load_keep

    data = load_keep("ipl")
    raw = load_auction_pool("ipl")
    pool = build_pool(raw)
    reg = load_auction_register("ipl")
    display = {r["cricsheet_id"]: r["display_name"] for r in raw if r.get("display_name")}
    out = {}
    for team in data["teams"]:
        ctx = build_context(data, pool, team, {}, None, OPEN_SLOTS, None, reg, display,
                            load_bidplan_rivals("ipl"))  # fmt: skip
        rr = rival_runs(ctx, TRIALS)
        out[team] = {
            "ctx": ctx,
            "res": plan(ctx, None, None, TRIALS, rr["prices"], rate=rr["rate"]),
        }
    return out


def _cr(x: float) -> str:
    return f"{round(float(x), 2):g}"


def render(plans: dict, ages: dict) -> str:
    """The markdown table: per team its kept players, purse left and expected spend, the top five targets
    (age, what rivals usually pay → max bid, cr; "rel." = released by that team's default plan) and the
    needs still short after the likely buys."""
    rows = ["| team (kept, purse left, expected spend = share) | top five targets | still short of |",
            "|---|---|---|"]  # fmt: skip
    for team, p in plans.items():
        ctx, res = p["ctx"], p["res"]
        left = float(ctx["purse_left"])
        share = res["mean_spend"] / left if left > 0 else 0.0
        ts = []
        for t in res["targets"][:TOP]:
            age = ages.get(t["id"])
            who = t["name"] + (f" ({t['from_team']} rel.)" if t.get("from_team") else "")
            who += f", {math.floor(age)}" if age is not None else ""
            ts.append(f"{who} {_cr(t['expected_price'])} → {_cr(t['max_bid'])}")
        short = ", ".join(m["label"] for m in res["missing"]) or "nothing"
        rows.append(f"| {team} ({len(ctx['kept'])}, {_cr(left)}, {_cr(res['mean_spend'])} = "
                    f"{share:.0%}) | {'; '.join(ts)} | {short} |")  # fmt: skip
    return "\n".join(rows)


def doc_table() -> str | None:
    s = DOC.read_text(encoding="utf-8")
    m = re.search(re.escape(START) + r"\n(.*?)\n" + re.escape(END), s, re.S)
    return m.group(1) if m else None


def main(
    check: bool = typer.Option(False, "--check", help="Exit 1 if the docs table is stale."),
) -> None:
    table = render(build_plans(), ages())
    if check:
        if doc_table() != table:
            typer.echo(
                "docs/METHODOLOGY.md's Bid plan sheets are stale: run scripts/bidplan_sheets.py"
            )
            raise typer.Exit(1)
        typer.echo("up to date")
        return
    s = DOC.read_text(encoding="utf-8")
    if START not in s:
        raise typer.BadParameter(f"no {START} marker in {DOC}")
    s = re.sub(re.escape(START) + r"\n.*?\n" + re.escape(END), lambda _: f"{START}\n{table}\n{END}", s,
               flags=re.S)  # fmt: skip
    DOC.write_text(s, encoding="utf-8")
    typer.echo(table)


if __name__ == "__main__":
    typer.run(main)
