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
from cricdex.web_parity.auction import auction_lots, one_trial, open_squad_places
from cricdex.web_parity.bidplan import (
    REPLACEMENT,
    XI_SIZE,
    best_xi,
    build_context,
    chain_text,
    gap_costs,
    piece,
    plan,
    rival_prices,
    rival_runs,
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


# balls faced and bowled a match by role (the export's playing-time fields, METHODOLOGY §6c)
_BALLS = {"batter": (24.0, 0.0), "keeper": (19.0, 0.0), "all_rounder": (13.0, 16.0),
          "bowler": (3.0, 22.5)}  # fmt: skip


def _contrib(v: float | None, role: str, i: int) -> dict:
    """Synthetic playing-time fields from a value: runs above replacement per match, batting and
    bowling parts at the role's balls (replacement −10 per 100 balls), as export_site writes them."""
    if v is None:
        return dict.fromkeys(("contrib", "contrib_bat", "contrib_bowl", "balls_faced",
                              "balls_bowled", "p_play", "season_value"))  # fmt: skip
    f, b = _BALLS[role]
    f += i % 5
    cb = round((v + 10.0) * f / 100.0, 4) if f else 0.0
    cw = round((v - 4.0 + (i % 3)) * b / 100.0, 4) if b else 0.0
    p = round(0.3 + (i % 7) / 10.0, 3)
    return {"contrib": round(cb + cw, 4), "contrib_bat": cb, "contrib_bowl": cw,
            "balls_faced": f, "balls_bowled": b, "p_play": p,
            "season_value": round(p * (cb + cw) * 14, 3)}  # fmt: skip


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
                    **_contrib(None if n % 23 == 0 else _val(n), role, n),
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
                **_contrib(_val(k + 500), ROLES[k % 4], k),
                "value_sd": 2.0 + k % 6 + 0.013,  # no exact price ties with squad rows
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
                    **{
                        k: p[k]
                        for k in (
                            "contrib",
                            "contrib_bat",
                            "contrib_bowl",
                            "balls_faced",
                            "balls_bowled",
                            "p_play",
                            "season_value",
                        )
                    },
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
    # eight openers at 25 balls each and three bowlers: the XI can't face more than a side's
    # innings, so the batting parts are scaled to TEAM_BALLS (a keeper-opener among them)
    [{"id": f"t{i}", "name": f"T{i}", "value": 6.0 - 0.2 * i, "role": "keeper" if i == 0 else "batter",
      "overseas": False, "tags": "o", "parts": [6.0 - 0.2 * i, 0.0, 25.0, 0.0]} for i in range(8)]
    + [{"id": f"w{i}", "name": f"W{i}", "value": 4.0 - i, "role": "all_rounder", "overseas": False,
        "tags": "d", "parts": [0.5, 3.5 - i, 8.0, 24.0, 0.9 - 0.15 * i]} for i in range(5)],
    # an XI that misses matches (P(plays) 0.7), a squad bench player and two auction candidates on the
    # bench: a veteran free agent (P(plays) 0.04, the best contribution a match) gives at most 0.04 of
    # an appearance a match, the rest goes to the next names
    [{"id": f"x{i}", "name": f"X{i}", "value": 3.0, "role": ROLES[i % 4], "overseas": False,
      "tags": "k" if i % 4 == 3 else "", "parts": [1.5, 1.5, 12.0, 12.0, 0.7]} for i in range(XI_SIZE)]
    + [{"id": "vet", "name": "Veteran", "value": 7.0, "role": "batter", "overseas": False, "tags": "o",
        "parts": [7.0, 0.0, 22.0, 0.0, 0.04], "cap": 0.04},
       {"id": "kid", "name": "Kid", "value": 2.0, "role": "batter", "overseas": False, "tags": "",
        "parts": [2.0, 0.0, 15.0, 0.0, 0.3], "cap": 0.3},
       {"id": "sub", "name": "Sub", "value": 1.0, "role": "bowler", "overseas": False, "tags": "",
        "parts": [0.0, 1.0, 2.0, 18.0, 0.2]}],
]  # fmt: skip


