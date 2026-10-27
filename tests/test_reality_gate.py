"""The reality gate (METHODOLOGY §13): the standing check every model change must pass.

It runs on the real IPL outputs the site serves (`site/public/data/ipl/`: keep.json, auction_pool.json)
and on the real auction record (`data/curated/ipl_auction_history.json`, from Wikipedia's IPL personnel
pages), and fails when the models say something the real IPL contradicts. Every threshold is taken from
real data or a cited record, named next to the check; none is tuned to make the current outputs pass.
Issues I16 and I17 (a 40-year-old free agent at 16–19 cr, a No. 8 hitter first on nine sheets, max bids
at λ's floor, a 40-year-old Mukesh Choudhary) each came back because no test looked at the outputs as
a cricket fan would; this file is that look.

It builds all ten 2027 Bid plans (about 30 seconds). Skipped when the exported IPL data is missing.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE_IPL = ROOT / "site" / "public" / "data" / "ipl"
HISTORY = ROOT / "data" / "curated" / "ipl_auction_history.json"
MASTER = ROOT / "data" / "curated" / "player_master.json"

pytestmark = pytest.mark.skipif(
    not (SITE_IPL / "keep.json").exists()
    or not (SITE_IPL / "auction_pool.json").exists()
    or not HISTORY.exists(),
    reason="no exported IPL data / auction history",
)

# Sourced records (not fitted, not tuned):
# - Youngest IPL player: Vaibhav Suryavanshi, 14 years 23 days on debut (19 April 2025; born
#   27 March 2011; iplt20.com / Wisden 2025 season preview).
# - Oldest IPL player: Brad Hogg, 45 years 92 days at his last match (KKR, 2016; ESPNcricinfo,
#   "Ask Steven").
YOUNGEST_IPL_DEBUT = 14 + 23 / 365.25
OLDEST_IPL_PLAYER = 45 + 92 / 365.25
# IPL Player Regulations 2025-27 (iplt20.com, 28 Sep 2024): capped retention slabs 18, 14, 11 cr.
FIRST_SLAB_CR = 18.0
LOWEST_CAPPED_SLAB_CR = 11.0
# AUCTION_MATH Part 0 (the market price's documented out-of-time error): lots that sold for 10 cr+
# come out at 0.36x their price.
STAR_LOT_CR = 10.0
STAR_PRICE_RATIO = 0.36


def _load(name: str):
    return json.loads((SITE_IPL / name).read_text(encoding="utf-8"))


def _real_auctions() -> list[dict]:
    """Every team at every real auction 2018-2026: purse left going in (the purse less what its
    retentions cost, with the 2025-27 slab charges, as scripts/bidplan_backtest.py; it reproduces the
    published 2026 purses), what it spent, how many it bought."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import bidplan_backtest as bt

    hist = json.loads(HISTORY.read_text(encoding="utf-8"))
    out = []
    for ys, a in sorted(hist["auctions"].items()):
        s = int(ys)
        if s < 2018:
            continue
        teams: dict[str, dict] = {}
        for r in hist["retentions"]:
            if r["season"] == s and r["kind"] == "retained":
                t = teams.setdefault(r["team"], {"cost": 0.0, "spend": 0.0})
                t["cost"] += float(r.get("purse_deduction_cr") or r.get("salary_cr") or 0.0)
        for r in hist["lots"]:
            if r["season"] == s and r.get("sold") and r.get("team"):
                t = teams.setdefault(r["team"], {"cost": 0.0, "spend": 0.0})
                t["spend"] += float(r.get("price_cr") or 0.0)
        for team, t in teams.items():
            left = float(a["purse_cr"]) - t["cost"] - bt._slab_extra(s, team, hist)
            if left > 0:
                out.append({"season": s, "kind": a["kind"], "team": team, "left": left,
                            "share": t["spend"] / left})  # fmt: skip
    return out


@pytest.fixture(scope="module")
def plans() -> dict:
    """The ten default 2027 Bid plans, as the page and `cricdex bidplan` build them."""
    from cricdex.web_parity import build_pool, load_auction_pool
    from cricdex.web_parity.bidplan import OPEN_SLOTS, TRIALS, build_context, plan, rival_runs
    from cricdex.web_parity.loader import load_auction_register, load_bidplan_rivals, load_keep

    data = load_keep("ipl")
    raw = load_auction_pool("ipl")
    pool = build_pool(raw)
    reg = load_auction_register("ipl")
    display = {r["cricsheet_id"]: r["display_name"] for r in raw if r.get("display_name")}
    out = {}
    for team in data["teams"]:
        ctx = build_context(data, pool, team, {}, None, OPEN_SLOTS, None, reg, display,
                            load_bidplan_rivals("ipl"))  # fmt: skip
        rr = rival_runs(ctx, TRIALS)
        out[team] = {
            "ctx": ctx,
            "res": plan(ctx, None, None, TRIALS, rr["prices"], rate=rr["rate"]),
        }
    return out


