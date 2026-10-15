"""Helpers shared by every CLI subcommand: rich console, exit codes,
config IO, error sugar."""

from __future__ import annotations

import os
import sys
import typing as t

import typer

# Exit codes — keep grep-able and matches docs/CLI.md.
EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_MISSING_DATA = 2
# 3 was "missing credential"; nothing raises it any more, so it is left unused.
EXIT_RUNTIME_ERROR = 4  # a pipeline step (ingest / metrics / export) failed


def _is_tty() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def console():
    """Cached rich.console.Console (falls back to plain prints when not TTY)."""
    from rich.console import Console

    return Console(no_color=not _is_tty(), highlight=False, soft_wrap=True)


def die(msg: str, code: int = EXIT_USER_ERROR, hint: str | None = None) -> t.NoReturn:
    """Print an error with optional hint then exit with the given code."""
    c = console()
    c.print(f"[red bold]error:[/red bold] {msg}")
    if hint:
        c.print(f"[dim]hint:[/dim] {hint}")
    raise typer.Exit(code=code)


def render_table(
    rows: list[dict],
    title: str | None = None,
    max_col_width: int = 28,
) -> None:
    """Pretty-print a list of dict rows as a rich table.

    Tweaks for wide-terminal use:
    - `expand=True` so the table fills available terminal width.
    - `max_col_width` caps individual columns so a long name doesn't
      starve the rest.
    - rounded box style + no row separators for compact reading.
    """
    from rich import box
    from rich.table import Table

    if not rows:
        console().print("[dim](no rows)[/dim]")
        return
    table = Table(
        title=title,
        title_style="bold",
        show_lines=False,
        header_style="bold cyan",
        box=box.ROUNDED,
        expand=True,
        pad_edge=False,
    )
    cols = list(rows[0].keys())
    for col in cols:
        table.add_column(col, overflow="fold", max_width=max_col_width, no_wrap=False)
    for r in rows:
        table.add_row(*(str(r.get(c, "")) for c in cols))
    console().print(table)
    console().print("[dim]tip: run `cricdex tui` for an interactive view.[/dim]")


def sort_missing_last(rows: list[dict], col: str, higher_is_better: bool) -> list[dict]:
    """Sort leaderboard rows best-first on `col`; rows with no usable value
    (None, NaN, non-numeric) go last whichever way the metric points."""

    def num(v: object) -> float | None:
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return None if f != f else f

    present = [(n, r) for r in rows if (n := num(r.get(col))) is not None]
    missing = [r for r in rows if num(r.get(col)) is None]
    present.sort(key=lambda nr: nr[0], reverse=higher_is_better)
    return [r for _, r in present] + missing


