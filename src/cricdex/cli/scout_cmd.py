"""`cricdex scout` — graph-traversal player similarity queries."""

from __future__ import annotations

import typer

from cricdex.cli._shared import die, render_table, resolve_or_die

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _similar():
    try:
        from cricdex.scout.graph import similar

        return similar
    except ImportError as e:
        die(
            f"neo4j extra not installed ({e})",
            hint="run `uv sync --extra graph` and ensure Neo4j is up "
            "(`make docker-scout-up && cricdex data ingest graph -c ipl`)",
        )


@app.command("twins", help="Graph cohort — co-faced bowlers or teammate overlap.")
def twins(
    name: str = typer.Argument(..., help="player name (fuzzy-matched)"),
    mode: str = typer.Option("co_faced", "--mode", help="co_faced | teammates"),
    top_k: int = typer.Option(10, "-k", "--top-k"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    s = _similar()
    name = resolve_or_die(name, collection=collection)
    if mode == "co_faced":
        rows = s.co_faced_bowlers(name, top_k=top_k)
    elif mode == "teammates":
        rows = s.teammate_overlap(name, top_k=top_k)
    else:
        die(f"unknown mode `{mode}` — use co_faced or teammates")
    if not rows:
        die("no cohort returned — graph populated for this collection?")
    render_table(rows, title=f"{mode} cohort for {name}")


@app.command("find-replacement", help="Auto-flip role-aware twin search.")
def find_replacement(
    name: str = typer.Argument(...),
    top_k: int = typer.Option(10, "-k", "--top-k"),
    role: str | None = typer.Option(None, "--role", help="bowler|batter|all_rounder"),
    style: str | None = typer.Option(
        None,
        "--style",
        help="bowling style filter (pace | spin). Curated map + middle-overs heuristic.",
    ),
    max_balls_bowled: int | None = typer.Option(None, "--max-balls-bowled"),
    max_balls_faced: int | None = typer.Option(None, "--max-balls-faced"),
    min_last_match: str | None = typer.Option(None, "--min-last-match"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    s = _similar()
    name = resolve_or_die(name, collection=collection)
    rows = s.find_replacement(
        name,
        top_k=top_k,
        role=role,
        max_balls_bowled=max_balls_bowled,
        max_balls_faced=max_balls_faced,
        min_last_match_date=min_last_match,
        bowling_style=style,
    )
    if not rows:
        die("no candidates — relax filters or check spelling")
    render_table(rows, title=f"replacement candidates for {name}")
