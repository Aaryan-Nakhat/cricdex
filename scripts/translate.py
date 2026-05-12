"""CLI: translate English commentary into a target language.

Examples:
    uv run python scripts/translate.py "Bumrah bowls a fast yorker" --target hi
    cat snippet.txt | uv run python scripts/translate.py --target ta
"""

from __future__ import annotations

import sys

import typer
from loguru import logger

from cricdex.commentary_translate import translate as tr

app = typer.Typer(add_completion=False)


@app.command()
def go(
    text: str = typer.Argument("", help="English commentary; reads stdin if empty"),
    target: str = typer.Option("hi", "--target", "-t"),
) -> None:
    if not text:
        text = sys.stdin.read()
    if not text.strip():
        logger.error("no input text supplied")
        raise typer.Exit(code=2)
    typer.echo(tr.translate(text, target=target))


if __name__ == "__main__":
    app()
