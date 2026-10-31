"""METHODOLOGY §10's worked example, reality table and default calls, generated from the exported data.

Each franchise's Keep or release picture is built exactly as the page and `cricdesk keep` build it, and the
three blocks are written between their markers (`<!-- keep-example -->`, `<!-- keep-reality -->`,
`<!-- keep-calls -->`), so the docs can't drift from the site (they had: Rohit Sharma read 71% and Dhoni
73% after the Keep model behind them was refitted). `tests/test_reality_gate.py` rebuilds them and fails
when they differ. The "what the franchise did" column is sourced history, kept here as text.

    uv run python scripts/keep_sheets.py          # rewrite the blocks in docs/METHODOLOGY.md
    uv run python scripts/keep_sheets.py --check  # exit 1 if the docs are stale
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import typer

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "METHODOLOGY.md"
BLOCKS = ("keep-example", "keep-reality", "keep-calls")

# the 25 marquee players and what their franchise did (Wikipedia's personnel pages, ESPNcricinfo)
MARQUEE = [
    ("Virat Kohli", "Retained 2025 (21 cr), kept for 2026"),
    ("Rohit Sharma", "Retained 2025, kept for 2026"),
    ("Suryakumar Yadav", "Retained 2025, kept for 2026"),
    ("Jasprit Bumrah", "Retained 2025, kept for 2026"),
    ("Shubman Gill", "Retained 2025, kept for 2026 (captain)"),
    ("Rishabh Pant", "Bought 27 by LSG (2025); traded back to DC at 15 (June 2026)"),
    ("Ravindra Jadeja", "Retained by CSK 2025; traded to RR for 2026"),
    ("MS Dhoni", "Retained 2025 (uncapped, 4 cr), kept for 2026; did not play in 2026"),
    ("Rinku Singh", "Retained 2025, kept for 2026"),
    ("Tejasvi Singh", "Bought 3 cr at the 2026 auction; 15 IPL balls"),
    ("Hardik Pandya", "Retained 2025, kept for 2026 (captain)"),
    ("Tilak Varma", "Retained 2025, kept for 2026"),
    ("Abhishek Sharma", "Retained 2025, kept for 2026"),
    ("Yashasvi Jaiswal", "Retained 2025, kept for 2026"),
    ("Shreyas Iyer", "Bought 26.75 (2025), kept for 2026 (captain)"),
    ("KL Rahul", "Bought 14 (2025), kept for 2026"),
    ("Axar Patel", "Retained 2025, kept for 2026 (captain)"),
    ("Sanju Samson", "Retained by RR 2025; traded to CSK for 2026"),
    ("Ruturaj Gaikwad", "Retained 2025, kept for 2026 (captain)"),
    ("Rashid Khan", "Retained 2025, kept for 2026"),
    ("Pat Cummins", "Retained 2025, kept for 2026 (captain)"),
    ("Heinrich Klaasen", "Retained 2025 (23 cr), kept for 2026"),
    ("Cameron Green", "Bought 25.2 at the 2026 auction (paid 18)"),
    ("Vaibhav Suryavanshi", "Bought 1.1 (2025), kept for 2026"),
    ("Arshdeep Singh", "Bought back 18 with an RTM (2025), kept for 2026"),
]
TOSS = (0.35, 0.65)  # keep.py KEEP_CALL ± BORDER_BAND: Release below, Keep from


def evaluate_all() -> dict:
    """team → the evaluated squad (keep.py `evaluate`, the page's defaults), plus the 2026 kept rate."""
    import json

    from cricdesk.web_parity import build_pool, load_auction_pool
    from cricdesk.web_parity.keep import evaluate, market_for, squad_of
    from cricdesk.web_parity.loader import load_keep

    data = load_keep("ipl")
    pool = build_pool(load_auction_pool("ipl"))
    rules = dict(data["competition"]["rules"])
    out = {}
    for team in data["teams"]:
        market = market_for(
            team, data["players"], pool, data.get("pool_tags") or {}, data.get("form"), rules
        )
        out[team] = evaluate(squad_of(data, team), market, rules, {}, {}, data.get("form"))
    # the shipped model's own record of its validation (committed; data/metrics is not)
    ev = json.loads((ROOT / "config" / "keep_model.json").read_text(encoding="utf-8"))["evaluation"]
    model = next(k for k in ev["validation"] if k.startswith(ev["chosen"].split()[0] + " "))
    return {"teams": out, "kept_2026": ev["validation"][model]["2026"]["kept_rate"]}


def _cr(x: float | None) -> str:
    return "–" if x is None else f"{round(float(x), 2):g}"


def _pct(p: float | None) -> str:
    return "–" if p is None else f"{round(100 * p)}%"


def _call(p: dict) -> str:
    pk = p.get("p_keep")
    if pk is None or TOSS[0] <= pk < TOSS[1]:
        return f"Toss-up ({'kept' if p['kept'] else 'released'})"
    return "Keep" if pk >= TOSS[1] else "Release"


def _players(ev: dict) -> dict:
    return {p["name"]: {**p, "team": t} for t, r in ev["teams"].items() for p in r["players"]}


def render_example(ev: dict) -> str:
    """The worked example: Virat Kohli's call, from the same numbers as the page."""
    p = _players(ev)["Virat Kohli"]
    fc = p.get("forecast") or {}
    reg = fc.get("p_regular_last")
    return (
        f"*Worked example (IPL 2027 defaults, data to the 2026 final).* RCB's Virat Kohli: value "
        f"{p['value_now']:+.1f} for the coming season (career {p['value']:+.1f}), {math.floor(p['age'])} at the "
        f"auction, {p.get('matches_last') or 0} IPL matches last season; market price {_cr(p['price'])} cr "
        f"({_cr(p['price_central'])} in the top quarter). A 2025 retention, so keeping him costs what releasing "
        f"him alone would free under the slab rule: {_cr(p['cost'])} cr, against a {_cr(p['salary'])} cr salary. "
        f"His price is {'under' if p['price'] < p['cost'] else 'over'} his cost; "
        f"{'he is home-grown and ' if p.get('home_grown') else ''}has played {p.get('seasons_here') or 0} seasons for "
        f"RCB"
        + (
            f", and the forecast gives him a {round(100 * reg)}% chance of being a regular in its third season"
            if reg is not None
            else ""
        )
        + f": franchises kept **{_pct(p['p_keep'])}** of players like him, so **{_call(p).split(' (')[0]}**."
    )


def render_reality(ev: dict) -> str:
    """The 25 marquee players' rows, and who of them the default plan doesn't keep."""
    ps = _players(ev)
    rows = ["| player | team | salary | cost | market | P | call | what the franchise did |",
            "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for name, did in MARQUEE:
        p = ps[name]
        cost = _cr(p["cost"]) + (" (slab)" if abs(p["cost"] - float(p["salary"])) > 0.005 else "")
        rows.append(f"| {name} | {p['team']} | {_cr(p['salary'])} | {cost} | {_cr(p['price'])} / "
                    f"{_cr(p['price_central'])} | {_pct(p['p_keep'])} | {_call(p)} | {did} |")  # fmt: skip
    out = [ps[n] for n, _ in MARQUEE if not ps[n]["kept"]]
    rows.append("")
    rows.append(
        f"{len(MARQUEE) - len(out)} of the {len(MARQUEE)} are kept by default"
        + (
            ": not kept, "
            + "; ".join(
                f"{p['name']} ({_pct(p['p_keep'])}, {p.get('matches_last') or 0} IPL "
                f"matches last season)"
                for p in out
            )
            if out
            else ""
        )
        + "."
    )
    return "\n".join(rows)


def render_calls(ev: dict) -> str:
    """Per team: kept, purse left, the releases (lowest chance first) and the toss-ups kept."""
    lines = []
    n_all = n_kept = 0
    for team, r in ev["teams"].items():
        ps = r["players"]
        rel = sorted(
            (p for p in ps if not p["kept"]), key=lambda p: (p.get("p_keep") or 0, p["name"])
        )
        tk = sorted((p for p in ps if p["kept"] and p.get("p_keep") is not None and p["p_keep"] < TOSS[1]),
                    key=lambda p: (p["p_keep"], p["name"]))  # fmt: skip
        part = f"- **{team}** ({r['kept']} kept, {_cr(r['purse_left'])} cr left): "
        if rel:
            part += "release " + ", ".join(
                p["name"] + (f" ({_pct(p['p_keep'])})" if k in (0, len(rel) - 1) else "")
                for k, p in enumerate(rel)
            )
        else:
            part += "no release"
        if tk:
            part += ". Toss-up, kept: " + ", ".join(p["name"] for p in tk)
        lines.append(part + ".")
        n_all += len(ps)
        n_kept += r["kept"]
    lines.append("")
    lines.append(
        f"{n_kept} of the {n_all} are kept by default ({round(100 * n_kept / n_all)}%; franchises kept "
        f"{round(100 * ev['kept_2026'])}% in 2026). The releases are what franchises release in a mini "
        f"year: overseas squad players, the young uncapped who didn't play, the old who stopped playing."
    )
    return "\n".join(lines)


def render_all(ev: dict) -> dict[str, str]:
    return {
        "keep-example": render_example(ev),
        "keep-reality": render_reality(ev),
        "keep-calls": render_calls(ev),
    }


def _pattern(name: str) -> re.Pattern:
    return re.compile(rf"<!-- {name}:start -->\n(.*?)\n<!-- {name}:end -->", re.S)


def doc_blocks() -> dict[str, str | None]:
    s = DOC.read_text(encoding="utf-8")
    return {b: (m.group(1) if (m := _pattern(b).search(s)) else None) for b in BLOCKS}


def main(
    check: bool = typer.Option(False, "--check", help="Exit 1 if the docs are stale."),
) -> None:
    blocks = render_all(evaluate_all())
    if check:
        stale = [b for b, v in doc_blocks().items() if v != blocks[b]]
        if stale:
            typer.echo(
                f"docs/METHODOLOGY.md is stale ({', '.join(stale)}): run scripts/keep_sheets.py"
            )
            raise typer.Exit(1)
        typer.echo("up to date")
        return
    s = DOC.read_text(encoding="utf-8")
    for b, text in blocks.items():
        if f"<!-- {b}:start -->" not in s:
            raise typer.BadParameter(f"no <!-- {b}:start --> marker in {DOC}")
        s = _pattern(b).sub(lambda _, b=b, t=text: f"<!-- {b}:start -->\n{t}\n<!-- {b}:end -->", s)
    DOC.write_text(s, encoding="utf-8")
    typer.echo("\n\n".join(blocks.values()))


if __name__ == "__main__":
    typer.run(main)
