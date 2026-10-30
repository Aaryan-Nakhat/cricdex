"""The market-price model (docs/METHODOLOGY.md §6b): four groups, each shifted by its median
out-of-fold residual (`calibration_part`), a monotone top-end calibration with a fitted tail slope, the
value held to its training support, no ceiling (mirrored in site/src/lib/auction.ts; the TS ⇄ Python
numbers are checked in test_scripts/test_web_parity.py)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

from cricdex.web_parity import pricing

ROOT = Path(__file__).resolve().parents[1]


def _row(**kw) -> dict:
    base = {
        "price_value": 10.0, "value_sd": 3.0, "role": "batter", "is_overseas": False,
        "intl_caps": 0, "intl_caps_2y": 0, "age": 27.0, "ipl_balls": 1500, "ipl_seasons": 5,
        "ipl_gap": 0.6, "target_balls": 1500,
    }  # fmt: skip
    return {**base, **kw}


@pytest.fixture(scope="module")
def model() -> dict:
    pricing.load_price_model.cache_clear()
    m = pricing.load_price_model(str(ROOT / "config" / "price_model.json"))
    if m is None:
        pytest.skip("no config/price_model.json")
    return m


def test_groups_split_overseas_by_auction_type(model):
    part = model["price"]
    names = [g["name"] for g in part["groups"]]
    # capped Indians split by auction type too since the 2026-10-30 refit (METHODOLOGY §6b)
    assert names == [
        "overseas_mega", "overseas_mini", "capped_indian_mini", "capped_indian", "uncapped_indian"
    ]  # fmt: skip
    cases = [
        (_row(is_overseas=True, intl_caps=50), "mega", "overseas_mega"),
        (_row(is_overseas=True, intl_caps=50), "mini", "overseas_mini"),
        (_row(intl_caps=20), "mini", "capped_indian_mini"),
        (_row(intl_caps=20), "mega", "capped_indian"),
        (_row(intl_caps=0), "mega", "uncapped_indian"),
    ]
    for row, cycle, want in cases:
        got = pricing.calibration_part(part, pricing.market_features(row, cycle))
        assert got["name"] == want


def test_price_is_the_calibrated_index_plus_group_shift(model):
    """The price is purse × e^(calibrate(linear) + his group's shift), no ceiling, at least the floor;
    `high` adds the fitted spread (the 75th percentile of the out-of-fold residuals at that
    prediction), or without one is the same for an index 0.674 residual sd higher."""
    part = model["price"]
    row = _row(is_overseas=True, intl_caps=80, price_value=12.0)
    comp = {"cycle": "mini", "purse": 125.0}
    f = pricing.market_features(row, "mini", part.get("pv_max"))
    g = pricing.calibration_part(part, f)
    raw = pricing.link_share(part, pricing._linear(part, f))
    mk = pricing.market_price(row, comp, model)
    assert mk["price"] == pytest.approx(max(0.3, 125.0 * math.exp(pricing.calibrate(g, raw))))
    lin = pricing.calibrate(g, raw)
    if part.get("spread"):
        hi = lin + max(0.0, part["spread"]["a"] + part["spread"]["b"] * lin)
    else:
        hi = pricing.calibrate(g, raw + pricing.MARKET_HIGH_Z * part["resid_sd"])
    assert mk["high"] == pytest.approx(max(0.3, 125.0 * math.exp(hi)))


def test_the_top_end_is_bounded_without_a_ceiling(model):
    """No ceiling: a value far past anything the market priced is held to the training support, and
    the top flattens, by the fitted budget-limit link (the median saturates at a share of the purse,
    since 2026-10-30) or a calibrated top slope below 1, so no player in the shipped model reaches the
    purse (the 2026-10-22 reality check: Gill was about 90 cr on the linear index)."""
    part = model["price"]
    assert part.get("pv_max") is not None and part["pv_max"] < pricing.MARKET_PV_MAX
    cal = part.get("calibration") or {}
    link = part.get("link") or {}
    assert (link.get("kind") == "sat" and 0.0 < link["cap_share"] <= 1.0) or (
        0.0 <= cal.get("hi_slope", 1.0) < 1.0
    )
    star = _row(price_value=60.0, value_sd=2.0, intl_caps=300, intl_caps_2y=60, ipl_balls=4000,
                ipl_seasons=9, age=27.0, captain_ipl_last=1, captain_ipl_seasons=2,
                captain_intl_2y=1)  # fmt: skip
    mk = pricing.market_price(star, {"cycle": "mega", "purse": 125.0}, model)
    assert mk["price"] < 0.5 * 125.0
    # the value is held to its support: beyond it the price doesn't move
    more = pricing.market_price(
        {**star, "price_value": 90.0}, {"cycle": "mega", "purse": 125.0}, model
    )
    assert more["price"] == pytest.approx(mk["price"])


def test_the_upper_quartile_is_never_below_the_price(model):
    """`high` keeps its gap above the model's unfloored median, so it can't fall under the price: a
    resold player the model puts below the floor read price 0.40, high 0.31 (Mayank Rawat, 2027)."""
    comp = {"cycle": "mini", "purse": 125.0}
    cases = [
        _row(price_value=v, ipl_balls=b, ipl_seasons=n, prior_share=ps, prior_years=1)
        for v in (-30.0, -10.0, 0.0, 10.0)
        for b, n in ((0, 0), (40, 1), (1500, 5))
        for ps in (0.2 / 120.0, 0.3 / 120.0, 1.0 / 120.0, 14.0 / 120.0)
    ]
    cases += [_row(price_value=v, ipl_balls=b) for v in (-40.0, -15.0, 5.0) for b in (0, 30, 3000)]
    for row in cases:
        mk = pricing.market_price(row, comp, model)
        assert mk["high"] >= mk["price"] - 1e-9, (row, mk)


def test_calibrate_continues_at_hi_slope():
    part = {"calibration": {"x": [-2.0, -1.0], "y": [-2.5, -2.0], "hi_slope": 0.5}, "shift": 0.1}
    assert pricing.calibrate(part, -3.0) == pytest.approx(-3.5 + 0.1)  # slope 1 below
    assert pricing.calibrate(part, -1.5) == pytest.approx(-2.25 + 0.1)
    assert pricing.calibrate(part, 1.0) == pytest.approx(-2.0 + 0.5 * 2.0 + 0.1)  # hi_slope above
    no_tail = {"calibration": {"x": [-2.0, -1.0], "y": [-2.5, -2.0]}}
    assert pricing.calibrate(no_tail, 1.0) == pytest.approx(-2.0 + 2.0)


def test_saturating_link_never_passes_its_cap():
    part = {"link": {"kind": "sat", "cap_share": 0.3}}
    assert pricing.link_share(part, 50.0) == pytest.approx(math.log(0.3), abs=1e-9)
    assert pricing.link_share(part, -30.0) == pytest.approx(math.log(0.3) - 30.0, abs=1e-6)
    assert pricing.link_share({}, -2.0) == -2.0


def test_tobit_sat_recovers_a_saturating_price():
    """TobitRidge(link="sat") fits ln S + ln σ(η) and finds S when the data saturate."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import ipl_price_model as ipm
    from scipy.special import log_expit

    rng = np.random.default_rng(2)
    x = rng.normal(size=(3000, 1)) * 2.0
    y = math.log(0.25) + log_expit(1.2 * x[:, 0]) + rng.normal(scale=0.2, size=3000)
    m = ipm.TobitRidge(alpha=0.0, link="sat").fit(x, y)
    assert m.cap_share_ == pytest.approx(0.25, rel=0.1)
    assert m.coef_[0] == pytest.approx(1.2, rel=0.15)


def test_median_offset_calibration_is_each_groups_median_residual():
    sys.path.insert(0, str(ROOT / "scripts"))
    import ipl_price_model as ipm

    rows = [
        {**_row(is_overseas=ov, intl_caps=caps), "cycle": cyc, "season": 2024}
        for ov, caps, cyc in ((True, 50, "mega"), (True, 50, "mini"), (False, 9, "mini"),
                              (False, 0, "mini")) for _ in range(5)
    ]  # fmt: skip
    lin = np.zeros(len(rows))
    rng = np.random.default_rng(0)
    y = rng.normal(size=len(rows))
    part = ipm._fit_calibration("none+group-median-offset", lin, y, rows)
    assert part["calibration"] is None
    for i, g in enumerate(part["groups"]):
        assert g["shift"] == pytest.approx(float(np.median(y[5 * i : 5 * i + 5])), abs=1e-6)


def test_tobit_treats_retentions_as_floors():
    """A retention is a floor, not a price: with the floors set below the true prices, the censored
    fit recovers the slope; treating the same floors as prices pulls it down."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import ipl_price_model as ipm

    rng = np.random.default_rng(1)
    x = rng.normal(size=(800, 1))
    y = 1.5 * x[:, 0] + rng.normal(scale=0.6, size=800)
    # the stars are "retained" at a price drawn independently of their worth: when they're worth
    # more than it, only that floor is seen (right-censored), else their price is
    floor = 1.5 * x[:, 0] - 0.3 + rng.normal(scale=0.5, size=800)
    cens = (x[:, 0] > 0.3) & (y > floor)
    obs = np.where(cens, floor, y)
    tob = ipm.TobitRidge(alpha=0.0).fit(x, obs, cens)
    assert tob.coef_[0] == pytest.approx(1.5, abs=0.1)
    assert tob.scale_ == pytest.approx(0.6, abs=0.08)
    plain = ipm.TobitRidge(alpha=0.0).fit(x, obs, np.zeros(800, bool))
    assert plain.coef_[0] < tob.coef_[0] - 0.1


def test_prior_verdict_is_the_last_sale_or_mega_retention():
    hist = {
        "auctions": {"2022": {"kind": "mega", "purse_cr": 90.0},
                     "2024": {"kind": "mini", "purse_cr": 100.0},
                     "2025": {"kind": "mega", "purse_cr": 120.0}},
        "lots": [{"season": 2022, "sold": True, "cricsheet_id": "a", "price_cr": 9.0}],
        "retentions": [
            {"season": 2024, "kind": "retained", "cricsheet_id": "a", "salary_cr": 9.0},  # mini: no
            {"season": 2025, "kind": "retained", "cricsheet_id": "a", "salary_cr": 18.0},
        ],
    }  # fmt: skip
    v = pricing.market_verdicts(hist)["a"]
    assert pricing.prior_verdict(v, 2025) == {
        "prior_share": pytest.approx(0.1),
        "prior_years": 3,
        "prior_retained": False,
    }
    assert pricing.prior_verdict(v, 2027) == {
        "prior_share": pytest.approx(0.15),
        "prior_years": 2,
        "prior_retained": True,
    }
    assert pricing.prior_verdict(v, 2022)["prior_share"] is None
