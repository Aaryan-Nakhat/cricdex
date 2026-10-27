"""Fact checks on the exported site data: one player-master build behind every league export, the
same identity for a player in every league, an age for every rated Keep player, and role tags that
match cricket reality for players whose role nobody disputes.

Skipped when there is no export (CI without data); point `CRICDEX_SITE_DATA` at another export to
check that one."""

from __future__ import annotations

import json

import pytest

from cricdex.config import SITE_DATA

IDX = SITE_DATA / "collections.json"
COLLECTIONS = (
    [c["collection"] for c in json.loads(IDX.read_text(encoding="utf-8"))] if IDX.exists() else []
)
KEEP = SITE_DATA / "ipl" / "keep.json"


def _load(*parts):
    p = SITE_DATA.joinpath(*parts)
    if not p.exists():
        pytest.skip(f"no {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _keep() -> list[dict]:
    if not KEEP.exists():
        pytest.skip("no keep.json")
    return json.loads(KEEP.read_text(encoding="utf-8"))["players"]


@pytest.mark.skipif(not COLLECTIONS, reason="no site export")
def test_every_league_export_comes_from_one_player_master_build():
    """meta.json stamps the player master each league was exported with; mixed builds give the
    same player different dates of birth or retirements in different leagues."""
    stamps: dict[str, list[str]] = {}
    for col in COLLECTIONS:
        st = (_load(col, "meta.json").get("player_master") or {}).get("hash")
        stamps.setdefault(st or "unstamped", []).append(col)
    assert len(stamps) == 1, (
        "league exports from different player-master builds (re-export these): "
        + "; ".join(f"{h}: {', '.join(sorted(c))}" for h, c in sorted(stamps.items()))
    )


@pytest.mark.skipif(not COLLECTIONS, reason="no site export")
@pytest.mark.parametrize("field", ["dob", "country", "retired"])
def test_a_player_has_one_identity_across_leagues(field):
    seen: dict[str, tuple[str, object]] = {}
    bad: list[str] = []
    for col in COLLECTIONS:
        for p in _load(col, "players.json"):
            cid = p.get("cricsheet_id")
            if not cid or field not in p:
                continue
            if cid in seen and seen[cid][1] != p[field]:
                bad.append(
                    f"{p.get('display_name')} ({cid}): {seen[cid][0]} {seen[cid][1]!r}, "
                    f"{col} {p[field]!r}"
                )
            seen.setdefault(cid, (col, p[field]))
    assert not bad, f"{len(bad)} players differ on {field}, e.g. " + "; ".join(bad[:8])


def test_every_rated_keep_player_has_an_age():
    """A missing age reads as 28 in the Keep and price models."""
    bad = [
        f"{p['name']} ({p['team']})"
        for p in _keep()
        if p.get("value") is not None and p.get("age") is None
    ]
    assert not bad, "rated, no age: " + ", ".join(bad)


def _tags(name: str) -> str:
    rows = [p for p in _keep() if p.get("name") == name]
    if not rows:
        pytest.skip(f"{name} not in a squad")
    return rows[0].get("tags") or ""


@pytest.mark.parametrize("name", ["Sunil Narine", "Virat Kohli", "Sanju Samson", "Aiden Markram"])
def test_regular_openers_carry_the_opener_tag(name):
    assert "o" in _tags(name), f"{name} opens for his franchise"


@pytest.mark.parametrize("name", ["Ruturaj Gaikwad", "Ben Duckett"])
def test_occasional_keepers_are_not_keepers(name):
    assert "k" not in _tags(name), f"{name} doesn't keep wicket"
