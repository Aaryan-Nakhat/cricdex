"""`cricdex auction room` — web-identical real-rules IPL auction.

A real-rules IPL Monte-Carlo read from the same exported pool/retentions and
computed with `cricdex.web_parity` (locked to the web by `test_web_parity.py`).
"""

from __future__ import annotations

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import EXIT_USER_ERROR, die
from cricdex.common.display import display_name

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("room", help="Real-rules IPL auction Monte-Carlo — identical to the web Auction room.")
def room(
    mode: str = typer.Option("mega", "--mode", help="mega | mini"),
    purse: float | None = typer.Option(None, "--purse", help="default 120 (mega) / 30 (mini)"),
    squad_size: int = typer.Option(25, "--squad-size"),
    overseas_cap: int = typer.Option(8, "--overseas-cap"),
    trials: int = typer.Option(300, "--trials"),
    top_n: int = typer.Option(20, "--top-n", help="marquee names to show"),
) -> None:
    from cricdex.web_parity import (
        IPL_TEAMS_DEFAULT,
        build_pool,
        default_retentions,
        load_activity_index,
        load_auction_pool,
        load_retentions,
        retention_inputs,
        simulate_auction,
    )

    if mode not in ("mega", "mini"):
        die("--mode must be `mega` or `mini`", code=EXIT_USER_ERROR)
    try:
        raw = load_auction_pool("ipl")
        pool = build_pool(raw)
        ret = load_retentions("ipl")
    except FileNotFoundError as e:
        die(str(e), code=EXIT_USER_ERROR)

    shown = {r["cricsheet_id"]: display_name(r) for r in raw}  # fan-facing names
    # a rating resting on stale SMAT data says so: "SMAT data to Dec 2024 · 85%" (issue I7)
    from cricdex.web_parity.keep import STALE_REASON_MIN

    stale = {
        r["cricsheet_id"]: f"{r['stale_note']} · {round(100 * r['stale_share'])}%"
        for r in raw
        if r.get("stale_note") and (r.get("stale_share") or 0) >= STALE_REASON_MIN
    }
    ri = retention_inputs(ret)  # the real 2025 lists, prices and the slab rule they cost
    mega_ids = ri["mega_ids"]
    act = load_activity_index("ipl")  # cid -> last-IPL / age / ipl_relevance
    if purse is None:
        purse = 120.0 if mode == "mega" else 30.0
    retentions = default_retentions(pool, IPL_TEAMS_DEFAULT, mode, mega_ids)
    res = simulate_auction(
        pool,
        IPL_TEAMS_DEFAULT,
        {
            "purse": purse,
            "squad_size": squad_size,
            "overseas_cap": overseas_cap,
            "trials": trials,
            "mode": mode,
            "retentions": retentions,
            "real_prices": ri["real_prices"],
            "retention_slabs": ri["retention_slabs"],
            "slab_holders": ri["slab_holders"],
            "fixed_retained": ri["fixed_retained"],
        },
    )

    _render.header(
        f"Auction room — {mode} Monte-Carlo",
        subtitle=f"{res['auctioned']} of {res['pool_size']} unretained under the hammer  ·  purse {purse:.0f} cr  ·  {trials} runs",
    )
    _render.intro_panel(_copy.AUCTION_SIMULATE_INTRO, title="Auction room")
    _render.pretty_table(
        [
            {
                "team": t["team"],
                "personality": t["personality"],
                "retained": t["retained"],
                "bought": round(t["avg_bought"]),
                "spend_cr": round(t["avg_spend"], 1),
                "squad_value": round(t["avg_value"], 1),
                "overseas": round(t["avg_overseas"]),
            }
            for t in sorted(res["teams"], key=lambda t: t["avg_value"], reverse=True)
        ],
        title="How each squad shapes up",
        column_styles={"team": "bold cyan"},
    )
    _render.pretty_table(
        [
            {
                "player": shown.get(m["player"]["cricsheet_id"]) or m["player"]["name"],
                "role": m["player"]["role"].replace("_", "-"),
                "value": round(m["player"]["projected_value"], 1),
                "ipl_fit": (
                    f"{round(act[m['player']['cricsheet_id']]['ipl_relevance'] * 100)}%"
                    if m["player"]["cricsheet_id"] in act
                    else "—"
                ),
                "last_ipl": (act.get(m["player"]["cricsheet_id"], {}).get("last_ipl") or "never")[
                    :4
                ],
                "most_likely": ", ".join(f"{w['team']} {w['pct']:.0f}%" for w in m["winners"])
                or "unsold",
                "stale": stale.get(m["player"]["cricsheet_id"]),
            }
            for m in res["marquee"][:top_n]
        ],
        title="Who lands the marquee names",
        column_styles={"player": "bold cyan"},
    )
    _render.footnote(
        "Same exported pool + retentions + seeded Monte-Carlo as the web "
        "(locked by test_web_parity.py)."
    )
