"""`cricdex auction room` — web-identical real-rules IPL auction.

A real-rules IPL Monte-Carlo read from the same exported pool/retentions and
computed with `cricdex.web_parity` (locked to the web by `test_web_parity.py`).
"""

from __future__ import annotations

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import EXIT_USER_ERROR, die

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
        load_auction_pool,
        load_retentions,
        simulate_auction,
    )

    if mode not in ("mega", "mini"):
        die("--mode must be `mega` or `mini`", code=EXIT_USER_ERROR)
    try:
        pool = build_pool(load_auction_pool("ipl"))
        ret = load_retentions("ipl")
    except FileNotFoundError as e:
        die(str(e), code=EXIT_USER_ERROR)

    mega_ids = {t: [r["cricsheet_id"] for r in rows] for t, rows in ret["mega"].items()}
    real_prices = {r["cricsheet_id"]: r["price"] for rows in ret["mega"].values() for r in rows}
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
            "real_prices": real_prices,
        },
    )

    _render.header(
        f"Auction room — {mode} Monte-Carlo",
        subtitle=f"{res['pool_size']} under the hammer  ·  purse {purse:.0f} cr  ·  {trials} runs",
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
                "player": m["player"]["name"],
                "role": m["player"]["role"].replace("_", "-"),
                "value": round(m["player"]["projected_value"], 1),
                "most_likely": ", ".join(f"{w['team']} {w['pct']:.0f}%" for w in m["winners"])
                or "unsold",
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
