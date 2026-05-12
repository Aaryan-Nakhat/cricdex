"""CLI: Cricbuzz live-score snapshots.

Examples:
    uv run python scripts/live.py snapshot
    uv run python scripts/live.py leanback 95562
"""

from __future__ import annotations

import json

import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.live import cricbuzz

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """CricDex live-feed CLI."""


@app.command()
def snapshot() -> None:
    out = cricbuzz.snapshot_to_disk(DATA_DIR / "live")
    if out is None:
        logger.warning(
            "Cricbuzz returned nothing — datacenter IP block likely. "
            "Run from a residential network or wire OAuth."
        )
        raise typer.Exit(code=1)
    logger.info(f"wrote {out}")
    typer.echo(out.read_text())


@app.command()
def leanback(match_id: str) -> None:
    data = cricbuzz.leanback(match_id)
    if data is None:
        logger.warning("Cricbuzz returned nothing — see snapshot caveat.")
        raise typer.Exit(code=1)
    typer.echo(json.dumps(data, indent=2))


if __name__ == "__main__":
    app()
