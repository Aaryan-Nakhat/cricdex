"""TUI: partial names never pick the wrong player, and corrupt / missing exported
JSON shows a message in the tab instead of crashing the app."""

from __future__ import annotations

import asyncio
import importlib
import shutil

import pytest

pytest.importorskip("textual", reason="needs the cli extra")
pytest.importorskip("textual_autocomplete", reason="needs the cli extra")

from textual.widgets import (  # noqa: E402
    Button,
    DataTable,
    Input,
    RichLog,
    Static,
    TabbedContent,
)

import cricdesk.config as config  # noqa: E402
import cricdesk.web_parity.loader as loader  # noqa: E402

tui = importlib.import_module("cricdesk.cli.tui")  # the package also has a `tui` command
from cricdesk.config import SITE_DATA  # noqa: E402


def _cells(table: DataTable) -> str:
    return " ".join(str(c) for i in range(table.row_count) for c in table.get_row_at(i))


def _press(app, button_id: str) -> None:
    app.on_button_pressed(Button.Pressed(app.query_one(f"#{button_id}", Button)))


def _log_text(app, log_id: str) -> str:
    return " ".join(line.text for line in app.query_one(log_id, RichLog).lines)


def _run(act, check, tab: str | None = None) -> None:
    """Mount the app (showing `tab`), do `act(app)`, let it settle, then `check(app)`."""

    async def main():
        app = tui.CricDeskApp()
        async with app.run_test(size=(200, 60)) as pilot:
            await pilot.pause()
            if tab:
                app.query_one(TabbedContent).active = tab
                await pilot.pause()
            act(app)
            await pilot.pause()
            check(app)
            assert app.is_running  # nothing took the app down

    asyncio.run(main())


def _assert_in(needle: str, haystack: str) -> None:
    assert needle in haystack, haystack


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A private copy of the ipl export the test may break, wired into every reader."""
    root = tmp_path / "data"
    (root / "ipl").mkdir(parents=True)
    shutil.copy(SITE_DATA / "ipl" / "players.json", root / "ipl" / "players.json")
    for mod in (config, tui, loader):
        monkeypatch.setattr(mod, "SITE_DATA", root)
    return root


def test_resolve_player_prefers_exact_then_unique_and_lists_ambiguous(site):
    row, _ = tui._resolve_player("ipl", "v kohli")
    assert row and row["name"] == "V Kohli"
    row, _ = tui._resolve_player("ipl", "Bumrah")
    assert row and row["name"] == "JJ Bumrah"
    row, msg = tui._resolve_player("ipl", "Sharma")
    assert row is None and "matches" in msg and "RG Sharma" in msg


def test_profile_ambiguous_name_shows_candidates(site):
    def act(app):
        app.query_one("#profile-name", Input).value = "Sharma"
        _press(app, "profile-run")

    def check(app):
        text = _log_text(app, "#profile-log")
        assert "matches" in text and "type more of the name" in text

    _run(act, check, tab="tab-profile")


def test_h2h_resolves_typed_names_and_rejects_ambiguous_ones(site):
    def act(app):
        app.query_one("#h2h-a", Input).value = "Sharma"
        app.query_one("#h2h-b", Input).value = "V Kohli"
        _press(app, "h2h-run")

    _run(act, lambda app: _assert_in("matches", _cells(app.query_one("#h2h-table", DataTable))))


def test_corrupt_players_json_shows_a_message(site):
    (site / "ipl" / "players.json").write_text("{not json", encoding="utf-8")

    _run(
        lambda app: _press(app, "mu-run"),
        lambda app: _assert_in("players.json", _cells(app.query_one("#mu-bat-table", DataTable))),
    )


def test_corrupt_profile_json_shows_a_message(site):
    cid = tui._resolve_player("ipl", "V Kohli")[0]["cricsheet_id"]
    (site / "ipl" / "profiles").mkdir()
    (site / "ipl" / "profiles" / f"{cid}.json").write_text("[[[", encoding="utf-8")

    def act(app):
        app.query_one("#profile-name", Input).value = "V Kohli"
        _press(app, "profile-run")

    _run(
        act, lambda app: _assert_in("can't read", _log_text(app, "#profile-log")), tab="tab-profile"
    )


def test_missing_auction_pool_does_not_crash(site):
    def act(app):
        app.query_one("#sim-ret-player", Input).value = "V Kohli"
        _press(app, "sim-ret-add")

    _run(
        act,
        lambda app: _assert_in(
            "auction_pool.json", str(app.query_one("#sim-ret-map", Static).render())
        ),
    )


def test_leaderboard_missing_values_go_last():
    rows = [{"name": "none", "v": None}, {"name": "low", "v": -3.0}, {"name": "high", "v": 4.0}]
    assert [r["name"] for r in tui.sort_missing_last(rows, "v", True)] == ["high", "low", "none"]
    assert [r["name"] for r in tui.sort_missing_last(rows, "v", False)] == ["low", "high", "none"]
