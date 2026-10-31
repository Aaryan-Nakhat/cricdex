"""League translations onto the IPL (cricdesk.scout.translation; audit item 5, 2026-10-23)."""

from __future__ import annotations

import math

import pytest

from cricdesk import leagues
from cricdesk.scout import translation as tr

ROW = {"a": -10.0, "b": 0.8, "tsd": 9.0, "cov": [[4.0, -0.1], [-0.1, 0.01]]}


def test_translate_row_mean_and_variance():
    mu, sd = tr.translate_row(ROW, 20.0, 5.0)
    assert mu == pytest.approx(-10.0 + 0.8 * 20.0)
    par = 4.0 + 2 * 20.0 * -0.1 + 400 * 0.01
    assert sd == pytest.approx(math.sqrt((0.8 * 5.0) ** 2 + 81.0 + par))
    # a missing sd counts as 0; the parameter variance is never negative
    mu0, sd0 = tr.translate_row({**ROW, "cov": [[0, -5], [-5, 0]]}, 20.0, None)
    assert sd0 == pytest.approx(9.0)


def test_combine_is_a_precision_blend_with_no_cutoff():
    v, sd, shares = tr.combine((10.0, 3.0), [(0.0, 9.0)])
    w1, w2 = 1 / 9, 1 / 81
    assert v == pytest.approx(10.0 * w1 / (w1 + w2))
    assert sd == pytest.approx((w1 + w2) ** -0.5)
    assert shares == pytest.approx([w1 / (w1 + w2), w2 / (w1 + w2)])
    # the IPL record's weight grows smoothly with its precision: no 300-ball switch
    thin = tr.combine((10.0, 12.0), [(0.0, 9.0)])[0]
    mid = tr.combine((10.0, 6.0), [(0.0, 9.0)])[0]
    long_ = tr.combine((10.0, 2.0), [(0.0, 9.0)])[0]
    assert thin < mid < long_ < 10.0


def test_combine_with_the_prior_divided_out():
    # one source: nothing to divide out
    assert tr.combine(None, [(5.0, 4.0)], prior=(0.0, 20.0))[:2] == pytest.approx((5.0, 4.0))
    # two sources that each hold the same prior: the product of posteriors / the prior
    v, sd, _ = tr.combine((6.0, 4.0), [(4.0, 4.0)], prior=(0.0, 20.0))
    prec = 1 / 16 + 1 / 16 - 1 / 400
    assert sd == pytest.approx(prec**-0.5)
    assert v == pytest.approx((6 / 16 + 4 / 16) / prec)
    assert v > 5.0  # less pull to the prior mean than the plain blend


def test_blend_translates_each_league_and_names_the_shares():
    model = {
        "blend": "precision",
        "roles": {
            "batter": {
                "leagues": {"bbl": {"a": 2.0, "b": 0.5, "tsd": 6.0, "cov": [[0, 0], [0, 0]]}},
                "groups": {"overseas_b": {"a": -3.0, "b": 0.5, "tsd": 8.0}},
                "prior": {"mean": 0.0, "sd": 20.0},
            }
        },
    }
    v, sd, shares = tr.blend("batter", None, {"bbl": (10.0, 0.0)}, model)
    assert (v, sd) == pytest.approx((7.0, 6.0))
    assert shares == {"bbl": pytest.approx(1.0)}
    # a league with no fitted row takes its pooling group's typical league
    v2, _, _ = tr.blend("batter", None, {"cpl": (10.0, 0.0)}, model)
    assert v2 == pytest.approx(2.0)
    # the IPL rating is not translated and comes first in the shares
    v3, _, sh3 = tr.blend("batter", (20.0, 6.0), {"bbl": (10.0, 0.0)}, model)
    assert v3 == pytest.approx((20 / 36 + 7 / 36) / (2 / 36))
    assert list(sh3) == ["ipl", "bbl"]
    assert tr.translate("ipl", "batter", 12.0, 3.0, model) == (12.0, 3.0)


def test_many_leagues_share_one_translation_variance():
    # a player's gap between league numbers and IPL level is his own: six leagues saying +10 shrink
    # the rating noise, not the translation sd
    one = tr.league_composite([(10.0, 4.0, 81.0)])
    six = tr.league_composite([(10.0, 4.0, 81.0)] * 6)
    assert one[:2] == pytest.approx((10.0, math.sqrt(85.0)))
    assert six[0] == pytest.approx(10.0)
    assert six[1] == pytest.approx(math.sqrt(4.0 / 6 + 81.0))
    assert six[2] == pytest.approx([1 / 6] * 6)
    # so a long IPL record keeps nearly all its weight against a player of many leagues
    model = {"blend": "precision", "roles": {"bowler": {
        "leagues": {c: {"a": 0.0, "b": 1.0, "tsd": 9.0, "cov": [[0, 0], [0, 0]]}
                    for c in ("bbl", "cpl", "psl", "ilt20", "sa20", "hundred_male")},
        "groups": {}, "prior": {"mean": 0.0, "sd": 12.0}}}}  # fmt: skip
    other = dict.fromkeys(model["roles"]["bowler"]["leagues"], (30.0, 3.0))
    v, _, shares = tr.blend("bowler", (20.0, 2.6), other, model)
    assert shares["ipl"] > 0.9 and 20.0 < v < 21.5


def test_legacy_blend_reproduces_the_replaced_scheme():
    # 300+ IPL balls: the IPL rating alone
    assert tr.legacy_blend((10.0, 3.0, 300), {"indian_domestic_male": (40.0, 5.0)})[:2] == (
        10.0,
        3.0,
    )
    # under 300: every league less its discount, by 1 / (sd² + old translation sd²)
    v, sd, _ = tr.legacy_blend((10.0, 3.0, 299), {"indian_domestic_male": (40.0, 5.0)})
    w1, w2 = 1 / 9, 1 / (25 + 6.5**2)
    assert v == pytest.approx((10 * w1 + 23 * w2) / (w1 + w2))
    assert sd == pytest.approx((w1 + w2) ** -0.5)


def test_shipped_model_covers_every_pool_league_and_role():
    m = tr.load_model()
    for role in tr.ROLES:
        fitted = m["roles"][role]["leagues"]
        for lg in leagues.auction_pool():
            if lg.auction_target:
                assert tr.table(lg.key, role) is None
                continue
            t = fitted[lg.key]
            # a translation sd from the fit, positive slopes, and the overlap it rests on
            assert t["tsd"] > 0 and 0 < t["b"] < 2 and t["pairs"] >= 0, (lg.key, role)
    # the pooling groups of the registry are the groups of the fit
    groups = {t.group for t in leagues.tiers().values()} - {"reference"}
    assert groups <= set(m["roles"]["batter"]["groups"])


def test_smat_translation_differs_by_role():
    # the audit's measured gap: SMAT batters lose far more than SMAT bowlers at their typical level
    s = tr.summary(at=15.0)["indian_domestic_male"]
    assert 15.0 - s["batter"] > 15.0 - s["bowler"]
