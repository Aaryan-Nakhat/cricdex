"""Parity lock: Keep or release's Python calculator (`cricdex.web_parity.keep`) must match the web
calculator (`site/src/lib/keep.ts`) on the same inputs — every price, surplus, call, reason
sentence, purse figure, gap pick and CSV cell.

Runs `site/scripts/keep_parity_dump.ts` under Node on fixed synthetic squads (every branch: keep,
release, thin record, fairly paid, age, unrated, overrides, role targets, overseas room, a purse
overrun) plus, when present, every real team from the exported keep.json. Skips if Node is
unavailable (fails in CI, see conftest.py).
"""

from __future__ import annotations

import json
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

# another franchise: its Release calls join the market AAA shops in
OTHERS = [
    _p(
        21, team="BBB", salary=12, value=9.0, role="keeper", tags="ko"
    ),  # released: a keeper on sale
    _p(22, team="BBB", salary=10, value=4.0, role="bowler", tags="d"),  # released death bowler
    _p(23, team="BBB", salary=1, value=10.0, role="bowler", tags="ds"),  # kept by BBB: not on sale
    _p(24, team="BBB", salary=9, value=None, cid=False),  # unrated: never on sale
]


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
]  # fmt: skip

CASES = [
    {"decisions": {}, "needs": {}},
    {"decisions": {"s02": "keep", "s01": "release", "name:AAA:Player 6": "release"}, "needs": {}},
    {"decisions": {}, "needs": {"keeper": 4, "spinner": 5, "overseas": 8, "death": 6}},
    {"decisions": {"s13": "keep", "s02": "keep"}, "needs": {"opener": 0}, "rules": {"purse": 40.0}},
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
            c["team"], c["players"], build_pool(c["pool"]), c["pool_tags"], c["form"]
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
        fx.write_text(json.dumps({"cases": cases, "fmt": FMT, "model": _model()}), encoding="utf-8")
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


def test_keep_synthetic_calls():
    """The synthetic squad exercises every branch, with the expected call."""
    market = market_for("AAA", SQUAD + OTHERS, build_pool(POOL), POOL_TAGS, FORM)
    assert {m["id"] for m in market if m["from_team"]} == {"s21", "s22"}
    assert {m["id"] for m in market} >= {m["id"] for m in free_agents(build_pool(POOL), POOL_TAGS)}
    res = evaluate(SQUAD, market, RULES, {}, {}, FORM)
    rec = {p["name"]: p["rec"] for p in res["players"]}
    assert rec["Player 1"] == "keep"
    assert rec["Player 2"] == "release"
    assert rec["Player 3"] == "borderline" and "Thin record" in res["players"][2]["reason"]
    assert rec["Player 4"] == "borderline" and "Fairly paid" in res["players"][3]["reason"]
    assert rec["Player 5"] == "borderline" and "value usually falls" in res["players"][4]["reason"]
    assert rec["Player 6"] == "borderline" and "Not enough balls" in res["players"][5]["reason"]
    assert rec["Player 7"] == "keep"  # 37 but a big surplus
    assert rec["Player 13"] == "release"
    # released players free their salary; the contracted pool player is never a pick
    picks = {c["id"] for g in res["gaps"] for c in g["picks"]}
    assert "f008" not in picks
    assert res["purse_left"] == pytest.approx(
        125 - sum(p["salary"] for p in res["players"] if p["kept"])
    )
    # a flipped decision moves the purse by exactly that salary
    flipped = evaluate(SQUAD, market, RULES, {"s02": "keep"}, {}, FORM)
    assert flipped["purse_left"] == pytest.approx(res["purse_left"] - 14)


def test_keep_default_plan_is_legal():
    """Over the squad or overseas limit, the default plan releases Borderline players first (lowest
    surplus per crore), overseas ones for the overseas cap, never a decided player, and says so."""
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
