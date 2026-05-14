"""Top-level one-shot commands: profile / compare / records / venues /
match-report / translate."""

from __future__ import annotations

import typer

from cricdex.cli._shared import (
    EXIT_MISSING_CRED,
    console,
    die,
    render_kv,
    render_table,
    resolve_or_die,
)


def profile(
    name: str = typer.Argument(..., help="player name (fuzzy-matched against collection)"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.profiles import builder

    name = resolve_or_die(name, collection=collection)
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

    a = resolve_or_die(a, collection=collection)
    b = resolve_or_die(b, collection=collection)
    df = cmp.compare([a, b], collection=collection)
    if df.is_empty():
        die("comparator returned no rows")
    # Transpose so each player is a column for a side-by-side terminal view.
    pdf = df.to_pandas().set_index("player").T.reset_index().rename(columns={"index": "metric"})
    render_table(pdf.to_dict(orient="records"), title=f"{a} vs {b}")


def records(
    key: str = typer.Argument("today", help="`today` or a record key (run `cricdex records list`)"),
    collection: str = typer.Option("ipl", "--collection", "-c"),
    top_n: int = typer.Option(25, "--top-n"),
) -> None:
    import datetime as _dt

    from cricdex.records import queries

    if key == "today":
        today = _dt.date.today()
        df = queries.on_this_day(month=today.month, day=today.day, collection=collection)
        rows = df.to_dicts() if hasattr(df, "to_dicts") else df
        if not rows:
            console().print(
                f"[dim]nothing notable on {today.month:02d}-{today.day:02d} in {collection}.[/dim]"
            )
            return
        render_table(rows, title=f"on-this-day {today.month:02d}-{today.day:02d} ({collection})")
        return
    if key == "list":
        # Try a few naming conventions — `RECORD_KEYS`, `RECORDS`, or fall back
        # to introspecting `top` callees.
        keys = (
            getattr(queries, "RECORD_KEYS", None)
            or getattr(queries, "RECORDS", None)
            or sorted(
                name
                for name in dir(queries)
                if not name.startswith("_") and name not in {"on_this_day", "top"}
            )
        )
        render_table([{"key": k} for k in keys], title="record keys")
        return
    fn = getattr(queries, key, None)
    if not callable(fn):
        die(f"unknown record key `{key}` — try `cricdex records list`")
    df = fn(collection=collection, top_n=top_n)
    rows = df.to_dicts() if hasattr(df, "to_dicts") else df
    render_table(rows, title=f"{key} top-{top_n} ({collection})")


def venues(
    venue: str = typer.Argument(...),
    collection: str = typer.Option("ipl", "--collection", "-c"),
) -> None:
    from cricdex.venues import profile as v

    c = console()
    c.print(f"\n[bold cyan]{venue}[/bold cyan]  ({collection})\n")
    try:
        innings = v.innings_totals(venue, collection)
        if not innings.is_empty():
            c.print("[bold]Innings totals[/bold]")
            render_table(innings.to_dicts())
        phases = v.phase_run_rates(venue, collection)
        if not phases.is_empty():
            c.print("\n[bold]Phase run rates[/bold]")
            render_table(phases.to_dicts())
        chase = v.chase_vs_set_winrate(venue, collection)
        if not chase.is_empty():
            c.print("\n[bold]Chase vs set win rate[/bold]")
            render_table(chase.to_dicts())
    except Exception as e:
        die(f"venue lookup failed: {e}")


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
