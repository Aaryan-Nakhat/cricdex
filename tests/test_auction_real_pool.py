"""Tests for the real-IPL franchise list the desktop Auction reads.

(The live auction Monte-Carlo lives in `cricdesk.web_parity`; the hand-assigned
bidding personalities were replaced by a fitted demand model on 2026-10-23.)
"""

from __future__ import annotations

from cricdesk.auction import real_pool


def test_ten_unique_franchises():
    assert len(real_pool.IPL_TEAMS) == 10
    assert len(set(real_pool.IPL_TEAMS)) == 10
    assert all(real_pool.IPL_TEAMS)


def test_no_personalities_left():
    assert not hasattr(real_pool, "FRANCHISE_ARCHETYPES")
    assert not hasattr(real_pool, "PERSONALITY_IDS")
