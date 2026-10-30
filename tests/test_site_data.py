"""The exported site data (what the web app, CLI, TUI and dashboard read) — shape and the rules the fixes promise."""

from __future__ import annotations

import json
import re

import pytest

from cricdex import leagues
from cricdex.config import SITE_DATA

COLLECTIONS = [
    c["collection"]
    for c in json.loads((SITE_DATA / "collections.json").read_text(encoding="utf-8"))
]
PAGE_FILES = [
    "meta.json",
    "players.json",
    "ratings.json",
    "records.json",
    "venues.json",
    "phase.json",
    "partnerships.json",
    "aging.json",
]
BOARDS = [
    "ngi",
    "pressure_runs",
    "intent_curve",
    "dot_ball_recovery",
    "counter_attack",
    "boundary_dependency",
    "dot_avoidance",
    "pace_spin",
    "finisher",
    "hand_split",
    "wicket_quality",
    "crease_longevity",
    "slow_start_cost",
    "keeping",
    "fielding",
]


def _load(*parts):
    return json.loads(SITE_DATA.joinpath(*parts).read_text(encoding="utf-8"))


def _registry_snapshot() -> dict:
    """The exported leagues.json — absent in a snapshot cooked before the league registry existed,
    so the registry checks wait for the first full re-export instead of failing on old data."""
    f = SITE_DATA / "leagues.json"
    if not f.exists():
        pytest.skip("site data predates leagues.json — re-run scripts/export_site.py")
    return json.loads(f.read_text(encoding="utf-8"))


def test_every_registry_league_is_exported():
    _registry_snapshot()
    assert COLLECTIONS == leagues.exported_keys()  # the same set, in registry order


def test_site_leagues_json_matches_the_registry():
    assert _registry_snapshot() == json.loads(json.dumps(leagues.site_payload()))


def test_scout_index_has_every_registry_pool():
    _registry_snapshot()
    idx = _load(leagues.auction_target().key, "scout_index.json")
    assert list(idx) == [lg.tier for lg in leagues.scout_pools()]


@pytest.mark.parametrize("col", COLLECTIONS)
def test_every_league_has_every_page(col):
    for f in PAGE_FILES:
        assert (SITE_DATA / col / f).exists(), f"{col}/{f} missing"
    for b in BOARDS:
        assert (SITE_DATA / col / "leaderboards" / f"{b}.json").exists(), f"{col} {b} board missing"
    assert any((SITE_DATA / col / "matchups").glob("*.json")), f"{col} has no matchups"


@pytest.mark.parametrize("col", COLLECTIONS)
def test_ngi_board_keeps_its_matches_floor(col):
    rows = _load(col, "leaderboards", "ngi.json")
    if rows:
        assert min(int(r["matches"]) for r in rows) >= 25


def test_bowlers_get_aging_curves():
    players = _load("ipl", "aging.json")["players"]
    assert any(p.get("bowling") for p in players.values())
    assert all(set(p) >= {"batting", "bowling"} for p in players.values())


def test_exported_data_names_no_llm_provider():
    # the taxonomy source is recorded generically; no provider / model name ships with the site
    pat = re.compile(r"gemini|vertex|openai|anthropic|gpt-\d", re.I)
    for col in COLLECTIONS:
        text = (SITE_DATA / col / "players.json").read_text(encoding="utf-8")
        assert not pat.search(text), f"{col}/players.json names an LLM provider"
