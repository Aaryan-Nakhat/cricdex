"""Parity lock: Keep or release's Python calculator (`cricdex.web_parity.keep`) must match the web
calculator (`site/src/lib/keep.ts`) on the same inputs — every price, surplus, call, reason
sentence, purse figure, gap pick and CSV cell.

Runs `site/scripts/keep_parity_dump.ts` under Node on fixed synthetic squads (every branch: keep,
release, borderline, unrated, overrides, role targets, overseas room, a purse overrun, franchise
ties) plus, when present, every real team from the exported keep.json, and the retention model's
features and probability on fixed inputs. Skips if Node is unavailable (fails in CI, see
conftest.py).
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from test_web_parity import _approx_eq  # test_scripts/ is on sys.path (rootdir import mode)

from cricdex.config import SITE_DATA
from cricdex.web_parity import build_pool
from cricdex.web_parity.keep import (
    cr,
    cr_exact,
    evaluate,
    fmt_num,
    free_agents,
    keep_features,
    keep_probability,
    load_keep_model,
    market_for,
    to_csv_rows,
)

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

RULES = {
    "purse": 125.0,
    "squad_min": 18,
    "squad_max": 25,
    "overseas_max": 8,
    "max_retained": 0,
    "max_overseas_retained": 0,
    "replacements_retainable": True,
}
FORM = {"season": 2026, "bat_sr": 156.34, "bowl_econ": 9.767}


def _p(i, team="AAA", salary=1.0, value=0.0, sd=3.0, role="batter", balls=800, age=27.0, tags="",
       overseas=False, form=None, cid=True):  # fmt: skip
    return {
        "id": f"s{i:02d}" if cid else None,
        "name": f"Player {i}",
        "team": team,
        "salary": salary,
        "acquired": "auction",
        "overseas": overseas,
        "country": "AUS" if overseas else "IND",
        "role": role,
        "value": value,
        "value_sd": None if value is None else sd,
        "target_balls": balls,
        "balls": balls,
        "age": age,
        "tags": tags + ("x" if overseas and "x" not in tags else ""),
        "form": form,
        "withdrawn": None,
        "trade": None,
        "profile": "ipl",
        "note": None,
    }


SQUAD = [
    _p(1, salary=14, value=22.9, sd=3.1, balls=2400, tags="o"),  # big keep
    _p(2, salary=14, value=-6.4, sd=4.0, balls=1500),  # clear release
    _p(3, salary=5, value=8.0, sd=12.0, balls=250, age=21.2, tags="o"),  # thin record
    _p(4, salary=6, value=4.5, sd=3.0, role="all_rounder", tags="s"),  # fairly paid
    _p(5, salary=9, value=14.0, sd=3.0, age=37.6, role="keeper", tags="k"),  # age downgrade
    _p(6, salary=0.3, value=None, cid=False),  # unrated, name key
    _p(7, salary=12, value=24.0, sd=2.5, age=37.6, role="bowler", tags="sdx", overseas=True,
       form={"bowl": [240, 330, 14], "bat": [40, 60, 3]}),  # fmt: skip
    _p(8, salary=11.75, value=3.0, role="bowler", tags="dx", overseas=True, form={"bowl": [200, 340, 9]}),
    _p(9, salary=0.75, value=-2.5, role="bowler", tags="s", form={"bowl": [20, 30, 1]}),
    _p(10, salary=2.4, value=1.0, role="all_rounder", tags="x", overseas=True, age=None),
    _p(11, salary=0.3, value=-1.0, role="keeper", tags="k", form={"bat": [120, 190, 5]}),
    _p(12, salary=13.25, value=13.3, sd=2.6, role="bowler", tags="s", age=32.1),
    _p(13, salary=25.2, value=6.9, sd=4.4, role="all_rounder", tags="x", overseas=True),
]  # fmt: skip


def _fc(median, flag, p_reg, avg3=None):
    """A Form forecast "3-season outlook" (scout/forecast.py `keep_outlook`), for the pass-through."""
    return {
        "role": "batter",
        "seasons": [2027, 2028, 2029],
        "median": median,
        "avg3": avg3 if avg3 is not None else round(sum(median) / 3, 1),
        "flag": flag,
        "p_regular_last": p_reg,
        "level": median[0],
        "text": "x",
    }


# half-way values check the rounding agrees (half up on both sides)
SQUAD[0]["forecast"] = _fc([12.5, 11.0, 9.4], "hold", 0.935)
SQUAD[4]["forecast"] = _fc([-2.5, -4.5, -6.0], "decline", 0.205)
SQUAD[6]["forecast"] = _fc([20.0, 19.5, 0.4], "hold_then_decline", 0.475)
SQUAD[11]["forecast"] = _fc([0.0, 2.6, 4.5], "improve", 0.5)

# 2025 mega-auction retentions charged by the retention slabs (only under SLAB_RULES): four capped
# (18 + 14 + 11 + 18 = 61 against 14 + 14 + 13.25 + 25.2 = 66.45 of salary, so the salaries count)
# and one uncapped (4 against 0.3)
for i, k in ((0, "capped"), (1, "capped"), (11, "capped"), (12, "capped"), (5, "uncapped")):
    SQUAD[i]["slab_holder"] = k
SLAB_RULES = {"retained_cost": "slabs", "retention_slabs": [18.0, 14.0, 11.0, 18.0, 14.0],
              "uncapped_retention_slab": 4.0}  # fmt: skip

# franchise ties (the retention model): a home-grown captain with seasons there, a one-season buy
SQUAD[0].update(home_grown=True, seasons_here=8, captain_teams=["AAA"])
SQUAD[6].update(seasons_here=1)
SQUAD[11].update(home_grown=True, seasons_here=3)

# a rating resting on stale SMAT data says so (issue I7): 0.845 rounds half up on both sides
SQUAD[2].update(stale_share=0.845, stale_note="SMAT data to Dec 2024")
SQUAD[8].update(stale_share=0.05, stale_note="SMAT data to Dec 2024")  # below the threshold

# another franchise: its Release calls join the market AAA shops in (BBB's keeper is a capped
# 2025 retention: under SLAB_RULES he costs the 18 cr slab, not his 12 cr salary)
OTHERS = [
    _p(
        21, team="BBB", salary=12, value=9.0, role="keeper", tags="ko"
    ),  # released: a keeper on sale
    _p(22, team="BBB", salary=10, value=4.0, role="bowler", tags="d"),  # released death bowler
    _p(23, team="BBB", salary=1, value=10.0, role="bowler", tags="ds"),  # kept by BBB: not on sale
    _p(24, team="BBB", salary=9, value=None, cid=False),  # unrated: never on sale
]
OTHERS[0]["slab_holder"] = "capped"


def _pool_row(i, value, sd=3.0, role="bowler", overseas=False, team=None, balls=700):
    return {
        "cricsheet_id": f"f{i:03d}",
        "name": f"Free {i}",
        "value": value,
        "value_sd": sd,
        "target_balls": balls,
        "role": role,
        "country": "ENG" if overseas else "IND",
        "is_overseas": overseas,
        "team": team,
    }


POOL = [
    _pool_row(1, 10.0, role="keeper"),
    _pool_row(2, -3.0, role="keeper", balls=0),
    _pool_row(3, 6.0, role="batter", overseas=True),
    _pool_row(4, 2.0, role="bowler"),
    _pool_row(5, 2.0, role="bowler", sd=3.0),  # tie with 4 on price + value → id order
    _pool_row(6, 12.0, role="bowler", overseas=True),
    _pool_row(7, 5.0, role="all_rounder"),
    _pool_row(8, 30.0, role="batter", team="AAA"),  # contracted: not a free agent
    _pool_row(9, -12.0, role="bowler"),
    _pool_row(10, 15.0, role="batter", balls=100),
]
POOL_TAGS = {"f001": "k", "f002": "k", "f003": "o", "f004": "d", "f005": "d", "f006": "ds",
             "f007": "s", "f009": "ds", "f010": "o"}  # fmt: skip


# the same squad priced by the market model (fitted to real auctions): each row also carries the
# market inputs (only used when config/price_model.json exists; else both sides use the curve)
def _mk(p: dict, caps: int, seasons: int, gap: float | None) -> dict:
    return {
        **p,
        "team": "MMM",
        "id": p["id"] and "m" + p["id"],
        "price_value": p["value"],
        "intl_caps": caps,
        "ipl_balls": p["balls"],
        "ipl_seasons": seasons,
        "ipl_gap": gap,
    }


MARKET_SQUAD = [
    {**_mk(SQUAD[0], 300, 12, 0.55), "captain_ipl_last": 1, "captain_ipl_seasons": 4,
     "captain_teams": ["MMM"]},
    _mk(SQUAD[1], 0, 6, 0.55), _mk(SQUAD[2], 0, 1, 0.55),
    _mk(SQUAD[3], 25, 4, 0.55), _mk(SQUAD[4], 120, 14, 0.55), _mk(SQUAD[6], 180, 9, 0.55),
    _mk(SQUAD[7], 60, 3, 1.6), _mk(SQUAD[9], 5, 0, None), _mk(SQUAD[12], 90, 2, 0.55),
    # no ball-by-ball record anywhere (issue I6): priced from the market as an uncapped Indian
    {**_p(31, salary=5.2, value=None, cid=False, age=None), "team": "MMM", "price_value": None,
     "intl_caps": 0, "intl_caps_2y": 0, "ipl_balls": 0, "ipl_seasons": 0, "ipl_gap": None,
     "target_balls": 0, "balls": 0},
    {**_p(32, salary=0.3, value=None, cid=False, age=19.4), "team": "MMM", "price_value": None,
     "intl_caps": 0, "intl_caps_2y": 0, "ipl_balls": 0, "ipl_seasons": 0, "ipl_gap": None,
     "target_balls": 0, "balls": 0},
]  # fmt: skip

CASES = [
    {"decisions": {}, "needs": {}},
    {"decisions": {"s02": "keep", "s01": "release", "name:AAA:Player 6": "release"}, "needs": {}},
    {"decisions": {}, "needs": {"keeper": 4, "spinner": 5, "overseas": 8, "death": 6}},
    {"decisions": {"s13": "keep", "s02": "keep"}, "needs": {"opener": 0}, "rules": {"purse": 40.0}},
    {"decisions": {}, "needs": {}, "rules": SLAB_RULES},
    {"decisions": {"s13": "release", "s01": "keep"}, "needs": {}, "rules": SLAB_RULES},
    {
        "decisions": {},
        "needs": {},
        "rules": {
            "squad_max": 12,
            "overseas_max": 3,
            "max_retained": 6,
            "max_overseas_retained": 1,
        },
    },  # fmt: skip
]
FMT = [0, 0.05, 0.25, 0.3, 0.75, 1.0, 1.05, 2.25, 9.95, 13.25, 16.35, -0.04, -0.05, -2.25, 125.0,
       0.995, 156.34, 9.767]  # fmt: skip


def _model() -> dict | None:
    from cricdex.web_parity.pricing import load_price_model

    load_price_model.cache_clear()
    return load_price_model()


def _keep_model() -> dict | None:
    load_keep_model.cache_clear()
    return load_keep_model()


# keep_features arguments: (market, cost, mega, forecast avg3, P(regular), captain here, seasons
# here, home-grown, capped Indian, overseas, age, IPL balls, bought at the last auction[, P(plays),
# contribution per match])
KEEP_CASES = [
    [12.5, 14.0, False, 3.4, 0.54, False, 19, True, True, False, 38.0, 6000, False],
    [0.3, 3.0, False, None, None, False, 1, True, False, False, 24.5, 15, True],
    [25.0, 0.0, True, -15.3, 0.2, True, 0, False, False, True, None, None, False],
    [1.1, 4.0, False, -15.8, 0.04, False, 16, True, True, False, 45.2, 4000, False],
    [8.0, 11.0, False, 6.1, 0.8, True, 6, False, True, False, 31.0, 2500, False, 0.86, 5.42],
    [2.0, 6.5, False, None, None, False, 2, False, False, True, 27.0, 300, True, 0.31, None],
    [4.0, 2.0, False, 1.0, 0.5, False, 3, True, False, False, 22.0, 700, True, 0.55, -1.2],
]


def _cases() -> list[dict]:
    out = [
        {
            "team": "MMM",
            "players": MARKET_SQUAD + OTHERS,
            "pool": POOL,
            "pool_tags": POOL_TAGS,
            "rules": RULES,
            "decisions": {},
            "needs": {},
            "form": FORM,
        }
    ]
    for c in CASES:
        out.append(
            {
                "team": "AAA",
                "players": SQUAD + OTHERS,
                "pool": POOL,
                "pool_tags": POOL_TAGS,
                "rules": {**RULES, **c.get("rules", {})},
                "decisions": c["decisions"],
                "needs": c["needs"],
                "form": FORM,
            }
        )
    keep_f = SITE_DATA / "ipl" / "keep.json"
    pool_f = SITE_DATA / "ipl" / "auction_pool.json"
    if keep_f.exists() and pool_f.exists():
        data = json.loads(keep_f.read_text(encoding="utf-8"))
        pool = json.loads(pool_f.read_text(encoding="utf-8"))
        for team in data["teams"]:
            out.append(
                {
                    "team": team,
                    "players": data["players"],
                    "pool": pool,
                    "pool_tags": data["pool_tags"],
                    "rules": data["competition"]["rules"],
                    "decisions": {},
                    "needs": {},
                    "form": data.get("form"),
                }
            )
    return out


def _python(cases: list[dict]) -> dict:
    out = []
    for c in cases:
        market = market_for(
            c["team"], c["players"], build_pool(c["pool"]), c["pool_tags"], c["form"], c["rules"]
        )
        squad = [p for p in c["players"] if p["team"] == c["team"]]
        res = evaluate(squad, market, c["rules"], c["decisions"], c["needs"], c["form"])
        out.append({"market": market, "res": res, "csv": to_csv_rows(res)})
    fmt = [[fmt_num(x, 0), fmt_num(x, 1), fmt_num(x, 2), cr(x), cr_exact(x)] for x in FMT]
    return {"out": out, "fmt": fmt}


def _node(cases: list[dict]) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        fx = Path(tmp) / "keep_fixture.json"
        fx.write_text(
            json.dumps(
                {
                    "cases": cases,
                    "fmt": FMT,
                    "model": _model(),
                    "keep_model": _keep_model(),
                    "keep_cases": KEEP_CASES,
                }
            ),  # fmt: skip
            encoding="utf-8",
        )
        r = subprocess.run(
            [
                "node",
                "--no-warnings",
                "--experimental-strip-types",
                "scripts/keep_parity_dump.ts",
                str(fx),
            ],  # fmt: skip
            cwd=SITE,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    if r.returncode != 0:
        pytest.skip(f"node strip-types unavailable / TS failed:\n{r.stderr[-800:]}")
    return json.loads(r.stdout)


def test_keep_parity():
    cases = _cases()
    js = _node(cases)
    py = _python(cases)
    _approx_eq(py["fmt"], js["fmt"], "fmt")
    assert len(py["out"]) == len(js["out"])
    for i, (a, b) in enumerate(zip(py["out"], js["out"], strict=True)):
        _approx_eq(a, b, f"case[{i}]")
    km = _keep_model()
    for i, (args, b) in enumerate(zip(KEEP_CASES, js["keepCases"], strict=True)):
        f = keep_features(*args)
        _approx_eq({"features": f, "p": keep_probability(f, km) if km else None}, b, f"keep[{i}]")


def test_keep_synthetic_calls():
    """The calls follow the retention model's chance kept (Keep ≥ 65%, Release < 35%, Borderline
    between, kept by default from 50%), and the purse follows the default plan."""
    from cricdex.web_parity.keep import BORDER_BAND, KEEP_CALL

    if _keep_model() is None:
        pytest.skip("no keep model")
    market = market_for("AAA", SQUAD + OTHERS, build_pool(POOL), POOL_TAGS, FORM)
    assert {m["id"] for m in market} >= {m["id"] for m in free_agents(build_pool(POOL), POOL_TAGS)}
    res = evaluate(SQUAD, market, RULES, {}, {}, FORM)
    for p in res["players"]:
        if p["p_keep"] is None:
            assert p["rec"] == "borderline" and p["kept"]
            continue
        want = ("keep" if p["p_keep"] >= KEEP_CALL + BORDER_BAND
                else "release" if p["p_keep"] < KEEP_CALL - BORDER_BAND else "borderline")  # fmt: skip
        assert p["rec"] == want, p["name"]
        assert p["kept"] == (p["p_keep"] >= KEEP_CALL), p["name"]
        assert f"franchises kept {math.floor(100 * p['p_keep'] + 0.5)}%" in p["reason"]
    # unrated with no market inputs: scout him, kept by default
    six = res["players"][5]
    assert six["rec"] == "borderline" and "Not enough balls" in six["reason"] and six["kept"]
    # the franchise ties are named in the reason
    assert (
        "captained AAA last season, home-grown, 8 seasons with AAA" in res["players"][0]["reason"]
    )
    assert "(1 season with AAA)" in res["players"][6]["reason"]
    # the other teams' players our calls release join the market; kept ones don't
    rel = {m["id"] for m in market if m["from_team"]}
    for p in OTHERS:
        a = evaluate([p], [], RULES, {}, {}, FORM)["players"][0]
        if p.get("value") is not None:
            assert (p["id"] in rel) == (not a["kept"])
    # released players free their salary; the contracted pool player is never a pick
    picks = {c["id"] for g in res["gaps"] for c in g["picks"]}
    assert "f008" not in picks
    assert res["purse_left"] == pytest.approx(
        125 - sum(p["salary"] for p in res["players"] if p["kept"])
    )
    # a flipped decision moves the purse by exactly that salary
    two = res["players"][1]
    flipped = evaluate(
        SQUAD, market, RULES, {"s02": "release" if two["kept"] else "keep"}, {}, FORM
    )
    assert flipped["purse_left"] == pytest.approx(res["purse_left"] + (14 if two["kept"] else -14))


def test_keep_model_is_the_backtested_one():
    """The shipped retention model is scripts/keep_backtest.py's: chosen on 2018-2024, tested once on
    2025-26, and its features are keep_features'."""
    km = _keep_model()
    if km is None:
        pytest.skip("no keep model")
    f = keep_features(*KEEP_CASES[0])
    assert set(km["coef"]) <= set(f)
    assert km["trained_on"] == [2018, 2026]
    assert "2018-2024" in km["evaluation"]["protocol"]["selection"]
    assert 0.0 < keep_probability(f, km) < 1.0


