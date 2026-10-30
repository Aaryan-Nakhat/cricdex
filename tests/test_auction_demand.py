"""The Auction room's bidding constants are the fitted demand model (config/auction_demand.json,
scripts/auction_demand_fit.py), in Python and in the browser alike; the ladder follows the IPL increments."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cricdex.web_parity import auction

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "auction_demand.json").read_text(encoding="utf-8"))


def test_python_constants_are_the_shipped_fit():
    p = CFG["params"]
    for k, v in auction.DEMAND.items():
        assert v == pytest.approx(round(float(p.get(k, 0.0)), 6), abs=1e-9), k
    assert auction.ROLE_TARGETS == CFG["role_targets"]
    assert auction.TEAM_EFFECTS == (p.get("team_effects") or {})


def test_ts_constants_match_python():
    ts = (ROOT / "site" / "src" / "lib" / "auction.ts").read_text(encoding="utf-8")
    block = re.search(r"export const DEMAND: Demand = \{(.*?)\n\}", ts, re.S).group(1)
    vals = {k: float(v) for k, v in re.findall(r"(\w+): (-?[\d.]+)", block)}
    assert vals == pytest.approx(auction.DEMAND)
    rt = re.search(r"export const ROLE_TARGETS: Record<Role, number> = \{(.*?)\}", ts).group(1)
    assert {k: float(v) for k, v in re.findall(r"(\w+): (-?[\d.]+)", rt)} == auction.ROLE_TARGETS


def test_ladder():
    assert auction.ladder_next(0.3) == 0.35
    assert auction.ladder_next(0.98) == 1.0
    assert auction.ladder_next(1.0) == 1.1
    assert auction.ladder_next(4.9) == 5.0
    assert auction.ladder_next(26.6) == 26.8  # 20 lakh above 5 cr (the 2024 and 2026 auctions)
    assert auction.ladder_next(14.0) == 14.2  # Veer and Kartik Sharma, 2026


def test_lots_scale_with_open_places():
    pool = [{"cricsheet_id": f"p{i}", "is_overseas": i % 2 == 0} for i in range(1000)]
    lots = auction.auction_lots(pool, 70, "mini")
    assert len(lots) == round(auction.LOTS_PER_PLACE["mini"] * 70)
    assert sum(p["is_overseas"] for p in lots) == round(len(lots) * auction.OVERSEAS_SHARE)
    assert len(auction.auction_lots(pool, 200, "mega")) == 600
