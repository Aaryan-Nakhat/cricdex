"""CLI: cricket records + On-This-Day digest over a Cricsheet collection.

Examples:
    uv run python scripts/records.py list --collection ipl
    uv run python scripts/records.py top fastest_fifty --collection ipl --top-n 20
    uv run python scripts/records.py on-this-day 4 27 --collection ipl
    uv run python scripts/records.py all --collection ipl
"""

from __future__ import annotations

import datetime as dt

import typer
from loguru import logger

from cricdex.config import DATA_DIR
from cricdex.records import queries

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Cricket records CLI."""


@app.command("list")
def list_records() -> None:
    typer.echo("\n=== Available records ===\n")
    for name in queries.RECORDS:
        typer.echo(f"  {name}")


@app.command("top")
def top_cmd(
    record: str,
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top_n: int = typer.Option(25, "--top-n"),
) -> None:
    if record not in queries.RECORDS:
        logger.error(f"unknown record {record!r}. options: {sorted(queries.RECORDS)}")
        raise typer.Exit(code=2)
    df = queries.RECORDS[record](collection, top_n=top_n)
    typer.echo(f"\n=== {record} — {collection} (top {top_n}) ===\n")
    typer.echo(df.to_pandas().to_string(index=False))
    out_path = DATA_DIR / "records" / f"{record}_{collection}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_json(str(out_path))
    logger.info(f"wrote {out_path}")


@app.command("on-this-day")
def on_this_day_cmd(
    month: int = typer.Argument(..., min=1, max=12),
    day: int = typer.Argument(..., min=1, max=31),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top_n: int = typer.Option(50, "--top-n"),
) -> None:
    df = queries.on_this_day(month=month, day=day, collection=collection, top_n=top_n)
    typer.echo(f"\n=== On {month:02d}-{day:02d} — {collection} ({df.height} rows) ===\n")
    typer.echo(df.to_pandas().to_string(index=False))
    out_path = DATA_DIR / "records" / f"on_this_day_{month:02d}_{day:02d}_{collection}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_json(str(out_path))
    logger.info(f"wrote {out_path}")


@app.command("today")
def today_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top_n: int = typer.Option(25, "--top-n"),
) -> None:
    today = dt.date.today()
    on_this_day_cmd(month=today.month, day=today.day, collection=collection, top_n=top_n)


@app.command("all")
def all_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top_n: int = typer.Option(25, "--top-n"),
) -> None:
    for name, fn in queries.RECORDS.items():
        df = fn(collection, top_n=top_n)
        out_path = DATA_DIR / "records" / f"{name}_{collection}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.write_json(str(out_path))
        logger.info(f"{name}: {df.height} rows → {out_path}")


if __name__ == "__main__":
    app()
