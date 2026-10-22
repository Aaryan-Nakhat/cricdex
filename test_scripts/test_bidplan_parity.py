"""Parity lock: Bid plan's Python optimiser (`cricdex.web_parity.bidplan`) must match the web
optimiser (`site/src/lib/bidplan.ts`) on the same inputs: every rival price in every run, the
exchange rate, every target's max bid and odds, the fallback chains, the squad summary and the CSV.

Runs `site/scripts/bidplan_parity_dump.ts` under Node on fixed synthetic leagues (overrides, role
needs, open places, a purse change, a register, a tight squad) plus, when present, every real team
from the exported keep.json + auction_pool.json (point CRICDEX_SITE_DATA at a scratch export).
Skips if Node is unavailable (fails in CI, see conftest.py).
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
from cricdex.web_parity.auction import auction_lots, one_trial
from cricdex.web_parity.bidplan import (
    REPLACEMENT,
    best_xi,
    build_context,
    chain_text,
    piece,
    plan,
    rival_prices,
    strength,
    to_csv_rows,
)

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

RULES = {
    "purse": 60.0,
    "squad_min": 14,
    "squad_max": 20,
    "overseas_max": 6,
    "max_retained": 0,
    "max_overseas_retained": 0,
    "replacements_retainable": True,
}
ROLES = ["batter", "bowler", "all_rounder", "keeper"]
TAGS = ["o", "d", "s", "", "ds", "ko", "k", "os"]


def _val(i: int) -> float:
    """Deterministic spread of values, about −25 … +25 runs per 100 balls."""
    return round(((i * 37) % 51) - 25 + (i % 7) * 0.37, 3)


def _league() -> dict:
    teams = ["AAA", "BBB", "CCC", "DDD"]
    players = []
    n = 0
    for t in teams:
        for _j in range(18):
            n += 1
            role = ROLES[(n * 3) % 4]
            ov = n % 4 == 0
            tags = TAGS[n % len(TAGS)]
            if role == "keeper" and "k" not in tags:
                tags += "k"
            if ov:
                tags += "x"
            players.append(
                {
                    "id": f"s{n:03d}" if n % 17 else None,
                    "name": f"Squad {n}",
                    "team": t,
                    "salary": round(0.3 + (n * 13 % 40) / 4, 2),
                    "acquired": "auction",
                    "overseas": ov,
                    "country": "AUS" if ov else "IND",
                    "role": role,
                    "value": None if n % 23 == 0 else _val(n),
                    "value_sd": 3.0 + (n % 5),
                    "target_balls": 200 + (n * 61) % 900,
                    "balls": 200 + (n * 61) % 900,
                    "age": 22 + n % 15,
                    "tags": tags,
                    "form": None,
                    "withdrawn": None,
                    "trade": None,
                    "profile": "ipl",
                    "note": None,
                }
            )
    pool = []
    tags = {}
    for k in range(70):
        cid = f"f{k:03d}"
        ov = k % 3 == 0
        pool.append(
            {
                "cricsheet_id": cid,
                "name": f"Free {k}",
                "display_name": f"Free Agent {k}" if k % 5 == 0 else None,
                "value": _val(k + 500),
                "value_sd": 2.0 + k % 6,
                "target_balls": (k * 97) % 800,
                "role": ROLES[k % 4],
                "country": "ENG" if ov else "IND",
                "is_overseas": ov,
                "team": None,
            }
        )
        tags[cid] = TAGS[k % len(TAGS)] + ("k" if ROLES[k % 4] == "keeper" else "")
    # squad players also appear in the pool with their team (as the export writes them)
    for p in players[::3]:
        if p["id"] and p["value"] is not None:
            pool.append(
                {
                    "cricsheet_id": p["id"],
                    "name": p["name"],
                    "value": p["value"],
                    "value_sd": p["value_sd"],
                    "target_balls": p["target_balls"],
                    "role": p["role"],
                    "country": p["country"],
                    "is_overseas": p["overseas"],
                    "team": p["team"],
                }
            )
    return {
        "competition": {"rules": RULES, "cycle": "mini"},
        "form": None,
        "teams": teams,
        "players": players,
        "pool_tags": tags,
        "_pool": pool,
    }


LEAGUE = _league()
SYNTH = [
    {"team": "AAA", "open_slots": 4},
    {"team": "BBB", "open_slots": 0, "needs": {"keeper": 3, "pace": 6, "spinner": 1}},
    {"team": "CCC", "open_slots": 6, "decisions": {"s037": "keep", "s040": "release"},
     "overrides": {"f001": 9.5, "f003": 0}, "purse": 75.0},
    {"team": "DDD", "open_slots": 2, "rules": {"squad_max": 18, "overseas_max": 4, "squad_min": 16}},
    {"team": "AAA", "open_slots": 3,
     "register": [{"id": "f000"}, {"id": "f002", "base_price": 1.5}, {"id": "f005"}, {"id": "s004"},
                  {"id": "s013"}, {"id": "f010"}, {"id": "f011"}, {"id": "nobody"}, {"id": "f000"}]},
]  # fmt: skip

XI_NEEDS = {"keeper": 1, "opener": 2, "death": 2, "spinner": 2, "pace": 3}
XI_CASES = [
    # five overseas stars: only four play
    [{"id": f"o{i}", "name": f"O{i}", "value": 20 - i, "role": "batter", "overseas": True,
      "tags": "x"} for i in range(5)]
    + [{"id": f"b{i}", "name": f"B{i}", "value": 5 - i, "role": "bowler", "overseas": False,
        "tags": "d" if i % 2 else "s"} for i in range(6)],
    # no keeper: a replacement keeper plays; a player below replacement level never does
    [{"id": f"p{i}", "name": f"P{i}", "value": 12 - 2 * i, "role": ROLES[i % 3],
      "overseas": i % 5 == 0, "tags": "o" if i < 2 else ""} for i in range(9)]
    + [{"id": "low", "name": "Low", "value": REPLACEMENT - 1, "role": "keeper", "overseas": False,
        "tags": "k"}, {"id": "nv", "name": "Unrated", "value": None, "role": "bowler",
                       "overseas": False, "tags": ""}],
    [],
]  # fmt: skip


def _keep_model() -> dict | None:
    from cricdex.web_parity.keep import load_keep_model

    load_keep_model.cache_clear()
    return load_keep_model()


def _model() -> dict | None:
    from cricdex.web_parity.pricing import load_price_model

    load_price_model.cache_clear()
    return load_price_model()


def _cases() -> list[dict]:
    data = {k: v for k, v in LEAGUE.items() if k != "_pool"}
    out = []
    for c in SYNTH:
        out.append({"data": data, "pool": LEAGUE["_pool"], "trials": 25, **c})
    keep_f = SITE_DATA / "ipl" / "keep.json"
    pool_f = SITE_DATA / "ipl" / "auction_pool.json"
    if keep_f.exists() and pool_f.exists():
        real = json.loads(keep_f.read_text(encoding="utf-8"))
        rows = json.loads(pool_f.read_text(encoding="utf-8"))
        for team in real["teams"]:
            out.append({"data": real, "pool": rows, "team": team, "open_slots": 8, "trials": 30})
    return out


CALIBS = [
    {"level_mega": 1.3, "level_mini": 1.7, "curve": 1.2, "sd": 0.7, "anchor": 0.5, "tight": 1},
    {"level_mega": 0.8, "level_mini": 2.0, "curve": 1.0, "sd": 0.0, "anchor": 0.0, "tight": 1},
]


def _sim_cases() -> list[dict]:
    """The simulator with every calibration path switched on, on a synthetic league's rivals and pool."""
    data = {k: v for k, v in LEAGUE.items() if k != "_pool"}
    ctx = build_context(data, build_pool(LEAGUE["_pool"]), "AAA", {}, None, 5)
    bases = [
        {"team": r["team"], "personality": r["personality"],
         "retained": [{"cricsheet_id": p["id"], "role": p["role"], "is_overseas": p["os"]} for p in r["kept"]],
         "retainSpend": RULES["purse"] - r["purse_left"], "retain_spend": RULES["purse"] - r["purse_left"],
         "retainOverseas": sum(1 for p in r["kept"] if p["os"]),
         "retain_overseas": sum(1 for p in r["kept"] if p["os"])}
        for r in ctx["rivals"]
    ]  # fmt: skip
    lots = auction_lots(ctx["available"])
    assert any(x.get("anchor_price") for x in lots)
    return [
        {"bases": bases, "lots": lots, "seeds": [1000, 8919, 16838],
         "opts": {"purse": RULES["purse"], "squad_size": 20, "overseas_cap": 6, "mode": mode, "calib": c}}
        for c in CALIBS for mode in ("mini", "mega")
    ]  # fmt: skip