def test_keep_no_match_data_is_priced_from_the_market():
    """A squad player with no ball-by-ball record gets the market model's prior as his price (never
    a rating), and the reason says so (issue I6)."""
    from cricdex.web_parity.keep import NO_DATA_LABEL, assess

    if _model() is None:
        pytest.skip("no price model")
    for p in MARKET_SQUAD[-2:]:
        a = assess(p, FORM)
        assert a["no_data"]
        assert a["price"] is not None and a["price"] > 0 and a["onfield"] is None
        assert a["price_central"] >= a["price"]
        assert a["surplus"] == pytest.approx(a["price"] - p["salary"])
        assert a["reason"].startswith(NO_DATA_LABEL[0].upper() + NO_DATA_LABEL[1:])
        assert "an uncapped Indian" in a["reason"]
    # bought well above the prior: the reason credits the market, not "overpaid"
    assert "saw something our data can't" in assess(MARKET_SQUAD[-2], FORM)["reason"]
    assert "saw something" not in assess(MARKET_SQUAD[-1], FORM)["reason"]
    # without the market inputs (an old export) it stays unpriced, as before
    a = assess(SQUAD[5], FORM)
    assert not a["no_data"] and a["price"] is None and "Not enough balls" in a["reason"]


def test_keep_stale_share_in_the_reason():
    """A rating resting mostly on stale SMAT data says so with its share; a small share doesn't."""
    from cricdex.web_parity.keep import assess

    assert assess(SQUAD[2], FORM)["reason"].endswith(
        " 85% of his rating rests on SMAT data to Dec 2024 (stale)."
    )
    assert "stale" not in assess(SQUAD[8], FORM)["reason"]
    assert "stale" not in assess(SQUAD[0], FORM)["reason"]


