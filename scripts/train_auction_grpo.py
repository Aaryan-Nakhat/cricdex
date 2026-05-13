"""CLI: train the GRPO auction self-play policy.

Examples (CPU smoke):
    uv run python scripts/train_auction_grpo.py --epochs 200 --group-size 8

Real training on the real IPL pool + heterogeneous franchise mix:
    uv run python scripts/train_auction_grpo.py \
        --pool real --epochs 8000 --group-size 16 --diverse-franchises
"""

from __future__ import annotations

from pathlib import Path

import typer
from loguru import logger

from cricdex.auction import grpo, real_pool, solver
from cricdex.config import DATA_DIR

app = typer.Typer(add_completion=False)


@app.command()
def train(
    epochs: int = typer.Option(200, "--epochs"),
    group_size: int = typer.Option(8, "--group-size"),
    n_franchises: int = typer.Option(4, "--n-franchises"),
    pool_size: int = typer.Option(40, "--pool-size"),
    purse: float = typer.Option(90.0, "--purse"),
    seed: int = typer.Option(42, "--seed"),
    pool: str = typer.Option(
        "synthetic",
        "--pool",
        help="'synthetic' (sample_pool, random) or 'real' (real_pool, Bayes-driven)",
    ),
    min_balls: int = typer.Option(
        200, "--min-balls", help="for --pool real: minimum IPL balls career"
    ),
    diverse_franchises: bool = typer.Option(
        False,
        "--diverse-franchises/--uniform-franchises",
        help="use the 6 real_pool.FRANCHISE_ARCHETYPES instead of uniform MC opponents",
    ),
    out: Path = typer.Option(DATA_DIR / "auction" / "policy.zip", "--out"),
) -> None:
    if pool == "real":
        pool_df = real_pool.build_pool(min_balls=min_balls)
        logger.info(
            f"real pool: {pool_df.height} players, "
            f"median projected_value={pool_df['projected_value'].median():.2f} cr"
        )
    else:
        pool_df = solver.sample_pool(n=pool_size, seed=seed)

    franchises = real_pool.FRANCHISE_ARCHETYPES[:n_franchises] if diverse_franchises else None

    logger.info(
        f"training GRPO policy: {epochs} epochs × {group_size} rollouts/group, "
        f"pool={pool}, diverse_franchises={diverse_franchises}"
    )
    result = grpo.train(
        pool_df,
        epochs=epochs,
        group_size=group_size,
        n_franchises=n_franchises,
        purse=purse,
        seed=seed,
        out_path=out,
        franchises=franchises,
    )
    logger.info(f"saved policy → {result['out_path']}")


if __name__ == "__main__":
    app()