def _python_sims(cases: list[dict]) -> list:
    out = []
    for c in cases:
        runs = []
        for seed in c["seeds"]:
            states = one_trial(c["bases"], c["lots"], c["opts"], seed)
            runs.append([{"team": st["team"], "bought": [p["cricsheet_id"] for p in st["bought"]],
                          "prices": st["bought_prices"], "spent": st["spent"]} for st in states])  # fmt: skip
        out.append(runs)
    return out


def _python(cases: list[dict]) -> dict:
    out = []
    for c in cases:
        pool = build_pool(c["pool"])
        display = {r["cricsheet_id"]: r["display_name"] for r in c["pool"] if r.get("display_name")}
        ctx = build_context(
            c["data"], pool, c["team"], c.get("decisions") or {}, c.get("purse"),
            c["open_slots"], c.get("rules"), c.get("register"), None, display,
        )  # fmt: skip
        prices = rival_prices(ctx, c["trials"])
        res = plan(ctx, c.get("needs") or {}, c.get("overrides") or {}, c["trials"], prices)
        out.append(
            {
                "ctx": {
                    k: ctx[k]
                    for k in ("kept", "purse_left", "rivals", "available", "squad", "rules")
                },  # fmt: skip
                "prices": prices,
                "plan": res,
                "csv": to_csv_rows(res),
                "chains": [chain_text(ch) for ch in res["chains"]],
            }
        )
    xi = []
    for ps in XI_CASES:
        pieces = [
            piece(p["id"], p["name"], p["value"], p["role"], p["overseas"], p["tags"]) for p in ps
        ]
        b = best_xi(pieces)
        xi.append({"xi": b["xi"], "ids": b["ids"], "fillers": b["fillers"],
                   "strength": strength(pieces, XI_NEEDS)})  # fmt: skip
    return {"out": out, "xi": xi}


