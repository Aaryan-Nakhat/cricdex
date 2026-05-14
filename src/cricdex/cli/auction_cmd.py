"""`cricdex auction` — solve / recommend / simulate / train-grpo.

Renderers mirror the Streamlit Auction + Auction-Simulator pages:
explainer panel, summary line, primary table, footnote with refresh
hint.
"""

from __future__ import annotations

from pathlib import Path

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import EXIT_USER_ERROR, console, die

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("solve", help="MILP squad optimiser over a player pool.")
def solve(
    pool: str = typer.Option("real", "--pool", help="real | synthetic | <csv path>"),
    purse: float = typer.Option(120.0, "--purse"),
    squad_size: int = typer.Option(25, "--squad-size"),
    overseas_cap: int = typer.Option(8, "--overseas-cap"),
    keeper_min: int | None = typer.Option(
        None,
        "--keeper-min",
        help="Minimum keepers (default 2 on synthetic / 0 on real-pool — "
        "real pool has no keeper-role tag yet, deferred to vNext).",
    ),
) -> None:
    import polars as pl

    from cricdex.auction import real_pool, solver

    if pool == "real":
        df = real_pool.build_pool()
        if keeper_min is None:
            keeper_min = 0
    elif pool == "synthetic":
        df = solver.sample_pool()
        if keeper_min is None:
            keeper_min = 2
    else:
        p = Path(pool)
        if not p.exists():
            die(f"no such file: {pool}", code=EXIT_USER_ERROR)
        df = pl.read_csv(p)
        if keeper_min is None:
            keeper_min = 0
    role_mins = {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": keeper_min}

    _render.header(
        "Auction — MILP squad solve",
        subtitle=f"pool: {pool}  ·  purse: {purse:.1f} cr  ·  squad-size: {squad_size}",
    )
    _render.intro_panel(_copy.AUCTION_SOLVE_INTRO, title="Auction")

    with _render.spinner("solving MILP"):
        res = solver.solve(
            df,
            purse=purse,
            squad_size=squad_size,
            overseas_cap=overseas_cap,
            role_mins=role_mins,
        )
    if not res["feasible"]:
        die(f"infeasible: {res.get('reason')}", code=EXIT_USER_ERROR)
    _render.kv_grid(
        {
            "Total price (cr)": f"{res['total_price']:.2f}",
            "Total projected value": f"{res['total_value']:.2f}",
            "Squad size": squad_size,
            "Overseas cap": overseas_cap,
        },
        title="Solution",
        cols=4,
    )
    _render.pretty_table(res["selected"].to_dicts(), title="Selected XV")
    _render.footnote(
        "Constraints: budget + squad-size + per-role minimums + overseas cap. "
        "Maximises total projected value."
    )


@app.command("recommend", help="War-room substitute advisor.")
def recommend(
    target: str = typer.Argument(...),
    budget: float = typer.Option(..., "--budget"),
    role: str | None = typer.Option(None, "--role"),
    style: str | None = typer.Option(
        None,
        "--style",
        help="bowling style filter for bowler replacements (pace | spin).",
    ),
    n: int = typer.Option(5, "-n", "--top-n"),
    min_last_match: str = typer.Option("2023-01-01", "--min-last-match"),
) -> None:
    from cricdex.auction import advisor

    _render.header(
        f"War-room advisor — substitute for {target}",
        subtitle=f"budget: {budget:.1f} cr  ·  top-{n}",
    )
    _render.intro_panel(_copy.AUCTION_RECOMMEND_INTRO, title="Recommend")
    if role:
        console().print(f"[dim]filter:[/dim] role = [bold]{role}[/bold]")
    if style:
        console().print(f"[dim]filter:[/dim] bowling style = [bold]{style}[/bold]")

    with _render.spinner(f"finding substitutes for {target}"):
        rec = advisor.recommend_substitutes(
            target,
            budget=budget,
            role=role,
            n=n,
            min_last_match_date=min_last_match,
            bowling_style=style,
        )
    if rec.is_empty():
        die("no affordable graph-similar candidates")
    _render.pretty_table(
        rec.to_dicts(),
        title=f"Substitutes for {target} @ {budget:.1f} cr",
        column_styles={"name": "bold cyan"},
    )
    _render.footnote("Composite score = graph similarity × Bayes value × role match × budget fit.")


@app.command("simulate", help="Monte-Carlo auction price-band sim.")
def simulate(
    n_sims: int = typer.Option(200, "--n-sims"),
    n_franchises: int = typer.Option(10, "--n-franchises"),
    purse: float = typer.Option(90.0, "--purse"),
    top_n: int = typer.Option(20, "--top-n"),
) -> None:
    from cricdex.auction import real_pool, simulator

    _render.header(
        "Auction simulator — Monte-Carlo",
        subtitle=f"n_sims: {n_sims}  ·  franchises: {n_franchises}  ·  purse: {purse:.1f}",
    )
    _render.intro_panel(_copy.AUCTION_SIMULATE_INTRO, title="Simulate")

    pool = real_pool.build_pool()
    franchises = [
        {"id": f"F{i + 1}", "purse": purse, "aggression": 1.0, "risk": 0.15}
        for i in range(n_franchises)
    ]
    with _render.spinner(f"running {n_sims} Monte-Carlo sims"):
        result = simulator.simulate(pool, franchises=franchises, n_sims=n_sims)
    df = result["per_player"].head(top_n)
    _render.pretty_table(df.to_dicts(), title=f"Price distribution (top {top_n})")
    _render.footnote(
        "Per-player columns: mean_price · price_p10 · price_p90 · sold_pct  "
        "(across all simulations)."
    )


@app.command("train-grpo", help="Train the GRPO auction self-play policy.")
def train_grpo(
    pool: str = typer.Option("real", "--pool", help="real | synthetic"),
    epochs: int = typer.Option(8000, "--epochs"),
    group_size: int = typer.Option(16, "--group-size"),
    n_franchises: int = typer.Option(6, "--n-franchises"),
    diverse_franchises: bool = typer.Option(True, "--diverse-franchises/--uniform-franchises"),
    out: Path = typer.Option(None, "--out"),
) -> None:
    from cricdex.auction import grpo, real_pool, solver
    from cricdex.config import DATA_DIR

    _render.header(
        "GRPO auction self-play",
        subtitle=f"pool: {pool}  ·  epochs: {epochs}  ·  group: {group_size}",
    )
    pool_df = real_pool.build_pool() if pool == "real" else solver.sample_pool()
    franchises = real_pool.FRANCHISE_ARCHETYPES[:n_franchises] if diverse_franchises else None
    out_path = out or DATA_DIR / "auction" / "policy.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    grpo.train(
        pool_df,
        epochs=epochs,
        group_size=group_size,
        n_franchises=n_franchises,
        out_path=out_path,
        franchises=franchises,
    )
    console().print(f"[bold]wrote policy →[/bold] {out_path}")
