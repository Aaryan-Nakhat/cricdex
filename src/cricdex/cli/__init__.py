"""CricDex CLI — single entry point exposed as the `cricdex` console script.

Subcommand groups, each mounted as its own typer app:

  cricdex init                              one-shot first-run wizard
  cricdex config set / get / edit / path    credential + setting store
  cricdex data status / ingest              local data inventory + setup
  cricdex leaderboard <metric>              novel-metric leaderboards
  cricdex profile <name>                    per-player profile card
  cricdex compare <a> <b>                   side-by-side comparator
  cricdex records [today | <key>]           record book + on-this-day
  cricdex venues <venue>                    pitch + conditions
  cricdex rules ask "<question>"            citation-grounded rule QA
  cricdex scout twins <name>                graph cohort
  cricdex scout find-replacement <name>     auto-flip role-aware twins
  cricdex auction solve / recommend / simulate / train-grpo
  cricdex tui                               full Textual UI
  cricdex dashboard                         optional Streamlit on :8501

`uvx --from cricdex cricdex --help` or `pip install cricdex` + run
`cricdex --help` from anywhere.
"""

from __future__ import annotations

import typer

from cricdex import __version__
from cricdex.cli import (
    auction_cmd,
    config_cmd,
    data_cmd,
    init_cmd,
    metrics_cmd,
    profile_cmd,
    scout_cmd,
)

app = typer.Typer(
    add_completion=True,
    # `invoke_without_command=True` lets the root callback fire when
    # the user types just `cricdex` (no subcommand) — we use that to
    # launch the TUI by default instead of dumping --help.
    invoke_without_command=True,
    no_args_is_help=False,
    help="CricDex — open cricket intelligence in your terminal.",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"cricdex {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    version: bool = typer.Option(  # noqa: B008
        False, "--version", "-V", callback=_version_callback, is_eager=True
    ),
) -> None:
    """CricDex root callback — `cricdex` with no subcommand launches
    the TUI; `cricdex --help` lists every subcommand."""
    if ctx.invoked_subcommand is not None:
        return
    # No subcommand → launch the Textual TUI.
    try:
        from cricdex.cli.tui import run_tui
    except ImportError as e:
        typer.echo(
            f"TUI requires the `cli` extra (`uv sync --extra cli`). ({e})\n"
            f"Run `cricdex --help` for the full command list."
        )
        raise typer.Exit(code=1) from e
    run_tui()


# Subcommands mounted as sub-apps.
app.add_typer(config_cmd.app, name="config", help="Manage credentials + settings.")
app.add_typer(data_cmd.app, name="data", help="Inventory + ingest local data.")
app.add_typer(scout_cmd.app, name="scout", help="Scout look-alikes (IPL/SMAT/BBL/SA20/CPL/Blast).")
app.add_typer(auction_cmd.app, name="auction", help="Real-rules IPL auction simulation.")

# Top-level conveniences — one-shot commands without a sub-namespace.
app.command(name="init", help="First-run wizard: creds + opt-in data setup.")(init_cmd.run)
app.command(name="leaderboard", help="Show a metric leaderboard.")(metrics_cmd.leaderboard)
app.command(name="profile", help="Per-player profile card.")(profile_cmd.profile)
app.command(name="compare", help="Side-by-side comparator.")(profile_cmd.compare)
app.command(name="records", help="Records + on-this-day.")(profile_cmd.records)
app.command(name="venues", help="Venue pitch + conditions.")(profile_cmd.venues)


@app.command(name="dashboard", help="Launch the Streamlit dashboard.")
def dashboard(
    port: int = typer.Option(
        0,
        "--port",
        "-p",
        help="Port to bind (0 = auto-pick a free one).",
    ),
) -> None:
    import socket
    import subprocess
    import sys

    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    bound = port if port else _free_port()
    typer.echo(f"Open http://localhost:{bound} — Ctrl-C to stop.")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/cricdex/dashboard/app.py",
            "--server.port",
            str(bound),
            "--server.headless",
            "true",
        ],
        check=False,
    )


@app.command(name="tui", help="Launch the interactive Textual TUI.")
def tui() -> None:
    try:
        from cricdex.cli.tui import run_tui
    except ImportError as e:
        typer.echo(f"Textual TUI requires `cli` extras — `uv sync --extra cli`. ({e})")
        raise typer.Exit(code=1) from e
    run_tui()


def main() -> None:
    """Entry point referenced by `[project.scripts] cricdex = ...`."""
    app()


if __name__ == "__main__":
    main()
