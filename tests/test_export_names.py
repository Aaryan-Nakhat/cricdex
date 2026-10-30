"""Namesakes in one league get the first tag that tells every one of them apart: country, years in
the league, full name, role, first match, else the registry id."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import export_site as ex  # noqa: E402


def _p(cid, **kw):
    return {
        "cricsheet_id": cid,
        "display_name": kw.pop("name", "Ollie Robinson"),
        "aliases": [],
        **kw,
    }


def _names(players):
    ex._disambiguate_names(players)
    return [p["display_name"] for p in players]


def test_country_first():
    ps = [
        _p("a", name="Harmeet Singh", country="USA"),
        _p("b", name="Harmeet Singh", country="IND"),
    ]
    assert _names(ps) == ["Harmeet Singh (USA)", "Harmeet Singh (IND)"]
    assert ps[0]["aliases"] == ["Harmeet Singh"]


def test_years_when_the_countries_match():
    ps = [
        _p("a", country="ENG", first_match_date="2021-07-01", last_match_date="2023-08-01"),
        _p("b", country="ENG", first_match_date="2024-07-26", last_match_date="2024-07-26"),
    ]
    assert _names(ps) == ["Ollie Robinson (2021–2023)", "Ollie Robinson (2024)"]


def test_full_name_when_country_and_years_match():
    # the 2024 Hundred: both English, both only in 2024
    d = {"country": "ENG", "first_match_date": "2024-07-26", "last_match_date": "2024-08-13"}
    ps = [
        _p("a", full_name="Oliver George Robinson", **d),
        _p("b", full_name="Oliver Edward Robinson", **d),
    ]
    assert _names(ps) == [
        "Ollie Robinson (Oliver George Robinson)",
        "Ollie Robinson (Oliver Edward Robinson)",
    ]


def test_role_then_first_match_then_id():
    d = {"full_name": "Tom Rogers", "last_match_date": "2026-10-24"}
    ps = [
        _p("a", role="batter", first_match_date="2026-09-25", **d),
        _p("b", role="bowler", first_match_date="2026-10-13", **d),
    ]
    assert _names(ps) == ["Ollie Robinson (batter)", "Ollie Robinson (bowler)"]
    ps = [
        _p("a", role="bowler", first_match_date="2024-03-09"),
        _p("b", role="bowler", first_match_date="2024-03-06"),
    ]
    assert _names(ps) == ["Ollie Robinson (from 2024-03-09)", "Ollie Robinson (from 2024-03-06)"]
    ps = [_p("a", role="bowler"), _p("b", role="bowler")]
    assert _names(ps) == ["Ollie Robinson (a)", "Ollie Robinson (b)"]
