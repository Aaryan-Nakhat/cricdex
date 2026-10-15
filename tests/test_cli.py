"""CLI smoke tests over the committed site data (no DuckDB needed)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cricdex.cli import app
from cricdex.config import SITE_DATA

runner = CliRunner()


def test_help_lists_the_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for cmd in ("leaderboard", "profile", "compare", "records", "scout", "auction", "data", "tui"):
        assert cmd in r.output


def test_leaderboard_reads_the_exported_board():
    top = json.loads((SITE_DATA / "ipl" / "leaderboards" / "ngi.json").read_text(encoding="utf-8"))[
        0
    ]
    r = runner.invoke(app, ["leaderboard", "ngi", "-c", "ipl", "--top", "3"])
    assert r.exit_code == 0, r.output
    assert top["name"] in r.output


def test_unknown_data_slice_is_a_user_error():
    r = runner.invoke(app, ["data", "ingest", "not-a-slice"])
    assert r.exit_code == 1


def test_documented_options_exist():
    # the options the docs show for scout and auction (they once listed a -c that didn't exist)
    r = runner.invoke(app, ["scout", "look-alikes", "--help"])
    assert (
        r.exit_code == 0
        and "--pos" in r.output
        and "-c" not in r.output.split("Options")[-1].split()
    )
    r = runner.invoke(app, ["auction", "room", "--help"])
    assert r.exit_code == 0
    for opt in ("--mode", "--purse", "--squad-size", "--overseas-cap", "--trials", "--top-n"):
        assert opt in r.output
