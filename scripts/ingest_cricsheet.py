"""CLI: download a Cricsheet collection, write Parquet, load into DuckDB.

Which zip(s) a collection comes from is set in the league registry (config/leagues.toml).

Usage:
    uv run python scripts/ingest_cricsheet.py ingest --collection recently_played_30_male
    uv run python scripts/ingest_cricsheet.py all              # every exported league
    uv run python scripts/ingest_cricsheet.py list             # the registry's collections
"""

from __future__ import annotations

from pathlib import Path

import typer
from loguru import logger

from cricdex import leagues
from cricdex.scout.ingest import cricsheet

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Cricsheet ETL — any collection in the league registry."""


def _check(collection: str) -> str:
    try:
        return leagues.validate_collection(collection)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--collection") from None


@app.command()
def ingest(
    collection: str = typer.Option("recently_played_30_male", "--collection", "-c"),
    out: Path | None = typer.Option(None, "--out"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    # Single shared pipeline (cricsheet.build) so the script + the
    # `cricdex data ingest cricsheet` CLI can't drift. `extract` auto-reruns
    # when the downloaded zip is newer, so a refreshed Cricsheet is picked up.
    cricsheet.build(collection=_check(collection), out=out, force=force)


@app.command("all")
def ingest_all(
    out: Path | None = typer.Option(None, "--out"),
    force: bool = typer.Option(False, "--force"),
    include_unexported: bool = typer.Option(
        False, "--include-unexported", help="Also the registry leagues with export = false."
    ),
) -> None:
    """Ingest every exported league in the registry (stops at the first failure)."""
    keys = leagues.keys() if include_unexported else leagues.exported_keys()
    for key in keys:
        logger.info(f"=== {key} ===")
        cricsheet.build(collection=key, out=out, force=force)


@app.command("list")
def list_collections(
    exported: bool = typer.Option(False, "--exported", help="Only the exported leagues."),
) -> None:
    """Print the registry's collections with their Cricsheet zip(s)."""
    for lg in leagues.all():
        if exported and not lg.export:
            continue
        flag = "export" if lg.export else "-"
        typer.echo(f"{lg.key:28} {flag:7} {' + '.join(lg.zips):40} {lg.name}")


@app.command("indian-domestic", hidden=True)
def indian_domestic(
    out: Path | None = typer.Option(None, "--out"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Deprecated alias: SMAT now comes from Cricsheet's single `sma_json.zip` like any other
    collection. Same as `ingest --collection indian_domestic_male`."""
    logger.warning("`indian-domestic` is deprecated — use `ingest -c indian_domestic_male`")
    cricsheet.build(collection="indian_domestic_male", out=out, force=force)


if __name__ == "__main__":
    app()