def test_keep_default_plan_is_legal():
    """Over the squad or overseas limit, the default plan releases Borderline players first (lowest
    chance kept), overseas ones for the overseas cap, never a decided player, and says so."""
    market = market_for("AAA", SQUAD + OTHERS, build_pool(POOL), POOL_TAGS, FORM)
    rules = {**RULES, "squad_max": 8, "overseas_max": 1}
    res = evaluate(SQUAD, market, rules, {"s13": "keep"}, {}, FORM)
    kept = [p for p in res["players"] if p["kept"]]
    auto = [p for p in res["players"] if p["auto_release"]]
    assert sum(1 for p in kept if p.get("overseas")) <= 1 or all(
        p["overridden"] for p in kept if p.get("overseas")
    )
    assert len(kept) <= 8
    assert auto and all("Released to fit" in p["reason"] for p in auto)
    assert all(not p["overridden"] for p in auto)
    # no Keep goes while a Borderline of the same pass is still kept
    for kind in ("overseas", "squad"):
        gone_keeps = [p for p in auto if p["auto_release"] == kind and p["rec"] == "keep"]
        if gone_keeps:
            assert not any(
                p["kept"]
                and not p["overridden"]
                and p["rec"] == "borderline"
                and (kind == "squad" or p.get("overseas"))
                for p in res["players"]
            )
    # with room to spare nothing moves
    assert not any(
        p["auto_release"] for p in evaluate(SQUAD, market, RULES, {}, {}, FORM)["players"]
    )


