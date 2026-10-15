"""CLI smoke tests over the committed site data (no DuckDB needed)."""

from __future__ import annotations

import json
import re

from typer.testing import CliRunner

from cricdex.cli import app
from cricdex.config import SITE_DATA

# CI terminals get coloured output, whose escape codes split words like "--pos"; plain text, wide, no colour.
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"})
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _run(*args):
    r = runner.invoke(app, list(args))
    return r.exit_code, _ANSI.sub("", r.output)


def test_help_lists_the_commands():
    code, out = _run("--help")
    assert code == 0
    for cmd in ("leaderboard", "profile", "compare", "records", "scout", "auction", "data", "tui"):
        assert cmd in out


def test_leaderboard_reads_the_exported_board():
    top = json.loads((SITE_DATA / "ipl" / "leaderboards" / "ngi.json").read_text(encoding="utf-8"))[
        0
    ]
    code, out = _run("leaderboard", "ngi", "-c", "ipl", "--top", "3")
    assert code == 0, out
    assert top["name"] in out


def test_unknown_data_slice_is_a_user_error():
    code, _ = _run("data", "ingest", "not-a-slice")
    assert code == 1


def test_documented_options_exist():
    # the options the docs show for scout and auction (they once listed a -c that didn't exist)
    code, out = _run("scout", "look-alikes", "--help")
    assert code == 0 and "--pos" in out and "-c" not in out.split("Options")[-1].split()
    code, out = _run("auction", "room", "--help")
    assert code == 0
    for opt in ("--mode", "--purse", "--squad-size", "--overseas-cap", "--trials", "--top-n"):
        assert opt in out
