"""CLI: bootstrap + populate + query the scout Neo4j graph.

Examples:
    uv run python scripts/scout_graph.py bootstrap
    uv run python scripts/scout_graph.py populate --collection ipl
    uv run python scripts/scout_graph.py co-faced "V Kohli" -k 10
    uv run python scripts/scout_graph.py teammates "MS Dhoni" -k 10
"""

from __future__ import annotations

from pathlib import Path

import typer
from loguru import logger

from cricdex.scout.graph import schema, similar, writer

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Scout Neo4j graph CLI."""


@app.command("bootstrap")
def bootstrap_cmd() -> None:
    schema.bootstrap()
    logger.info("schema constraints + indexes ensured")


@app.command("populate")
def populate_cmd(
    collection: str = typer.Option("ipl", "--collection", "-c"),
    db_path: Path | None = typer.Option(None, "--db"),
) -> None:
    summary = writer.populate(
        collection=collection,
        db_path=db_path or writer.DEFAULT_DB_PATH,
    )
    logger.info(f"done: {summary}")


@app.command("co-faced")
def co_faced_cmd(
    name: str = typer.Argument(..., help="unique_name as stored on Player nodes"),
    top_k: int = typer.Option(10, "-k", "--top-k"),
) -> None:
    rows = similar.co_faced_bowlers(name, top_k=top_k)
    if not rows:
        typer.echo("no neighbours — verify the unique_name (case sensitive)")
        raise typer.Exit(code=1)
    typer.echo(f"Top-{top_k} players sharing FACED bowlers with {name}:")
    for r in rows:
        typer.echo(f"  {r['shared_bowlers']:4d}  {r['name']}  ({r['cricsheet_id']})")


@app.command("teammates")
def teammates_cmd(
    name: str = typer.Argument(..., help="unique_name as stored on Player nodes"),
    top_k: int = typer.Option(10, "-k", "--top-k"),
) -> None:
    rows = similar.teammate_overlap(name, top_k=top_k)
    if not rows:
        typer.echo("no neighbours — verify the unique_name (case sensitive)")
        raise typer.Exit(code=1)
    typer.echo(f"Top-{top_k} players sharing teammates with {name}:")
    for r in rows:
        typer.echo(f"  shared={r['shared_teammates']:3d}  weight={r['weight']:5d}  {r['name']}")


@app.command("find-replacement")
def find_replacement_cmd(
    name: str = typer.Argument(..., help="target player (e.g., 'JJ Bumrah')"),
    top_k: int = typer.Option(10, "-k", "--top-k"),
    role: str | None = typer.Option(None, "--role", help="bowler|batter|all_rounder"),
    max_balls_bowled: int | None = typer.Option(None, "--max-balls-bowled"),
    max_balls_faced: int | None = typer.Option(None, "--max-balls-faced"),
    min_last_match: str | None = typer.Option(
        None, "--min-last-match", help="YYYY-MM-DD — keep only candidates active after this"
    ),
) -> None:
    rows = similar.find_replacement(
        name,
        top_k=top_k,
        role=role,
        max_balls_bowled=max_balls_bowled,
        max_balls_faced=max_balls_faced,
        min_last_match_date=min_last_match,
    )
    if not rows:
        typer.echo("no candidates — relax filters or verify target name")
        raise typer.Exit(code=1)
    typer.echo(f"Replacement candidates for {name}:")
    for r in rows:
        typer.echo(
            f"  shared={r['shared']:4d}  role={r['role']:<11}  "
            f"bw={r['balls_bowled']:6d}  bt={r['balls_faced']:6d}  "
            f"last={r['last_match_date']}  {r['name']}"
        )


if __name__ == "__main__":
    app()