def _pieces(ps: list[dict]) -> list[dict]:
    out = []
    for p in ps:
        q = piece(p["id"], p["name"], p["value"], p["role"], p["overseas"], p["tags"],
                  tuple(p["parts"]) if p.get("parts") else None)  # fmt: skip
        if "cap" in p:
            q["cap"] = p["cap"]
        out.append(q)
    return out


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
    # P(plays) of a lot once bought (the buy model, ROADMAP I18; off in the export, locked here)
    pt_model = json.loads((ROOT / "config" / "playing_time_model.json").read_text(encoding="utf-8"))
    if pt_model.get("buy"):
        b = pt_model["buy"]
        pool = [dict(r, age=24.0 + (i % 15), ipl_matches=(i * 7) % 60, last_share=None if i % 3 else 0.5,
                     captain_ipl_last=1 if i == 2 else 0) for i, r in enumerate(LEAGUE["_pool"])]  # fmt: skip
        out.append({"data": {**data, "buy_model": {"intercept": b["intercept"], "coef": b["coef"],
                                                   "season": 2027}},
                    "pool": pool, "trials": 25, "team": "BBB", "open_slots": 5})  # fmt: skip
    # the rivals' own plans chasing two lots (ROADMAP I2): every rival but ours, two targets each
    ids = [r["cricsheet_id"] for r in LEAGUE["_pool"]][:3]
    out.append(
        {
            "data": data,
            "pool": LEAGUE["_pool"],
            "trials": 25,
            "team": "AAA",
            "open_slots": 4,
            "rival_bids": {t: {ids[0]: [3.0, 0.6], ids[2]: [1.2, 0.9]} for t in data["teams"]},
        }
    )
    keep_f = SITE_DATA / "ipl" / "keep.json"
    pool_f = SITE_DATA / "ipl" / "auction_pool.json"
    if keep_f.exists() and pool_f.exists():
        real = json.loads(keep_f.read_text(encoding="utf-8"))
        rows = json.loads(pool_f.read_text(encoding="utf-8"))
        riv_f = SITE_DATA / "ipl" / "bidplan_rivals.json"
        riv = json.loads(riv_f.read_text(encoding="utf-8"))["teams"] if riv_f.exists() else None
        for team in real["teams"]:
            out.append(
                {
                    "data": real,
                    "pool": rows,
                    "team": team,
                    "open_slots": 8,
                    "trials": 30,
                    "rival_bids": riv,
                }
            )
    # the "opportunity" money rule (candidate of 2026-10-29) on the synthetic league and two real teams
    synth = [c for c in out if c["pool"] is LEAGUE["_pool"]]
    reals = [c for c in out if c["pool"] is not LEAGUE["_pool"] and c["data"] is not data][:2]
    out += [{**c, "money": "opportunity"} for c in synth + reals]
    return out


# demand models with every path switched on (interest by needs, heat, anchor, stage, mega), and a
# near-deterministic one (no heat, every team bids)
DEMANDS = [
    {"a": 0.4, "c": 0.3, "sigma": 0.5, "tau": 0.7, "p0": -1.5, "p1": 0.4, "p2": 0.2, "base": 0.2,
     "anchor": 0.1, "money": 0.6, "stage": -1.3, "mega": 0.2, "need": 0.35, "os": 1.3, "pps": 0.5,
     "up": 0.03, "i_need": 0.3, "i_os": -0.3, "i_pps": -0.4, "i_up": 0.01, "val": 0.05, "i_val": 0.1, "heat_q": 0.2, "tau2": 1.5, "hinge": 0.3},
    {"a": 0.0, "c": 1.0, "sigma": 0.3, "tau": 0.0, "p0": 5.0, "p1": 0.0, "p2": 0.0, "base": 0.0,
     "anchor": 0.0, "money": 0.0, "stage": 0.0, "mega": 0.0, "need": 0.0, "os": 0.0, "pps": 0.0,
     "up": 0.0, "i_need": 0.0, "i_os": 0.0, "i_pps": 0.0, "i_up": 0.0, "val": 0.0, "i_val": 0.0, "heat_q": 0.0, "tau2": 0.0, "hinge": 0.0},
]  # fmt: skip


