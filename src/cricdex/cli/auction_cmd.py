"""`cricdex auction` — solve / recommend / simulate / train-grpo."""

from __future__ import annotations

from pathlib import Path

import typer

from cricdex.cli._shared import EXIT_USER_ERROR, die, render_table

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
        # Real pool has no keeper-role tag — default to 0 unless user
        # overrides explicitly. Otherwise the MILP is infeasible.
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

    res = solver.solve(
        df,
        purse=purse,
        squad_size=squad_size,
        overseas_cap=overseas_cap,
        role_mins=role_mins,
    )
    if not res["feasible"]:
        die(f"infeasible: {res.get('reason')}", code=EXIT_USER_ERROR)
    typer.echo(f"feasible squad — price {res['total_price']:.2f}  value {res['total_value']:.2f}")
    render_table(res["selected"].to_dicts(), title="selected XI")


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
    render_table(rec.to_dicts(), title=f"substitutes for {target} @ {budget:.1f} cr")


@app.command("simulate", help="Monte-Carlo auction price-band sim.")
def simulate(
    n_sims: int = typer.Option(200, "--n-sims"),
    n_franchises: int = typer.Option(10, "--n-franchises"),
    purse: float = typer.Option(90.0, "--purse"),
    top_n: int = typer.Option(20, "--top-n"),
) -> None:
    from cricdex.auction import real_pool, simulator

    pool = real_pool.build_pool()
    franchises = [
        {"id": f"F{i + 1}", "purse": purse, "aggression": 1.0, "risk": 0.15}
        for i in range(n_franchises)
    ]
    result = simulator.simulate(pool, franchises=franchises, n_sims=n_sims)
    df = result["per_player"].head(top_n)
    render_table(df.to_dicts(), title=f"price distribution (top {top_n})")


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
    typer.echo(f"wrote policy → {out_path}")
