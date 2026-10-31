"""The brand feature's input: a player's Wikipedia pageviews in the 12 months before an auction
(src/cricdesk/scout/identity/pageviews.py; METHODOLOGY §6b)."""

import math

from cricdesk.scout.identity import pageviews
from cricdesk.web_parity import pricing

DATA = {
    "first_month": "2015-07",
    "last_month": "2016-12",
    # July 2015 .. December 2016: 18 months, views = month number 1..18
    "views": {"A": list(range(1, 19)), "B": [0] * 18},
}


def test_window_is_the_twelve_months_before_the_auction_month():
    # a December 2016 auction: Dec 2015 .. Nov 2016 = months 6..17
    assert pageviews.views_asof("A", "2016-12-16", DATA) == sum(range(6, 18)) / 12
    # an auction after the data ends: the last 12 months there are
    assert pageviews.views_asof("A", "2027-12-16", DATA) == sum(range(7, 19)) / 12


def test_no_reading_without_title_data_or_enough_months():
    assert pageviews.views_asof(None, "2016-12-16", DATA) is None
    assert pageviews.views_asof("Nobody", "2016-12-16", DATA) is None
    assert pageviews.views_asof("A", "2015-11-01", DATA) is None  # 4 months only
    assert pageviews.views_asof("B", "2016-12-16", DATA) == 0.0


def test_brand_features():
    f = pricing.market_features({"price_value": 1.0, "role": "batter", "wiki_views": 99000}, "mini")
    assert math.isclose(f["brand"], math.log(100.0)) and f["no_brand"] == 0.0
    assert f["brand_x_indian"] == f["brand"]
    g = pricing.market_features({"price_value": 1.0, "role": "batter", "is_overseas": True}, "mini")
    assert g["brand"] == 0.0 and g["no_brand"] == 1.0 and g["brand_x_indian"] == 0.0