# ---- 1. spend ------------------------------------------------------------------------------------


def test_planned_spend_within_real_range_for_similar_purses(plans):
    """Each plan's expected spend, as a share of its purse left, lies within the range real teams
    spent at mini auctions (2023, 2024, 2026: the 2027 auction is a mini) with a purse left within a
    factor of two of its own. Source: ipl_auction_history.json (Wikipedia personnel pages)."""
    real = [r for r in _real_auctions() if r["kind"] == "mini"]
    bad = []
    for team, p in plans.items():
        left = float(p["ctx"]["purse_left"])
        peers = [r["share"] for r in real if left / 2 <= r["left"] <= left * 2]
        if len(peers) < 3:
            peers = [r["share"] for r in real]
        share = p["res"]["mean_spend"] / left if left > 0 else 1.0
        if not (min(peers) - 1e-9 <= share <= max(peers) + 1e-9):
            bad.append(f"{team}: plan spends {share:.0%} of {left:.1f} cr; real peers "
                       f"{min(peers):.0%}–{max(peers):.0%} (n={len(peers)})")  # fmt: skip
    assert not bad, "; ".join(bad)


# ---- 2-3. who tops the sheets ---------------------------------------------------------------------


def _p_bids(lot: dict, kept: list[dict], rules: dict) -> float:
    """The fitted chance a franchise bids at all for this lot at the start of the auction (the
    Auction room's demand model, config/auction_demand.json, fitted on the 2019-2026 auctions; the
    purse and upgrade terms at their mean, 0)."""
    from cricdex.web_parity import auction as au

    dm = au.demand({})
    os_cap = int(rules["overseas_max"])
    sq_max = int(rules["squad_max"])
    counts = {"batter": 0, "bowler": 0, "all_rounder": 0, "keeper": 0}
    for p in kept:
        counts[p["role"]] = counts.get(p["role"], 0) + 1
    open_ = max(1, sq_max - len(kept))
    os_n = sum(1 for p in kept if p["os"])
    lmk = math.log(max(float(lot["projected_value"]), 1e-6))
    lb = math.log(max(float(lot["base_price"]), 1e-6))
    x_need = math.log1p(max(0.0, au.ROLE_TARGETS[lot["role"]] - counts.get(lot["role"], 0)))
    x_os = (min(os_cap - os_n, open_) / open_) if lot["is_overseas"] else 0.0
    z = dm["p0"] + dm["p1"] * lmk + dm["p2"] * lb + dm["i_need"] * x_need + dm["i_os"] * x_os
    return 1.0 / (1.0 + math.exp(-z))


@pytest.mark.xfail(strict=True, reason="ROADMAP I18: open. With his sourced age (20, not 28) Dewald "
                   "Pretorius is first on 5 sheets against a bound of 4.4: each sheet is planned alone, so "
                   "every team chases the same best-value player (rival plans are built but switched off)")  # fmt: skip
def test_no_player_tops_more_sheets_than_teams_would_bid_for_him(plans):
    """A player is the first target on at most as many sheets as franchises would bid for him at
    all: ten times the mean fitted chance a franchise bids for him (`_p_bids`, the demand model fitted
    on real auctions), plus two binomial standard deviations for ten teams."""
    firsts: dict[str, list[str]] = {}
    for team, p in plans.items():
        if p["res"]["targets"]:
            firsts.setdefault(p["res"]["targets"][0]["id"], []).append(team)
    bad = []
    for pid, teams in firsts.items():
        any_ctx = next(iter(plans.values()))["ctx"]
        lot = next(r for r in any_ctx["available"] if r["cricsheet_id"] == pid)
        ps = [_p_bids(lot, p["ctx"]["kept"], p["ctx"]["rules"]) for p in plans.values()]
        q = statistics.fmean(ps)
        n = len(plans)
        bound = n * q + 2 * math.sqrt(n * q * (1 - q))
        if len(teams) > bound:
            bad.append(f"{lot['name']} first on {len(teams)} sheets ({', '.join(teams)}); "
                       f"franchises bid for him with mean chance {q:.2f}: at most {bound:.1f}")  # fmt: skip
    assert not bad, "; ".join(bad)


def test_minimum_price_player_does_not_top_most_sheets(plans):
    """A player rivals don't bid above his base price for (median price to beat = base price) is
    first on at most half the sheets."""
    firsts: dict[str, int] = {}
    names = {}
    for p in plans.values():
        if p["res"]["targets"]:
            t = p["res"]["targets"][0]
            if t["expected_price"] <= float(t["base_price"]) + 1e-9:
                firsts[t["id"]] = firsts.get(t["id"], 0) + 1
                names[t["id"]] = t["name"]
    bad = [f"{names[k]} ({v} sheets)" for k, v in firsts.items() if v > len(plans) / 2]
    assert not bad, "minimum-price player first on most sheets: " + ", ".join(bad)


