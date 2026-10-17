"""Sanity-check the IPL mega auction on the exported data: purse use, squad sizes and the price spread.

Runs the real simulator (cricdex.web_parity, the same code as the website) with the real 2025
retentions, so a data rebuild or a pricing change can be checked before it ships: every team should
spend close to its purse, reach the minimum squad, and no price should pass the cap.

Example:
    uv run python scripts/auction_check.py               # site/public/data
    uv run python scripts/auction_check.py --trials 300
"""

from __future__ import annotations

import statistics

import typer

from cricdex.web_parity import (
    IPL_TEAMS_DEFAULT,
    build_pool,
    default_retentions,
    load_auction_pool,
    load_retentions,
    simulate_auction,
)

app = typer.Typer(add_completion=False)


@app.command()
def run(
    base: str | None = typer.Option(
        None, "--base", help="site data dir (default: site/public/data)"
    ),
    trials: int = typer.Option(100, "--trials"),
    purse: float = typer.Option(120.0, "--purse"),
) -> None:
    pool = build_pool(load_auction_pool("ipl", base))
    ret = load_retentions("ipl", base)
    mega_ids = {t: [r["cricsheet_id"] for r in rows] for t, rows in ret["mega"].items()}
    real_prices = {r["cricsheet_id"]: r["price"] for rows in ret["mega"].values() for r in rows}
    retentions = default_retentions(pool, IPL_TEAMS_DEFAULT, "mega", mega_ids)
    res = simulate_auction(
        pool,
        IPL_TEAMS_DEFAULT,
        {
            "purse": purse,
            "squad_size": 25,
            "overseas_cap": 8,
            "trials": trials,
            "mode": "mega",
            "retentions": retentions,
            "real_prices": real_prices,
        },
    )
    typer.echo(
        f"{'team':5} {'kept':>4} {'kept cr':>8} {'bought':>6} {'spent':>6} {'total':>6} {'left':>5} squad"
    )
    lefts = []
    for b, t in zip(res["bases"], res["teams"], strict=True):
        total = b["retain_spend"] + t["avg_spend"]
        lefts.append(purse - total)
        squad = t["retained"] + t["avg_bought"]
        typer.echo(
            f"{t['team']:5} {t['retained']:>4} {b['retain_spend']:>8.1f} {t['avg_bought']:>6.1f} "
            f"{t['avg_spend']:>6.1f} {total:>6.1f} {purse - total:>5.1f} {squad:.1f}"
        )
    typer.echo(f"average purse left: {statistics.mean(lefts):.1f} cr")
    prices = sorted((o["avgPrice"] for o in res["outcomes"] if o["status"] == "sold"), reverse=True)
    typer.echo(f"sold {len(prices)} · top prices {[round(p, 1) for p in prices[:8]]}")
    typer.echo(
        f"≥10 cr: {sum(p >= 10 for p in prices)} · ≥5 cr: {sum(p >= 5 for p in prices)} · <1 cr: {sum(p < 1 for p in prices)}"
    )
    top = sorted(pool, key=lambda p: -p["projected_value"])[:10]
    typer.echo(
        "top of the pool: " + ", ".join(f"{p['name']} {p['projected_value']:.1f}" for p in top)
    )


if __name__ == "__main__":
    app()