def load_players(collection: str) -> list[dict] | None:
    """The exported `players.json` rows for `collection`, or None when the file
    is missing or unreadable (a fresh clone before `export_site.py`)."""
    import json

    from cricdex.config import SITE_DATA

    try:
        data = json.loads((SITE_DATA / collection / "players.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return [p for p in data if isinstance(p, dict) and p.get("name")]


def match_player(query: str, players: list[dict]) -> tuple[dict | None, list[dict]]:
    """Pick the one player a typed name means, without guessing.

    Order: exact scorecard or full name (case-insensitive), then a unique
    word-start prefix ("Bumr", "Jasp"), then a unique substring. Returns `(row, [])` for a single hit,
    `(None, candidates)` when several players fit (most matches first), and
    `(None, [])` when nothing does. Shared by the CLI and the TUI.
    """
    q = " ".join((query or "").split()).lower()
    if not q:
        return None, []

    def names(p: dict) -> list[str]:
        return [str(n).lower() for n in (p.get("name"), p.get("full_name")) if n]

    def by_matches(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda p: -(p.get("matches") or 0))

    exact = [p for p in players if q in names(p)]
    if exact:
        return (exact[0], []) if len(exact) == 1 else (None, by_matches(exact))

    def starts_a_word(n: str) -> bool:  # "bumr" / "jasp" / "kohli" — the start of any word
        return n.startswith(q) or f" {q}" in n

    for fits in (starts_a_word, lambda n: q in n):
        hits = [p for p in players if any(fits(n) for n in names(p))]
        if len(hits) == 1:
            return hits[0], []
        if hits:
            return None, by_matches(hits)
    return None, []


def player_label(p: dict) -> str:
    """'RG Sharma (Rohit Sharma)' — the scorecard name plus the full name when different."""
    name, full = p.get("name", ""), p.get("full_name")
    return f"{name} ({full})" if full and full != name else name


def _close_names(query: str, players: list[dict], k: int = 3) -> list[str]:
    from rapidfuzz import fuzz, process

    by_label = {}
    for p in players:
        for n in (p.get("name"), p.get("full_name")):
            if n:
                by_label.setdefault(str(n), p["name"])
    out: list[str] = []
    for label, _score, _ in process.extract(
        query, list(by_label), scorer=fuzz.WRatio, limit=k * 3, score_cutoff=60
    ):
        if by_label[label] not in out:
            out.append(by_label[label])
    return out[:k]


def resolve_or_die(query: str, collection: str = "ipl") -> str:
    """Turn a typed player name into the exact scorecard name, or exit.

    Looks in the exported `players.json` first (what the TUI and web use, so
    it works without the DuckDB) and only falls back to the live DuckDB when
    the export has no match. Several matches → lists them and exits 1 rather
    than picking one; no player list at all → exits 2 with how to get one.
    """
    from rich.markup import escape

    from cricdex.config import SITE_DATA
    from cricdex.profiles.identity import DEFAULT_DB_PATH, resolve_name

    c = console()
    players = load_players(collection)
    if players:
        row, candidates = match_player(query, players)
        if row:
            return row["name"]
        if candidates:
            c.print(
                f"[yellow]{escape(query)!r} matches {len(candidates)} players in "
                f"{collection}[/yellow] — which one?"
            )
            for i, p in enumerate(candidates[:10], 1):
                c.print(f"  [cyan]{i}[/cyan]  {escape(player_label(p))}")
            if len(candidates) > 10:
                c.print(f"  [dim]… and {len(candidates) - 10} more — type more of the name[/dim]")
            c.print(
                f'[dim]hint:[/dim] re-run with the full name in quotes, e.g. "{candidates[0]["name"]}"'
            )
            raise typer.Exit(code=EXIT_USER_ERROR)

    # Not in the export (or no export yet): the live DuckDB knows every player.
    has_db = DEFAULT_DB_PATH.exists()
    suggestions: list[str] = []
    if has_db:
        exact, matches = resolve_name(query, collection=collection)
        if exact:
            return exact
        suggestions = [m.name for m in matches]
    if players is None and not has_db:
        die(
            f"no player list for collection {collection!r}: "
            f"{SITE_DATA / collection / 'players.json'} is missing or unreadable, "
            "and there is no DuckDB to fall back on",
            code=EXIT_MISSING_DATA,
            hint=f"run `uv run python scripts/export_site.py -c {collection}` "
            f"(or `cricdex data ingest cricsheet -c {collection}`)",
        )
    if not suggestions and players:
        suggestions = _close_names(query, players)
    c.print(f"[yellow]no player matching[/yellow] {escape(query)!r} in {collection}")
    if suggestions:
        c.print("[bold]closest names:[/bold]")
        for i, s in enumerate(suggestions, 1):
            c.print(f"  [cyan]{i}[/cyan]  {escape(s)}")
        c.print(f'[dim]hint:[/dim] re-run with the exact name in quotes, e.g. "{suggestions[0]}"')
    else:
        c.print("[dim](no close names — check the spelling or the --collection)[/dim]")
    raise typer.Exit(code=EXIT_USER_ERROR)


def render_kv(d: dict, title: str | None = None) -> None:
    """Pretty-print a flat dict as a 2-column key/value rich table."""
    from rich.table import Table

    table = Table(title=title, show_header=False, box=None)
    table.add_column(style="bold cyan")
    table.add_column()
    for k, v in d.items():
        table.add_row(str(k), str(v))
    console().print(table)
