"""Price-model reality gates (2026-10-29, after the six-way review; METHODOLOGY §6b): what any market
price must do before its error is compared at all. Written before the refit they judge; each threshold
is a property of a price or of the auction record, not tuned to a model. They run on the shipped
`config/price_model.json` (and, for the ties, the exported pool).

Marked xfail(strict) while the shipped model failed them; the 2026-10-30 refit (recipe BH, METHODOLOGY
§6b) passes them all and the marks came off."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from cricdesk.web_parity import pricing

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "site" / "public" / "data" / "ipl" / "auction_pool.json"
COMP = {"cycle": "mini", "purse": 125.0}


@pytest.fixture(scope="module")
def model() -> dict:
    pricing.load_price_model.cache_clear()
    m = pricing.load_price_model(str(ROOT / "config" / "price_model.json"))
    if m is None:
        pytest.skip("no config/price_model.json")
    return m


def _row(**kw) -> dict:
    base = {
        "price_value": 10.0, "value_sd": 3.0, "role": "batter", "is_overseas": False,
        "intl_caps": 20, "intl_caps_2y": 5, "age": 27.0, "ipl_balls": 1500, "ipl_seasons": 5,
        "ipl_gap": 0.6, "target_balls": 1500,
    }  # fmt: skip
    return {**base, **kw}


PROFILES = [
    {},  # a capped Indian batter, 5 seasons
    {"is_overseas": True, "intl_caps": 60, "intl_caps_2y": 15},
    {"role": "bowler", "intl_caps": 0, "intl_caps_2y": 0, "ipl_balls": 600},
    {"role": "keeper", "price_value": 25.0, "ipl_balls": 3000},
]


def test_more_ipl_seasons_never_lowers_the_price(model):
    """At the same balls, value and everything else, a longer IPL career can't make a player cheaper
    (Kohli 16.2 cr at 3 seasons fell to 7.6 at 15)."""
    for prof in PROFILES:
        prices = [pricing.market_price(_row(**{**prof, "ipl_seasons": n}), COMP, model)["price"]
                  for n in range(1, 16)]  # fmt: skip
        assert all(b >= a - 1e-9 for a, b in zip(prices, prices[1:], strict=False)), (prof, prices)


def test_a_better_value_never_lowers_the_price(model):
    """Across the values the market has priced, a better player never prices lower."""
    for prof in PROFILES:
        prices = [pricing.market_price(_row(**{**prof, "price_value": v}), COMP, model)["price"]
                  for v in range(-30, 41, 2)]  # fmt: skip
        assert all(b >= a - 1e-9 for a, b in zip(prices, prices[1:], strict=False)), (prof, prices)


def test_a_few_ipl_balls_dont_cut_the_price(model):
    """Six IPL balls can't make a player much cheaper than none (Rickelton's profile: 2.92 cr with
    none, 1.70 with 6): at most 10% below."""
    for prof in PROFILES:
        none = pricing.market_price(
            _row(**{**prof, "ipl_balls": 0, "ipl_seasons": 0, "ipl_gap": None}), COMP, model
        )
        few = pricing.market_price(_row(**{**prof, "ipl_balls": 6, "ipl_seasons": 1}), COMP, model)
        assert few["price"] >= 0.9 * none["price"], (prof, none["price"], few["price"])


def test_a_longer_ipl_absence_never_raises_the_chance_he_is_bought(model):
    """Two years out of the IPL can't make a franchise likelier to buy him (fitted ipl_gap +0.345)."""
    assert float(model["bought"]["coef"].get("ipl_gap", 0.0)) <= 0.0


def test_prices_resolve_players(model):
    """A price that says something about the player: no more than 5% of the pool shares an exact
    price with five or more others (the staircase put 50 players at 1.0672 cr)."""
    if not POOL.exists():
        pytest.skip("no exported pool")
    rows = json.loads(POOL.read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("players", [])
    prices = [round(pricing.market_price(r, COMP, model)["price"], 4) for r in rows
              if pricing.has_market_inputs(r, model)]  # fmt: skip
    c = Counter(prices)
    crowded = sum(n for p, n in c.items() if n >= 6 and p > 0.3)  # the floor is a floor, not a tie
    assert crowded <= 0.05 * len(prices), (crowded, len(prices), c.most_common(3))


def test_the_upper_quartile_is_beaten_about_a_quarter_of_the_time(model):
    """The fit's out-of-time evaluation (`evaluation.coverage`, written by ipl_price_model.py): in every
    band of model price with 20+ held-out lots, the real price beats `high` 15-35% of the time (a true
    upper quartile: 25%)."""
    cov = (model.get("evaluation") or {}).get("coverage")
    assert cov, "the fit wrote no coverage by price band"
    for band in cov:
        if band["n"] >= 20:
            assert 0.15 <= band["above_high"] <= 0.35, band


def test_no_pool_price_beats_the_auction_record(model):
    """No player in the exported pool is priced above the IPL record, 27 cr (Pant, 2025): stars ran
    past it when the top end didn't flatten (METHODOLOGY §6b)."""
    if not POOL.exists():
        pytest.skip("no exported pool")
    rows = json.loads(POOL.read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("players", [])
    top = max(pricing.market_price(r, COMP, model)["price"] for r in rows
              if pricing.has_market_inputs(r, model))  # fmt: skip
    assert top <= 27.0, top
