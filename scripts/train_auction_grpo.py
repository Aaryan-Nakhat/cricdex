"""CLI: train the GRPO auction self-play policy.

Example:
    uv run python scripts/train_auction_grpo.py --epochs 200 --group-size 8
"""

from __future__ import annotations

from pathlib import Path

import typer
from loguru import logger

from cricdex.auction import grpo, solver
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
    out: Path = typer.Option(DATA_DIR / "auction" / "policy.zip", "--out"),
) -> None:
    pool = solver.sample_pool(n=pool_size, seed=seed)
    logger.info(f"training GRPO policy: {epochs} epochs × {group_size} rollouts/group")
    result = grpo.train(
        pool,
        epochs=epochs,
        group_size=group_size,
        n_franchises=n_franchises,
        purse=purse,
        seed=seed,
        out_path=out,
    )
    logger.info(f"saved policy → {result['out_path']}")


if __name__ == "__main__":
    app()