def _sim_cases() -> list[dict]:
    """The simulator with every demand path switched on, on a synthetic league's rivals and pool
    (some lots uncapped, some with a last price as a purse share)."""
    data = {k: v for k, v in LEAGUE.items() if k != "_pool"}
    ctx = build_context(data, build_pool(LEAGUE["_pool"]), "AAA", {}, None, 5)
    bases = [
        {"team": r["team"],
         "retained": [{"cricsheet_id": p["id"], "role": p["role"], "is_overseas": p["os"], "v": p["v"]}
                      for p in r["kept"]],
         "retainSpend": RULES["purse"] - r["purse_left"], "retain_spend": RULES["purse"] - r["purse_left"],
         "retainOverseas": sum(1 for p in r["kept"] if p["os"]),
         "retain_overseas": sum(1 for p in r["kept"] if p["os"])}
        for r in ctx["rivals"]
    ]  # fmt: skip
    lots = [dict(x) for x in auction_lots(ctx["available"], open_squad_places(bases, 20), "mini")]
    for i, x in enumerate(lots):
        x["capped"] = i % 3 != 0
        if i % 4 == 1 and not x.get("anchor_price"):
            x["prior_share"] = 0.01 + 0.003 * i
    assert any(x.get("anchor_price") for x in lots)
    return [
        {"bases": bases, "lots": lots, "seeds": [1000, 8919, 16838],
         "opts": {"purse": RULES["purse"], "squad_size": 20, "squad_min": 14, "overseas_cap": 6,
                  "mode": mode, "demand": d}}
        for d in DEMANDS for mode in ("mini", "mega")
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
            c["open_slots"], c.get("rules"), c.get("register"), display, c.get("rival_bids"),
        )  # fmt: skip
        runs = rival_runs(ctx, c["trials"])
        prices = runs["prices"]
        res = plan(ctx, c.get("needs") or {}, c.get("overrides") or {}, c["trials"], prices,
                   rate=runs["rate"], money=c.get("money") or "auction")  # fmt: skip
        out.append(
            {
                "ctx": {
                    k: ctx[k]
                    for k in ("kept", "purse_left", "rivals", "available", "squad", "rules")
                },  # fmt: skip
                "prices": prices,
                "market": {k: runs[k] for k in ("rate", "rival_gain", "rival_spend")},
                "plan": res,
                "csv": to_csv_rows(res),
                "chains": [chain_text(ch) for ch in res["chains"]],
                "gaps": gap_costs(
                    ctx,
                    res,
                    c.get("needs") or {},
                    c.get("overrides") or {},
                    prices,
                    runs["rate"],
                    c.get("money") or "auction",
                ),  # fmt: skip
            }
        )
    xi = []
    for ps in XI_CASES:
        pieces = _pieces(ps)
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
    assert empty["xi"] == pytest.approx(XI_SIZE * REPLACEMENT)


def test_best_xi_balls_budget():
    """An XI whose expected balls faced pass a side's innings has its batting parts scaled down to
    TEAM_BALLS, every member alike; bowling parts too; nothing is scaled up."""
    from cricdex.web_parity.bidplan import TEAM_BALLS

    pieces = [piece(p["id"], p["name"], p["value"], p["role"], p["overseas"], p["tags"],
                    tuple(p["parts"])) for p in XI_CASES[3]]  # fmt: skip
    b = best_xi(pieces)
    chosen = [p for p in pieces if p["id"] in b["ids"]]
    faced = sum(p["fb"] for p in chosen)
    bowled = sum(p["wb"] for p in chosen)
    sb = min(1.0, TEAM_BALLS / faced)
    sw = min(1.0, TEAM_BALLS / bowled)
    assert faced > TEAM_BALLS and sb < 1
    assert b["xi"] == pytest.approx(
        sb * sum(p["cb"] for p in chosen) + sw * sum(p["cw"] for p in chosen)
    )


def test_bench_cap_by_p_play():
    """The side's missed appearances (12 × 0.3 = 3.6 a match) go to the bench, best contribution a
    match first, each candidate at most his P(plays): the veteran (7 a match, P 0.04) fills 0.04,
    the kid (2 a match, P 0.3) 0.3, the squad's bench bowler (1 a match) a whole appearance."""
    from cricdex.web_parity.bidplan import bench_fill

    pieces = _pieces(XI_CASES[4])
    b = best_xi(pieces)
    assert set(b["ids"]) == {f"x{i}" for i in range(XI_SIZE)}
    depth = bench_fill(b["ids"], pieces, b["bench"])
    assert depth == pytest.approx(0.04 * 7.0 + 0.3 * 2.0 + 1.0 * 1.0)
    # without the cap the veteran alone would have filled a whole appearance a match
    for p in pieces:
        p["cap"] = 1.0
    assert bench_fill(b["ids"], pieces, b["bench"]) == pytest.approx(7.0 + 2.0 + 1.0 * 1.0)


def test_no_target_at_or_below_replacement():
    """A candidate whose contribution a match is at or below replacement level adds nothing to any
    squad, so the plan never bids for him (unless you set a max bid yourself)."""
    data = {k: v for k, v in LEAGUE.items() if k != "_pool"}
    ctx = build_context(data, build_pool(LEAGUE["_pool"]), "AAA", {}, None, 4)
    low = {r["cricsheet_id"] for r in ctx["available"]
           if r.get("contrib") is None or r["contrib"] <= REPLACEMENT}  # fmt: skip
    assert low
    res = plan(ctx, {}, {}, 25, rival_prices(ctx, 25))
    assert not [t for t in res["targets"] if t["id"] in low]
    assert all(t["gain"] > 0 for t in res["targets"] if t["max_bid"] > 0)


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