def test_keep_slab_costs():
    """Under the retention slabs a team's 2025 retentions cost max(slab total, salary total)
    together, each one's cost is what releasing him alone frees, and the purse follows."""
    from cricdex.web_parity.keep import purse_charged, retention_costs, slab_charge

    rules = {**RULES, **SLAB_RULES}
    holders = [p for p in SQUAD if p.get("slab_holder")]
    # 4 capped: 61 of slabs + 4 uncapped = 65 against 66.75 of salaries: the salaries count
    assert slab_charge(holders, rules) == pytest.approx(66.75)
    costs = retention_costs(SQUAD, rules)
    # releasing the 25.2 cr player leaves 43 + 4 = 47 of slabs against 41.55 of salary: frees 19.75
    assert costs["s13"] == pytest.approx(66.75 - 47)
    # a player who isn't a retention costs his salary
    assert costs["s03"] == 5
    res = evaluate(SQUAD, [], rules, {}, {}, FORM)
    kept = [p for p in res["players"] if p["kept"]]
    assert res["purse_left"] == pytest.approx(125 - purse_charged(kept, rules))
    assert all(p["cost"] == pytest.approx(costs[p["key"]]) for p in res["players"])
    # under the salary rule nothing changes
    assert retention_costs(SQUAD, RULES) == {p.get("id") or f"name:AAA:{p['name']}": p["salary"]
                                              for p in SQUAD}  # fmt: skip
    # BBB's keeper costs his 18 cr slab in the market AAA shops in, not his 12 cr salary
    m = market_for("AAA", SQUAD + OTHERS, build_pool(POOL), POOL_TAGS, FORM, rules)
    assert retention_costs(OTHERS, rules)["s21"] == 18
    from cricdex.web_parity.keep import assess

    a = assess(OTHERS[0], FORM, 18.0)
    assert a["cost"] == 18
    assert any(x["id"] == "s21" for x in m) == (not a["default_keep"])