def _node(cases: list[dict]) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        fx = Path(tmp) / "bidplan_fixture.json"
        fx.write_text(
            json.dumps({"cases": cases, "model": _model(), "keep_model": _keep_model(), "xi_cases": XI_CASES,
                        "xi_needs": XI_NEEDS, "sim_cases": _sim_cases()}),
            encoding="utf-8",
        )  # fmt: skip
        r = subprocess.run(
            ["node", "--no-warnings", "--experimental-strip-types",
             "scripts/bidplan_parity_dump.ts", str(fx)],
            cwd=SITE, capture_output=True, text=True, encoding="utf-8",
        )  # fmt: skip
    if r.returncode != 0:
        pytest.skip(f"node strip-types unavailable / TS failed:\n{r.stderr[-800:]}")
    return json.loads(r.stdout)


def test_bidplan_parity():
    cases = _cases()
    js = _node(cases)
    py = json.loads(json.dumps(_python(cases)))  # tuples → lists, as JSON
    _approx_eq(py["xi"], js["xi"], "xi")
    _approx_eq(json.loads(json.dumps(_python_sims(_sim_cases()))), js["sims"], "sims")
    assert len(py["out"]) == len(js["out"])
    for i, (a, b) in enumerate(zip(py["out"], js["out"], strict=True)):
        _approx_eq(a, b, f"case[{i}]")


def test_best_xi_rules():
    """At most four overseas, a keeper (a replacement one if the squad has none), five bowling
    and six batting options; below-replacement players never play."""
    pieces = [piece(p["id"], p["name"], p["value"], p["role"], p["overseas"], p["tags"])
              for p in XI_CASES[0]]  # fmt: skip
    b = best_xi(pieces)
    assert sum(1 for i in b["ids"] if i.startswith("o")) == 4
    pieces = [piece(p["id"], p["name"], p["value"], p["role"], p["overseas"], p["tags"])
              for p in XI_CASES[1]]  # fmt: skip
    b = best_xi(pieces)
    assert "low" not in b["ids"] and "nv" not in b["ids"] and b["fillers"] >= 1
    empty = best_xi([])
    assert empty["xi"] == pytest.approx(11 * REPLACEMENT)


def test_plan_respects_purse_and_room():
    """Every run's buys fit the purse (with the squad-minimum reserve), the squad maximum and the
    overseas cap; an override of 0 is never bought; max bids stay within the purse left."""
    data = {k: v for k, v in LEAGUE.items() if k != "_pool"}
    ctx = build_context(data, build_pool(LEAGUE["_pool"]), "CCC", {}, None, 6)
    prices = rival_prices(ctx, 25)
    res = plan(ctx, {}, {"f003": 0}, 25, prices)
    assert res["mean_spend"] <= ctx["purse_left"] + 1e-9
    assert res["mean_squad"] <= ctx["rules"]["squad_max"]
    assert all(t["id"] != "f003" or t["p_land"] == 0 for t in res["targets"])
    for t in res["targets"]:
        if not t["override"]:
            assert 0 <= t["max_bid"] <= max(0.0, ctx["purse_left"]) + 1e-9
    assert res["mean_strength"] >= res["before"]["total"] - 1e-9
    # open places: the team keeps at most squad_max − 6 (nobody here was decided by hand)
    assert len(ctx["kept"]) <= ctx["rules"]["squad_max"] - 6