def test_unspent_purse_worth_what_later_lots_can_buy():
    """ROADMAP I17b (2026-10-27): a crore's worth at a lot is the gain per crore of the marginal later
    lot the money could still buy at its expected price, and a place's worth the gain of the lot it
    would push out when places run out first; both 0 after the last lot."""
    from cricdex.web_parity.bidplan import DEFAULT_NEEDS, _cands, _Gains, _median, _MoneyValue

    data = {k: v for k, v in LEAGUE.items() if k != "_pool"}
    ctx = build_context(data, build_pool(LEAGUE["_pool"]), "CCC", {}, None, 6)
    runs = rival_runs(ctx, 25)
    cands = _cands(ctx)
    gains = _Gains(ctx["kept"], cands, dict(DEFAULT_NEEDS))
    mv = _MoneyValue(cands, gains, [], [_median(ps) for ps in runs["prices"]])
    assert mv.items and all(a[0] >= b[0] for a, b in zip(mv.items, mv.items[1:], strict=False))
    assert mv.value(len(cands) - 1, 100.0, 10) == (0.0, 0.0)  # nothing left to buy
    assert mv.value(-1, 1e9, 10**6) == (0.0, 0.0)  # money and places cover everything
    assert mv.value(-1, 0.0, 10) == (mv.items[0][0], 0.0)  # no money: the best later lot's ratio
    # one place and plenty of money: the place is worth the gain of the lot that would fill it
    assert mv.value(-1, 1e9, 1) == (0.0, mv.items[0][3])
    # more money never makes a crore worth more (diminishing returns)
    rates = [mv.value(-1, m, 25)[0] for m in (0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)]
    assert all(a >= b for a, b in zip(rates, rates[1:], strict=False))
    res = plan(ctx, {}, {}, 25, runs["prices"], rate=runs["rate"], money="auction")
    assert res["money"] == "auction" and res["purse_rate"] == res["lam"]
    for t in res["targets"]:
        assert 0 <= t["max_bid"] <= max(0.0, ctx["purse_left"]) + 1e-9


def test_opportunity_rule_bids_what_paying_gives_up():
    """The "opportunity" money rule (candidate of 2026-10-29, after the review found every max bid
    was the purse left and buys far above the sheet's own max bids): a lot's max bid is the most that
    keeps what paying gives up (the later lots its money and place would have bought) within his gain,
    so it is finite and never above the money left, and the plan never lands a likely buy above his max
    bid on average. Every run reaches the squad minimum."""
    from cricdex.web_parity.bidplan import DEFAULT_NEEDS, _cands, _Gains, _median, _OppValue

    data = {k: v for k, v in LEAGUE.items() if k != "_pool"}
    for team in ("AAA", "CCC"):
        ctx = build_context(data, build_pool(LEAGUE["_pool"]), team, {}, None, 6)
        runs = rival_runs(ctx, 25)
        cands = _cands(ctx)
        gains = _Gains(ctx["kept"], cands, dict(DEFAULT_NEEDS))
        ov = _OppValue(cands, gains, [], [_median(ps) for ps in runs["prices"]])
        for i in range(len(cands)):
            g = gains.gain(gains.state([]), i)
            bids = [
                ov.max_bid(i, g, m, 5, 2, bool(cands[i]["os"])) for m in (0.0, 1.0, 3.0, 9.0, 27.0)
            ]
            assert all(
                0.0 <= b <= m + 1e-9 for b, m in zip(bids, (0.0, 1.0, 3.0, 9.0, 27.0), strict=True)
            )
            # (more money can lower a max bid: the later lots his place would hold get better)
            # places for every later lot: he is worth whatever money the later lots don't need
            if g > 0:
                later = sum(e for _r, j, e, _g, _os in ov.items if j > i)
                mb = ov.max_bid(i, g, 1e6, 10**6, 99, bool(cands[i]["os"]))
                assert 1e6 - later - 1e-6 <= mb <= 1e6
            assert ov.max_bid(i, g, 27.0, 0, 2, False) == 0.0  # no place: nothing to buy
        res = plan(ctx, {}, {}, 25, runs["prices"], rate=runs["rate"], money="opportunity")
        assert res["money"] == "opportunity" and res["purse_rate"] == res["lam"]
        assert res["mean_squad"] >= ctx["rules"]["squad_min"] - 1e-9
        for t in res["targets"]:
            assert 0 <= t["max_bid"] <= max(0.0, ctx["purse_left"]) + 1e-9
            if t["likely"] and not t["override"]:
                assert t["avg_paid"] <= t["max_bid"] + 1e-9, (
                    team,
                    t["name"],
                    t["avg_paid"],
                    t["max_bid"],
                )
