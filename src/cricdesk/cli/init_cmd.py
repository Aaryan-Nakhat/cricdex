"""`cricdesk init` — first-run wizard.

Walks a fresh user through: (1) creating $CRICDESK_HOME (config.toml), (2) optional
LLM model + key entry, (3) the next commands to run. From a cloned repo the data stays in the
repo's data/ folder either way (see cricdesk.config.DATA_DIR).

Idempotent — re-running just re-prompts for missing pieces.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from cricdesk.cli._shared import console
from cricdesk.cli.config_cmd import _config_path, _read, _write


def run() -> None:
    c = console()
    c.print("[bold cyan]CricDesk first-run setup[/bold cyan]")
    home = Path(os.environ.get("CRICDESK_HOME", str(Path.home() / ".cricdesk")))
    home.mkdir(parents=True, exist_ok=True)
    (home / "data").mkdir(exist_ok=True)
    (home / "cache").mkdir(exist_ok=True)
    (home / "logs").mkdir(exist_ok=True)
    c.print(f"home: [green]{home}[/green]")

    cfg = _read()

    if not cfg.get("llm_model"):
        c.print(
            "\n[bold]LLM (optional)[/bold] — only for taxonomy enrichment "
            "(player role / seam-spin / country). Skip for metrics / scout / auction.\n"
            "Any LiteLLM model string: <provider>/<model>."
        )
        model = typer.prompt("LLM model (or hit Enter to skip)", default="", show_default=False)
        if model.strip():
            cfg["llm_model"] = model.strip()
            key = typer.prompt(
                "API key for that provider (Enter to use its usual env var)",
                default="",
                show_default=False,
                hide_input=True,
            )
            if key.strip():
                cfg["llm_api_key"] = key.strip()

    if cfg:
        _write(cfg)
        c.print(f"\nwrote [green]{_config_path()}[/green]")

    c.print("\n[bold]Next steps:[/bold]")
    c.print("  [cyan]cricdesk data status[/cyan]                     check what's on disk")
    c.print("  [cyan]cricdesk data ingest cricsheet -c ipl[/cyan]    fetch IPL ball-by-ball")
    c.print("  [cyan]cricdesk leaderboard ngi -c ipl[/cyan]           your first analytical query")
    c.print("  [cyan]cricdesk tui[/cyan]                              full interactive UI")
