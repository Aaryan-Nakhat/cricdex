"""The value calibration (scout/ratings/shrink.py): the shrink toward the role's mean."""

from __future__ import annotations

import pytest

from cricdex.scout.ratings import shrink


def test_flat_shrink_moves_toward_the_mean():
    m = {"batter": shrink.RoleShrink(mu=-10.0, tau2=1.0, k_flat=0.75)}
    out, ks = shrink.adjust({"p": {"batter": (10.0, 4.0)}}, {}, {}, m)
    assert out["p"]["batter"] == pytest.approx((5.0, 3.0))
    assert ks[("p", "batter")] == pytest.approx(0.75)


def test_evidence_shrink_trusts_ipl_and_recent_evidence_more():
    m = shrink.RoleShrink(mu=0.0, tau2=50.0, s=1.0, w_o=40.0, w_r=10.0)
    ipl_recent = m.k(sd=3.0, ipl_share=1.0, years=0.0)
    league_old = m.k(sd=3.0, ipl_share=0.0, years=2.0)
    assert 0 < league_old < ipl_recent < 1


def test_no_model_leaves_values_alone():
    v = {"p": {"bowler": (3.0, 1.0)}}
    assert shrink.adjust(v, {}, {}, None)[0] is v
