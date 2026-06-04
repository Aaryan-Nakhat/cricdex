"""`cricdex scout` — player similarity.

`look-alikes` is the canonical, **web-identical** scout: 3-tier
cross-competition look-alikes (IPL / SMAT / BBL) read from the same exported
JSON and computed with `cricdex.web_parity` (locked to the web by
`test_web_parity.py`). `twins` / `find-replacement` are the advanced
Neo4j-graph relational views (require the `graph` extra + a populated graph).
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


def _detect_target_archetype(name: str, collection: str = "ipl") -> tuple[str, str]:
    """Read balls_bowled vs balls_faced off the Player node — same
    discriminator the graph queries use internally. Returns (archetype,
    bowling_style) where archetype ∈ {bowler, batter}."""
    try:
        from cricdex.scout.graph.schema import driver

        drv = driver()
        try:
            with drv.session() as s:
                row = s.run(
                    "MATCH (p:Player {unique_name: $name, collection: $collection}) "
                    "RETURN p.balls_bowled AS bb, p.balls_faced AS bf, "
                    "p.bowling_style AS style",
                    name=name,
                    collection=collection,
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


@app.command(
    "look-alikes",
    help="3-tier cross-competition look-alikes (IPL/SMAT/BBL) — identical to the web Scout.",
)
def look_alikes(
    name: str = typer.Argument(..., help="active IPL player (fuzzy-matched)"),
    role: str | None = typer.Option(None, "--role", help="override match role"),
    pos: str | None = typer.Option(None, "--pos", help="batting slot filter (opener…tailender)"),
    top_k: int = typer.Option(8, "-k", "--top-k"),
) -> None:
    from cricdex.web_parity import (
        est_value,
        gem_threshold,
        is_gem,
        load_scout_index,
        similar_to,
    )

    try:
        idx = load_scout_index("ipl")
    except FileNotFoundError as e:
        die(str(e), hint="run `uv run python scripts/export_site.py` to cook the indices")

    name = resolve_or_die(name, collection="ipl")
    sel = next((p for p in idx["ipl"] if p["name"] == name), None)
    if sel is None:
        die(f"{name} isn't in the active IPL scout index (too few balls / inactive).")

    use_role = role or sel["role"]
    use_pos = pos or ""
    sel_price = est_value(sel["value"], sel["role"], "ipl")
    gem_med = gem_threshold(idx["smat"])

    _render.header(
        f"Scout — look-alikes for {name}",
        subtitle=f"role: {use_role}  ·  standing: {sel['z']:.2f}  ·  est ≈ {sel_price:.1f} cr",
    )
    _render.intro_panel(_copy.TWINS_INTRO, title="Scout")

    titles = {
        "ipl": "IPL peers",
        "smat": "Uncapped · SMAT",
        "bbl": "Overseas · BBL",
        "sa20": "Overseas · SA20",
        "cpl": "Overseas · CPL",
        "blast": "Overseas · T20 Blast",
    }
    for tier in ("ipl", "smat", "bbl", "sa20", "cpl", "blast"):
        rows = []
        for r in similar_to(sel, idx[tier], use_role, use_pos)[:top_k]:
            price = est_value(r["value"], r["role"], tier)
            saving = sel_price - price if price < sel_price else 0.0
            rows.append(
                {
                    "name": r["name"],
                    "country": r.get("country") or "—",
                    "last": (r.get("last_match_date") or "")[:4],
                    "est_cr": round(price, 1),
                    "save_cr": round(saving, 1) if saving > 0 else "",
                    "sim%": round(r["sim"] * 100),
                    "gem": "💎" if (tier == "smat" and is_gem(r, gem_med)) else "",
                }
            )
        if rows:
            _render.pretty_table(rows, title=titles[tier], column_styles={"name": "bold cyan"})
        else:
            console().print(f"[dim]{titles[tier]}: no close match of this archetype.[/dim]")
    _render.footnote(
        "Same data + logic as the web Scout (locked by test_web_parity.py). est_cr = the "
        "auction's skill→price curve (tier-discounted); 💎 = uncapped gem (high standing, low "
        "exposure). The graph `twins` / `find-replacement` below are the advanced relational views."
    )


@app.command("twins", help="[advanced] Graph cohort — co-faced bowlers or teammate overlap.")
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

    archetype, style = _detect_target_archetype(name, collection)
    console().print(
        f"[dim]auto-detected archetype:[/dim] [bold]{archetype}[/bold]  "
        f"[dim]·  bowling style:[/dim] [bold]{style}[/bold]"
    )

    with _render.spinner(f"querying graph ({mode})"):
        if mode == "co_faced":
            rows = s.co_faced_bowlers(name, top_k=top_k, collection=collection)
        elif mode == "teammates":
            rows = s.teammate_overlap(name, top_k=top_k, collection=collection)
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


@app.command("find-replacement", help="[advanced] Auto-flip role-aware graph twin search.")
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

    archetype, target_style = _detect_target_archetype(name, collection)
    console().print(
        f"[dim]auto-detected archetype:[/dim] [bold]{archetype}[/bold]  "
        f"[dim]·  bowling style:[/dim] [bold]{target_style}[/bold]"
    )
    if style:
        console().print(f"[dim]filter:[/dim] bowling style = [bold]{style}[/bold]")
    if role:
        console().print(f"[dim]filter:[/dim] role = [bold]{role}[/bold]")

    with _render.spinner("searching for replacement candidates"):
        rows = s.find_replacement(
            name,
            top_k=top_k,
            role=role,
            max_balls_bowled=max_balls_bowled,
            max_balls_faced=max_balls_faced,
            min_last_match_date=min_last_match,
            bowling_style=style,
            collection=collection,
        )
    if not rows:
        die("no candidates — relax filters or check spelling")

    title = f"replacement candidates  ({len(rows)} matched)"
    _render.pretty_table(rows, title=title, column_styles={"name": "bold cyan"})
    _render.footnote(
        "Ranked by shared FACED-cohort size; archetype-locked to the "
        "target via balls_bowled vs balls_faced ratio."
    )
