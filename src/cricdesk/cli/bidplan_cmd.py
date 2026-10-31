"""`cricdesk bidplan --team RCB` — Bid plan, the auction bidding-plan optimiser.

Reads the exported keep.json + auction_pool.json and computes with `cricdesk.web_parity.bidplan`,
the Python twin of the website's Bid plan page (locked by test_bidplan_parity.py): the same squad
going in (Keep or release's plan, with your --keep / --release calls), the same rival runs, the
same targets, max bids and fallback chains.
"""

from __future__ import annotations

import csv
import difflib
import json
from pathlib import Path

import typer

from cricdesk.cli import _render
from cricdesk.cli._shared import EXIT_USER_ERROR, console, die

INTRO = (
    "Bid plan: whom to bid for at the auction, and how high. The other nine franchises keep their "
    "Keep-or-release plans and bid in the Auction room's simulator a few hundred times, which gives, "
    "for every player, the price a rival would pay. The plan then picks the targets that add the "
    "most squad strength (the best XI's runs a match above replacement, each player at the balls he "
    "gets, under the 4-overseas rule, plus the bench filling the matches the XI misses, each lot only "
    "as often as players like him play) for the "
    "purse, allowing for the chance of losing each one. Max bid = his gain in strength over the "
    "plan's exchange rate (runs per crore), capped by what the purse leaves for the rest of the "
    "likely buys. A model's view for discussion, not advice."
)


