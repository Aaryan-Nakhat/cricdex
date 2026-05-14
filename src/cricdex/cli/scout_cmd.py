"""`cricdex scout` — graph-traversal player similarity queries.

CLI renderer mirrors the Streamlit Player Twins page: explainer panel,
auto-detected role line, archetype + style tag per candidate.
"""

from __future__ import annotations

import typer

from cricdex.cli import _copy, _render
from cricdex.cli._shared import console, die, resolve_or_die

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


def _detect_target_archetype(name: str) -> tuple[str, str]:
    """Read balls_bowled vs balls_faced off the Player node — same
    discriminator the graph queries use internally. Returns (archetype,
    bowling_style) where archetype ∈ {bowler, batter}."""
    try:
        from cricdex.scout.graph.schema import driver

        drv = driver()
        try:
            with drv.session() as s:
                row = s.run(
                    "MATCH (p:Player {unique_name: $name}) "
                    "RETURN p.balls_bowled AS bb, p.balls_faced AS bf, "
                    "p.bowling_style AS style",
                    name=name,
                ).single()
        finally:
            drv.close()
    except Exception:
        return ("unknown", "unknown")
    if row is None:
        return ("unknown", "unknown")
    bb = row.get("bb") or 0
    bf = row.get("bf") or 0
    archetype = "bowler" if bb > bf else "batter"
    style = row.get("style") or "—"
    return (archetype, style)


@app.command("twins", help="Graph cohort — co-faced bowlers or teammate overlap.")
def twins(
    name: str = typer.Argument(..., help="player name (fuzzy-matched)"),
    mode: str = typer.Option("co_faced", "--mode", help="co_faced | teammates"),
    top_k: int = typer.Option(10, "-k", "--top-k"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    s = _similar()
    name = resolve_or_die(name, collection=collection)

    _render.header(f"Player Twins — {name}", subtitle=f"mode: {mode}  ·  collection: {collection}")
    _render.intro_panel(_copy.TWINS_INTRO, title="Player Twins")

    archetype, style = _detect_target_archetype(name)
    console().print(
        f"[dim]auto-detected archetype:[/dim] [bold]{archetype}[/bold]  "
        f"[dim]·  bowling style:[/dim] [bold]{style}[/bold]"
    )

    if mode == "co_faced":
        rows = s.co_faced_bowlers(name, top_k=top_k)
    elif mode == "teammates":
        rows = s.teammate_overlap(name, top_k=top_k)
    else:
        die(f"unknown mode `{mode}` — use co_faced or teammates")
    if not rows:
        die("no cohort returned — graph populated for this collection?")

    title = f"{mode} cohort  ({len(rows)} candidates)"
    _render.pretty_table(rows, title=title, column_styles={"name": "bold cyan"})
    _render.footnote(
        "Same-archetype candidates only — bowler targets surface bowlers, "
        "batter targets surface batters (auto-flip on balls_bowled vs balls_faced)."
    )


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

    _render.header(f"Find replacement — {name}", subtitle=f"collection: {collection}")
    _render.intro_panel(_copy.FIND_REPLACEMENT_INTRO, title="Find replacement")

    archetype, target_style = _detect_target_archetype(name)
    console().print(
        f"[dim]auto-detected archetype:[/dim] [bold]{archetype}[/bold]  "
        f"[dim]·  bowling style:[/dim] [bold]{target_style}[/bold]"
    )
    if style:
        console().print(f"[dim]filter:[/dim] bowling style = [bold]{style}[/bold]")
    if role:
        console().print(f"[dim]filter:[/dim] role = [bold]{role}[/bold]")

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

    title = f"replacement candidates  ({len(rows)} matched)"
    _render.pretty_table(rows, title=title, column_styles={"name": "bold cyan"})
    _render.footnote(
        "Ranked by shared FACED-cohort size; archetype-locked to the "
        "target via balls_bowled vs balls_faced ratio."
    )
