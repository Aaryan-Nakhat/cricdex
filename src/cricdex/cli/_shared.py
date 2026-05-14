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
EXIT_MISSING_CRED = 3


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


def require_path(path, what: str, next_cmd: str) -> None:
    """Bail with a helpful message if `path` doesn't exist."""
    from pathlib import Path

    if not Path(path).exists():
        die(
            f"missing {what} at {path}",
            code=EXIT_MISSING_DATA,
            hint=f"run `{next_cmd}` first",
        )


def require_cred(key: str, *, label: str, set_cmd: str) -> str:
    """Bail with a helpful message if credential `key` is empty."""
    from cricdex.config import settings

    value = getattr(settings, key, "") or ""
    if not value:
        die(
            f"missing credential `{key}` ({label})",
            code=EXIT_MISSING_CRED,
            hint=f"`{set_cmd}` or set the env var {key.upper()}",
        )
    return value


def render_table(rows: list[dict], title: str | None = None) -> None:
    """Pretty-print a list of dict rows as a rich table."""
    from rich.table import Table

    if not rows:
        console().print("[dim](no rows)[/dim]")
        return
    table = Table(title=title, show_lines=False, header_style="bold cyan")
    cols = list(rows[0].keys())
    for col in cols:
        table.add_column(col)
    for r in rows:
        table.add_row(*(str(r.get(c, "")) for c in cols))
    console().print(table)


def render_kv(d: dict, title: str | None = None) -> None:
    """Pretty-print a flat dict as a 2-column key/value rich table."""
    from rich.table import Table

    table = Table(title=title, show_header=False, box=None)
    table.add_column(style="bold cyan")
    table.add_column()
    for k, v in d.items():
        table.add_row(str(k), str(v))
    console().print(table)
