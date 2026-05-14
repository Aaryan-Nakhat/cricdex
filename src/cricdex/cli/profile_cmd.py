"""Top-level one-shot commands: profile / compare / records / venues /
match-report / translate."""

from __future__ import annotations

import typer

from cricdex.cli._shared import EXIT_MISSING_CRED, console, die, render_kv, render_table


def profile(
    name: str = typer.Argument(..., help="player unique_name (case sensitive)"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.profiles import builder

    p = builder.build(name, collection)
    c = console()
    c.print(f"\n[bold cyan]{p.get('name', name)}[/bold cyan]")
    if p.get("ids"):
        c.print(f"[dim]{p['ids']}[/dim]")
    if p.get("career"):
        render_kv(p["career"], title="career totals")
    if p.get("bayes"):
        render_kv(p["bayes"], title="Bayes scout skill")
    twins_b = p.get("style_twins_batter") or []
    twins_k = p.get("style_twins_bowler") or []
    if twins_b:
        render_table(twins_b[:8], title="style twins (batter)")
    if twins_k:
        render_table(twins_k[:8], title="style twins (bowler)")


def compare(
    a: str = typer.Argument(...),
    b: str = typer.Argument(...),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.comparator import compare as cmp

    rows = cmp.side_by_side(a, b, collection=collection)
    render_table(rows, title=f"{a} vs {b}")


def records(
    key: str = typer.Argument("today", help="`today` or a record key (run `cricdex records list`)"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top_n: int = typer.Option(25, "--top-n"),
) -> None:
    from cricdex.records import queries

    if key == "today":
        rows = queries.on_this_day(collection=collection)
        render_table(rows, title=f"on-this-day {collection}")
        return
    if key == "list":
        render_table([{"key": k} for k in queries.RECORD_KEYS], title="record keys")
        return
    rows = queries.top(record=key, collection=collection, top_n=top_n)
    render_table(rows, title=f"{key} top-{top_n} ({collection})")


def venues(
    venue: str = typer.Argument(...),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.venues import profile as v

    res = v.venue_profile(venue, collection=collection)
    render_kv(res, title=f"venue: {venue}")


def match_report(
    match_id: str = typer.Argument(...),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.config import settings
    from cricdex.reports import match_report as mr

    if not (settings.gemini_api_key or settings.gemini_tmp_url):
        die(
            "no Gemini credential — `cricdex config set gemini_api_key <key>`",
            code=EXIT_MISSING_CRED,
        )
    path = mr.generate(match_id=match_id, collection=collection)
    typer.echo(path.read_text())


def translate(
    text: str = typer.Argument(...),
    to: str = typer.Option("hi", "--to", help="hi|ta|bn|ur|si|mr|te|kn"),
) -> None:
    from cricdex.commentary_translate import translate as t

    out = t.translate(text, target=to)
    typer.echo(out)