def _pick(rows: list[dict], name: str, what: str) -> dict:
    """A row by (part of) its name; did-you-mean on a miss, a list on several hits."""
    needle = name.strip().lower()
    exact = [p for p in rows if p["name"].lower() == needle]
    hits = exact or [p for p in rows if needle in p["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        die(
            f"{name!r} matches {len(hits)} {what}: " + ", ".join(p["name"] for p in hits[:12]),
            code=EXIT_USER_ERROR,
        )
    near = difflib.get_close_matches(name, [p["name"] for p in rows], n=3, cutoff=0.5)
    die(
        f"no {name!r} among the {what}",
        code=EXIT_USER_ERROR,
        hint=f"did you mean {' / '.join(near)}?" if near else None,
    )


def bidplan(
    team: str = typer.Option(..., "--team", "-t", help="Franchise code, e.g. RCB, CSK, MI."),
    keep_names: list[str] = typer.Option(
        [],
        "--keep",
        "-k",
        help="Keep this squad player whatever Keep or release says (repeatable).",
    ),
    release_names: list[str] = typer.Option(
        [], "--release", "-r", help="Release this squad player (repeatable)."
    ),
    purse: float | None = typer.Option(
        None, "--purse", help="Override the purse (cr), every team."
    ),
    need: list[str] = typer.Option(
        [],
        "--need",
        help="Role need, e.g. --need spinner=4 (keeper, opener, death, spinner, pace).",
    ),
    open_slots: int | None = typer.Option(
        None,
        "--open",
        help="Every team opens at least this many squad places (default 8; 0 = Keep or release's "
        "plan exactly).",
    ),
    max_bid: list[str] = typer.Option(
        [],
        "--max",
        help='Your own max bid for a player, e.g. --max "Phil Salt=14" (0 = never bid; repeatable).',
    ),
    squad_max: int | None = typer.Option(None, "--squad-max", help="Override the squad maximum."),
    squad_min: int | None = typer.Option(None, "--squad-min", help="Override the squad minimum."),
    overseas_cap: int | None = typer.Option(
        None, "--overseas-cap", help="Override the overseas cap."
    ),
    trials: int | None = typer.Option(None, "--trials", help="Rival auction runs (default 200)."),
    register: Path | None = typer.Option(
        None,
        "--register",
        help='The official auction list as JSON: [{"id": cricsheet id, "base_price": cr}, …] '
        "(replaces the pool we infer; the export's auction_register.json is used by default).",
    ),
    csv_path: Path | None = typer.Option(None, "--csv", help="Also write the targets to this CSV."),
) -> None:
    from cricdesk.web_parity import build_pool, load_auction_pool
    from cricdesk.web_parity.bidplan import (
        NEED_LABEL,
        NEED_ORDER,
        OPEN_SLOTS,
        SLOT_LABEL,
        TRIALS,
        build_context,
        chain_text,
        gap_costs,
        plan,
        rival_runs,
        to_csv_rows,
    )
    from cricdesk.web_parity.keep import cr, fmt_num, player_key, squad_of
    from cricdesk.web_parity.loader import load_keep

    try:
        data = load_keep("ipl")
        raw = load_auction_pool("ipl")
        pool = build_pool(raw)
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
    needs: dict[str, int] = {}
    for n in need:
        k, _, v = n.partition("=")
        if k not in NEED_ORDER or not v.strip().isdigit():
            die(
                f"--need {n!r}: use need=N with need in {', '.join(NEED_ORDER)}",
                code=EXIT_USER_ERROR,
            )
        needs[k] = int(v)
    squad = squad_of(data, code)
    decisions: dict[str, str] = {}
    for n in keep_names:
        decisions[player_key(_pick(squad, n, f"{code} players"))] = "keep"
    for n in release_names:
        decisions[player_key(_pick(squad, n, f"{code} players"))] = "release"
    from cricdesk.web_parity.loader import load_auction_register

    reg = load_auction_register("ipl")  # the exported official list, when there is one
    if register is not None:
        try:
            reg = json.loads(register.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            die(f"--register: {e}", code=EXIT_USER_ERROR)
        if isinstance(reg, dict):
            reg = reg.get("players") or []
    rules = {"squad_max": squad_max, "squad_min": squad_min, "overseas_max": overseas_cap}
    n_open = OPEN_SLOTS if open_slots is None else max(0, open_slots)
    display = {r["cricsheet_id"]: r["display_name"] for r in raw if r.get("display_name")}
    from cricdesk.web_parity.loader import load_bidplan_rivals

    ctx = build_context(data, pool, code, decisions, purse, n_open, rules, reg, display,
                        load_bidplan_rivals("ipl"))  # fmt: skip
    overrides: dict[str, float] = {}
    for m in max_bid:
        nm, _, v = m.rpartition("=")
        try:
            val = float(v)
        except ValueError:
            die(f'--max {m!r}: use "Name=cr"', code=EXIT_USER_ERROR)
        row = _pick(ctx["available"], nm, "players in the auction pool")
        overrides[row["cricsheet_id"]] = val
    n_trials = trials or TRIALS
    with _render.spinner(f"Running {n_trials} rival auctions and the plan…"):
        runs = rival_runs(ctx, n_trials)
        res = plan(ctx, needs, overrides, n_trials, runs["prices"], rate=runs["rate"])
    gaps = []
    if res["missing"]:
        with _render.spinner("Pricing the roles still short…"):
            gaps = gap_costs(ctx, res, needs, overrides, runs["prices"], runs["rate"])

    comp = data["competition"]
    assumed = set(comp.get("assumed") or [])
    r = ctx["rules"]
    _render.header(
        f"Bid plan — {code}, {comp['name']}",
        subtitle=(
            f"auction {comp['auction_date']}{' (likely)' if 'auction_date' in assumed else ''}  ·  "
            f"purse {cr(r['purse'])} cr{' (assumed)' if 'purse' in assumed and purse is None else ''}  ·  "
            f"squad {r['squad_min']}–{r['squad_max']}, {r['overseas_max']} overseas  ·  "
            f"{res['trials']} rival runs"
        ),
    )
    _render.intro_panel(INTRO, title="Bid plan")
    released = [p for p in ctx["squad"] if not p["kept"]]
    _render.kv_grid(
        {
            "kept": f"{len(ctx['kept'])} ({sum(1 for p in ctx['kept'] if p['os'])} overseas)",
            "purse left": f"{cr(ctx['purse_left'])} cr",
            "open places": f"{res['slots_open']} ({res['overseas_open']} overseas)",
            "released": ", ".join(
                p["name"] + (" (to open places)" if p.get("auto_release") == "open" else "")
                for p in released
            )
            or "none",
        },
        title=f"Going in (Keep or release's plan{', your calls' if decisions else ''}; "
        f"every team opens at least {n_open} places)",
        cols=2,
    )
    _render.pretty_table(
        [
            {
                "#": x["priority"],
                "player": x["name"] + (" ✈" if x["overseas"] else ""),
                "slot": SLOT_LABEL[x["slot"]],
                "from": x.get("from_team") or "free agent",
                # next season's value, the career rating after it
                "value": fmt_num(x["value_now"], 1) if x.get("value_now") is not None else None,
                "career": fmt_num(x["value"], 1) if x["value"] is not None else None,
                "market": cr(x["price"]),
                "rivals pay": cr(x["expected_price"]),
                "enough 9/10": cr(x["enough_90"]),
                "max bid": cr(x["max_bid"])
                + (" (yours)" if x["override"] else " (purse)" if x["purse_bound"] else ""),
                "P(≤ max)": f"{fmt_num(100 * x['p_le_max'], 0)}%",
                "in plan": f"{fmt_num(100 * x['p_land'], 0)}%",
                "gain": fmt_num(x["gain"], 1),
            }
            for x in res["targets"]
        ],
        title=f"Targets ({len(res['targets'])}): max bid = gain ÷ what a crore still buys from the later "
        f"lots ({fmt_num(res['lam'], 2)} runs per crore at the start; 0 = the purse is the limit)",
        column_styles={"player": "bold cyan"},
    )
    c = console()
    _render.section("Fallback chains (per role: next name if the one before goes above his max)")
    for ch in res["chains"]:
        c.print(f"[bold]{ch['label']}[/bold]: {chain_text(ch)}")
    ex_line = ", ".join(f"{x['name']} ~{cr(x['price'])}" for x in res["likely"]) or "none"
    _render.kv_grid(
        {
            "strength now": fmt_num(res["before"]["total"], 1),
            "expected after": fmt_num(res["mean_strength"], 1),
            "XI now → expected": f"{fmt_num(res['before']['xi'], 1)} → {fmt_num(res['mean_xi'], 1)}",
            "expected spend": f"{cr(res['mean_spend'])} of {cr(ctx['purse_left'])} cr",
            "expected squad": fmt_num(res["mean_squad"], 1),
            "likely buys": ex_line,
        },
        title="Squad",
        cols=3,
    )
    need_bits = [
        f"{NEED_LABEL[n]} {res['needs'][n]}: met in {fmt_num(100 * res['need_met'][n], 0)}% of runs"
        for n in NEED_ORDER
    ]
    c.print("[dim]" + " · ".join(need_bits) + "[/dim]")
    if not res["converged"]:
        c.print(
            f"[yellow]![/yellow] The likely buys didn't settle after {res['rounds']} rounds: the likely "
            "buys and max bids are the last round's; names near the 50% line are uncertain."
        )
    if res.get("topped_up_share"):
        c.print(
            f"[yellow]![/yellow] {round(100 * res['topped_up_share'])}% of runs ended short of the squad "
            "minimum and were filled at the lowest base price."
        )
    for m in res["missing"]:
        c.print(f"[yellow]![/yellow] Still missing after the likely buys: {m['label']} "
                f"({m['have']} of {m['target']}).")  # fmt: skip
    for g in gaps:
        if g["id"] is None:
            c.print(f"  No target fills {g['label'].lower()} within the purse.")
            continue
        c.print(f"  {g['label']}: {g['name']}, usually {cr(g['expected_price'])} cr ({cr(g['enough_90'])} cr to "
                f"be sure in 9 runs of 10). Bought at that price, the best plan around him is "
                f"{fmt_num(abs(g['cost']), 2)} runs a match {'weaker' if g['cost'] > 0 else 'stronger'} than "
                f"this one, with {g['label'].lower()} in {round(100 * g['need_met'])}% of the runs.")  # fmt: skip
    for x in res["reconsider"]:
        c.print(f"[yellow]![/yellow] Reconsider keeping {x['name']}: worth about {cr(x['worth'])} cr to your "
                f"squad, paid {cr(x['salary'])} cr"
                + (" (released only to open a place)" if x.get("auto_release") == "open" else "")
                + ". The plan never buys back your releases.")  # fmt: skip
    for w in ctx["warnings"]:
        c.print(f"[yellow]![/yellow] {w}")
    if not res["targets"]:
        c.print("[yellow]![/yellow] No targets: no open places or no purse left. Release players "
                "(--release, or --open N).")  # fmt: skip
    if assumed:
        c.print(
            f"[dim]Assumed, not confirmed: {', '.join(sorted(assumed))} (config/competitions.toml).[/dim]"
        )
    if csv_path:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(to_csv_rows(res))
        c.print(f"[dim]wrote {csv_path}[/dim]")
    _render.footnote(
        "Same keep.json + pool + optimiser as the web page (locked by test_bidplan_parity.py). "
        "--keep / --release / --open shape the squad; --need, --max and --purse change the plan."
    )
