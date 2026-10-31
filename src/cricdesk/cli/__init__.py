"""CricDesk CLI — single entry point exposed as the `cricdesk` console script.

Subcommand groups, each mounted as its own typer app:

  cricdesk init                              one-shot first-run wizard
  cricdesk config set / get / edit / path    credential + setting store
  cricdesk data status / ingest              local data inventory + setup
  cricdesk leaderboard <metric>              novel-metric leaderboards
  cricdesk profile <name>                    per-player profile card
  cricdesk compare <a> <b>                   side-by-side comparator
  cricdesk records [today | <key>]           record book + on-this-day
  cricdesk venues <venue>                    pitch + conditions
  cricdesk matchups <name>                   batter-vs-bowler + pace/spin splits
  cricdesk phase [powerplay|middle|death]    phase specialists
  cricdesk form <metric>                     recent form vs career baseline
  cricdesk partnerships [<name>]             batter-pair stands
  cricdesk aging [--role batting|bowling]    performance-vs-age curves
  cricdesk scout look-alikes <name>          cross-competition look-alikes
  cricdesk auction room                      real-rules IPL auction sim
  cricdesk keep --team RCB                   Keep or release: retention calculator
  cricdesk bidplan --team RCB                Bid plan: whom to bid for at the auction, and how high
  cricdesk forecast <name> | --team RCB      Form forecast: value over the next 3 seasons
  cricdesk tui                               full Textual UI
  cricdesk dashboard                         optional Streamlit dashboard (`--extra ui`)

There is no PyPI package: clone the repo, `uv sync`, then run
`uv run cricdesk --help` from the repo root.
"""

from __future__ import annotations

from pathlib import Path

import typer

from cricdesk import __version__
from cricdesk.cli import (
    aging_cmd,
    auction_cmd,
    bidplan_cmd,
    config_cmd,
    data_cmd,
    forecast_cmd,
    form_cmd,
    init_cmd,
    keep_cmd,
    matchups_cmd,
    metrics_cmd,
    partnerships_cmd,
    phase_cmd,
    profile_cmd,
    scout_cmd,
)

app = typer.Typer(
    add_completion=True,
    # `invoke_without_command=True` lets the root callback fire when
    # the user types just `cricdesk` (no subcommand) — we use that to
    # launch the TUI by default instead of dumping --help.
    invoke_without_command=True,
    no_args_is_help=False,
    help="CricDesk — open cricket intelligence in your terminal.",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"cricdesk {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    version: bool = typer.Option(  # noqa: B008
        False, "--version", "-V", callback=_version_callback, is_eager=True
    ),
) -> None:
    """CricDesk root callback — `cricdesk` with no subcommand launches
    the TUI; `cricdesk --help` lists every subcommand."""
    if ctx.invoked_subcommand is not None:
        return
    # No subcommand → launch the Textual TUI.
    try:
        from cricdesk.cli.tui import run_tui
    except ImportError as e:
        typer.echo(
            f"TUI dependencies are missing — reinstall with `uv sync`. ({e})\n"
            f"Run `cricdesk --help` for the full command list."
        )
        raise typer.Exit(code=1) from e
    run_tui()


# Subcommands mounted as sub-apps.
app.add_typer(config_cmd.app, name="config", help="Manage credentials + settings.")
app.add_typer(data_cmd.app, name="data", help="Inventory + ingest local data.")
app.add_typer(
    scout_cmd.app, name="scout", help="Scout look-alikes (IPL, SMAT and every overseas league)."
)
app.add_typer(auction_cmd.app, name="auction", help="Real-rules IPL auction simulation.")

# Top-level conveniences — one-shot commands without a sub-namespace.
app.command(name="init", help="First-run wizard: creds + opt-in data setup.")(init_cmd.run)
app.command(name="leaderboard", help="Show a metric leaderboard.")(metrics_cmd.leaderboard)
app.command(name="profile", help="Per-player profile card.")(profile_cmd.profile)
app.command(name="compare", help="Side-by-side comparator.")(profile_cmd.compare)
app.command(name="records", help="Records + on-this-day.")(profile_cmd.records)
app.command(name="venues", help="Venue pitch + conditions.")(profile_cmd.venues)
app.command(name="matchups", help="Batter-vs-bowler head-to-heads + pace/spin splits.")(
    matchups_cmd.matchups
)
app.command(name="phase", help="Powerplay / middle / death specialists.")(phase_cmd.phase)
app.command(name="form", help="Recent-form vs career baseline per metric.")(form_cmd.form)
app.command(
    name="partnerships", help="Batter-pair stands (best partnerships + a player's partners)."
)(partnerships_cmd.partnerships)
app.command(name="aging", help="Performance-vs-age curves (batting / bowling).")(aging_cmd.aging)
app.command(name="keep", help="Keep or release: which players a franchise should retain, and why.")(
    keep_cmd.keep
)
app.command(
    name="bidplan", help="Bid plan: whom a franchise should bid for at the auction, and how high."
)(bidplan_cmd.bidplan)
app.command(name="forecast", help="Form forecast: a player's value over the next three seasons.")(
    forecast_cmd.forecast
)


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
            str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py"),
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
        from cricdesk.cli.tui import run_tui
    except ImportError as e:
        typer.echo(f"Textual TUI dependencies are missing — reinstall with `uv sync`. ({e})")
        raise typer.Exit(code=1) from e
    run_tui()


def main() -> None:
    """Entry point referenced by `[project.scripts] cricdesk = ...`."""
    app()


if __name__ == "__main__":
    main()
