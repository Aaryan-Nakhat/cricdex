"""Tests for the real-IPL franchise/personality defaults.

(The offline Bayes-priced pool/franchise builders were removed — the live
auction Monte-Carlo lives in `cricdex.web_parity`; this module now only supplies
the franchise + personality config the desktop Auction reads.)
"""

from __future__ import annotations

from cricdex.auction import real_pool


def test_franchise_archetypes_shape():
    assert len(real_pool.FRANCHISE_ARCHETYPES) >= 4
    needed = {"id", "purse", "aggression", "risk", "role_mins"}
    for spec in real_pool.FRANCHISE_ARCHETYPES:
        assert needed.issubset(spec), spec
        assert spec["purse"] > 0
        assert 0.0 < spec["aggression"] <= 2.0


def test_personality_ids_derived_from_archetypes():
    assert real_pool.PERSONALITY_IDS == tuple(a["id"] for a in real_pool.FRANCHISE_ARCHETYPES)
    assert len(set(real_pool.PERSONALITY_IDS)) == len(real_pool.PERSONALITY_IDS)  # unique


def test_team_defaults_use_valid_personalities():
    assert len(real_pool.IPL_TEAMS_DEFAULT) == 10
    for team, personality in real_pool.IPL_TEAMS_DEFAULT:
        assert team
        assert personality in real_pool.PERSONALITY_IDS


def test_load_team_overrides_missing_file_is_none(tmp_path):
    assert real_pool.load_team_overrides(tmp_path / "nope.yaml") is None