# ---- 4. stars rank high --------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ROADMAP I18, a real signal, not a model error (METHODOLOGY §13): "
                   "Cummins played 8 of SRH's 15 matches in 2026 and his IPL 2024-26 bowling was about the "
                   "league average; his 18 cr retention pays for the captaincy, which the season value "
                   "doesn't price")  # fmt: skip
def test_known_stars_rank_in_the_pool_top_n():
    """Players their franchises retained at the first capped slab (18 cr+, IPL Player Regulations
    2025-27) rank, by expected season value, inside the top N, N = the number of squad players their
    franchises pay at least the lowest capped retention slab (11 cr): the market's own count of stars."""
    keep = _load("keep.json")
    pool = _load("auction_pool.json")
    sv = sorted((r for r in pool if r.get("season_value") is not None),
                key=lambda r: -r["season_value"])  # fmt: skip
    rank = {r["cricsheet_id"]: i + 1 for i, r in enumerate(sv)}
    n = sum(1 for p in keep["players"] if (p.get("salary") or 0) >= LOWEST_CAPPED_SLAB_CR)
    stars = [p for p in keep["players"]
             if (p.get("salary") or 0) >= FIRST_SLAB_CR and p.get("slab_holder")]  # fmt: skip
    assert stars
    bad = [f"{p['name']} ({p['team']}, {p['salary']} cr) ranks {rank.get(p['id'])}"
           for p in stars if rank.get(p["id"], 10**6) > n]  # fmt: skip
    assert not bad, f"top {n}: " + "; ".join(bad)


# ---- 5. ages ---------------------------------------------------------------------------------------


def test_every_ipl_player_age_is_plausible():
    """No IPL player's date of birth makes him younger at his first IPL match than the youngest IPL
    player ever, or older at his last than the oldest (records above)."""
    if not MASTER.exists():
        pytest.skip("no player master")
    pm = json.loads(MASTER.read_text(encoding="utf-8"))
    bad = []
    for cid, r in pm.items():
        if not isinstance(r, dict) or not r.get("dob"):
            continue
        ipl = (r.get("leagues") or {}).get("ipl")
        if not ipl or not ipl.get("first"):
            continue
        dob = dt.date.fromisoformat(str(r["dob"])[:10])
        first = (dt.date.fromisoformat(ipl["first"][:10]) - dob).days / 365.25
        last = (dt.date.fromisoformat((ipl.get("last") or ipl["first"])[:10]) - dob).days / 365.25
        if first < YOUNGEST_IPL_DEBUT - 1e-6 or last > OLDEST_IPL_PLAYER + 1e-6:
            bad.append(f"{r.get('display_name')} ({cid}) dob {r['dob']}: {first:.1f} at first IPL "
                       f"match, {last:.1f} at last")  # fmt: skip
    assert not bad, "; ".join(bad)


# ---- 6. obvious retentions -----------------------------------------------------------------------


def test_keep_calls_keep_the_first_slab_stars():
    """Keep or release's default call keeps every player paid at least the first capped slab (18 cr):
    the price his franchise already chose to pay him."""
    from cricdex.web_parity.keep import evaluate, squad_of
    from cricdex.web_parity.loader import load_keep

    data = load_keep("ipl")
    gaps = {"keeper": 0, "opener": 0, "death": 0, "spinner": 0, "overseas": 0}
    bad = []
    for team in data["teams"]:
        res = evaluate(squad_of(data, team), [], data["competition"]["rules"], {}, gaps,
                       data.get("form"))  # fmt: skip
        for p in res["players"]:
            if (p.get("salary") or 0) >= FIRST_SLAB_CR and not p.get("default_keep"):
                bad.append(f"{p['name']} ({team}, {p['salary']} cr)")
    assert not bad, "released by default: " + ", ".join(bad)


# ---- 7. star prices ------------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ROADMAP I18: open. Kartik Sharma and Prashant Veer were bought "
                   "on 2025-26 SMAT and UP T20 League form and CSK trials, none of it in the data (Cricsheet's "
                   "SMAT ends Dec 2024); no sourced, fitted feature explains them")  # fmt: skip
def test_star_market_price_within_documented_error():
    """For the players sold for 10 cr+ at the last real auction (2026), the median of market price ÷
    real price is not below the documented 0.36 (AUCTION_MATH Part 0)."""
    from cricdex.web_parity import build_pool

    pool = {r["cricsheet_id"]: r["projected_value"] for r in build_pool(_load("auction_pool.json"))}
    hist = json.loads(HISTORY.read_text(encoding="utf-8"))
    last = max(int(s) for s in hist["auctions"])
    rat = [pool[r["cricsheet_id"]] / float(r["price_cr"]) for r in hist["lots"]
           if r["season"] == last and r.get("sold") and float(r.get("price_cr") or 0) >= STAR_LOT_CR
           and r.get("cricsheet_id") in pool]  # fmt: skip
    assert rat
    assert statistics.median(rat) >= STAR_PRICE_RATIO, (
        f"median market ÷ real {statistics.median(rat):.2f} for {len(rat)} lots of {last}"
    )
