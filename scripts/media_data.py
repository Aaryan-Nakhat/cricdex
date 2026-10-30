"""Compute every number the README visuals show -> docs/media/src/data.js (`window.MEDIA = {...}`).

    uv run python scripts/media_data.py                 # then render_images.py and render_video.py

The visuals' HTML sources (docs/media/src/img-*.html, hero.html) read their numbers from data.js, so a refresh
is: re-export the site data, run this, re-render. Everything comes from the same exported JSON and the same
Python twins of the site's logic the CLI uses (`cricdex.web_parity`, parity-locked to the TypeScript):

- auction: the Auction room's default mega run (real 2025 retentions, 120 cr, 300 seeded trials)
- keep: Keep or release for one franchise (`--keep-team`, default RCB) on the exported keep.json
- scout: Scout look-alikes for one IPL player (`--scout`, default Jasprit Bumrah), every country
- ratings / head to head: ratings.json; NGI leaders: leaderboards/ngi.json
- backtests: data/metrics/{ratings,newcomer,keep}_backtest_ipl.json (gitignored: written by the backtest
  scripts; a missing file keeps that block's last values in data.js)
- bidplan sheet: Bid plan's live 2027 sheet for one franchise (`--bidplan-team`, default RCB; 200 rival runs)
- Bid plan's replay and calibration: METHODOLOGY section 12, copied into BIDPLAN_DOC below
  (`scripts/bidplan_backtest.py` takes ~45 min and keeps no report on disk; update BIDPLAN_DOC after a re-run)

Run from the repo root.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

SITE = Path("site/public/data")
METRICS = Path("data/metrics")
OUT = Path("docs/media/src/data.js")

COUNTRY = {
    "IND": "India", "AUS": "Australia", "ENG": "England", "NZL": "New Zealand", "ZAF": "South Africa",
    "LKA": "Sri Lanka", "BGD": "Bangladesh", "AFG": "Afghanistan", "WIN": "West Indies", "PAK": "Pakistan",
    "IRE": "Ireland", "NLD": "Netherlands", "ZWE": "Zimbabwe", "SCO": "Scotland", "USA": "USA", "NAM": "Namibia",
    "NEP": "Nepal", "UAE": "UAE",
}  # fmt: skip

# Bid plan (draft) replay, METHODOLOGY section 12, the opportunity money rule (2026-10-30; scripts/bidplan_backtest.py
# --money opportunity, 200 runs): the plan's squad vs the real one next season (2024 at full purse, the year the
# rule was checked on; 2025-26 at the real team's spend, seen before); and "P(<= max bid)" said / came true per
# band on the 2025 and 2026 auctions.
BIDPLAN_DOC = {
    "source": "METHODOLOGY section 12 (scripts/bidplan_backtest.py, opportunity rule, 2026-10-30)",
    "replay": {
        "check": {"label": "2024 mini (full purse)", "ahead": 7, "teams": 10, "mean": 6.1},
        "mega": {"label": "2025 mega (real spend)", "ahead": 2, "teams": 10, "mean": -6.6},
        "mini": {"label": "2026 mini (real spend)", "ahead": 1, "teams": 10, "mean": -3.0},
    },
    "calibration": [
        {"band": "0.0–0.2", "y2025": [0.02, 0.02, 296], "y2026": [0.06, 0.20, 40]},
        {"band": "0.2–0.4", "y2025": [0.27, 0.09, 22], "y2026": [0.28, 0.32, 28]},
        {"band": "0.4–0.6", "y2025": [0.49, 0.54, 13], "y2026": [0.47, 0.60, 10]},
        {"band": "0.6–0.8", "y2025": [0.71, 0.53, 38], "y2026": [0.69, 0.59, 17]},
        {"band": "0.8–1.0", "y2025": [0.88, 0.77, 52], "y2026": [0.85, 1.00, 9]},
    ],
}


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def r1(x: float) -> float:
    return round(float(x), 1)


def r2(x: float) -> float:
    return round(float(x), 2)


def auction_block() -> dict:
    from cricdex.common.display import display_name
    from cricdex.web_parity import (
        IPL_TEAMS_DEFAULT,
        build_pool,
        default_retentions,
        load_auction_pool,
        load_retentions,
        retention_inputs,
        simulate_auction,
    )

    raw = load_auction_pool("ipl")
    shown = {r["cricsheet_id"]: display_name(r) for r in raw}
    pool = build_pool(raw)
    ri = retention_inputs(load_retentions("ipl"))
    purse, trials = 120.0, 300
    opts = {
        "purse": purse,
        "squad_size": 25,
        "overseas_cap": 8,
        "trials": trials,
        "mode": "mega",
        "retentions": default_retentions(pool, IPL_TEAMS_DEFAULT, "mega", ri["mega_ids"]),
        "real_prices": ri["real_prices"],
        "retention_slabs": ri["retention_slabs"],
        "slab_holders": ri["slab_holders"],
        "fixed_retained": ri["fixed_retained"],
    }
    res = simulate_auction(pool, IPL_TEAMS_DEFAULT, opts)
    teams = []
    for b, t in zip(res["bases"], res["teams"], strict=True):
        teams.append(
            {
                "team": t["team"],
                "kept": t["retained"],
                "retain": r1(b["retain_spend"]),
                "bought": r1(t["avg_spend"]),
                "used": r1(b["retain_spend"] + t["avg_spend"]),
                "n_bought": round(t["avg_bought"]),
            }
        )
    sold = sorted(
        (o for o in res["outcomes"] if o["status"] == "sold"), key=lambda o: -o["avgPrice"]
    )
    raw_by = {r["cricsheet_id"]: r for r in raw}
    top = [
        {
            "name": shown.get(o["cricsheet_id"]) or o["name"],
            "role": o["role"].replace("_", "-"),
            "country": COUNTRY.get(raw_by.get(o["cricsheet_id"], {}).get("country") or "", ""),
            "price": r1(o["avgPrice"]),
            "sold": round(o["soldPct"]),
            "winners": [{"team": w["team"], "pct": round(w["pct"])} for w in o["winners"]],
        }
        for o in sold[:8]
    ]
    # the team that kept fewest and what it spent: it has the most purse to bid with
    fewest = min(teams, key=lambda t: (t["kept"], -t["bought"]))
    top_wins: dict[str, int] = {}
    for o in sold[:20]:
        if o["winners"]:
            top_wins[o["winners"][0]["team"]] = top_wins.get(o["winners"][0]["team"], 0) + 1
    return {
        "purse": purse,
        "trials": trials,
        "auctioned": res["auctioned"],
        "pool_size": res["pool_size"],
        "teams": teams,
        "top": top,
        "fewest": {
            "team": fewest["team"],
            "kept": fewest["kept"],
            "bought": fewest["bought"],
            "most_likely_of_top20": top_wins.get(fewest["team"], 0),
            "max_bought": max(t["bought"] for t in teams) == fewest["bought"],
        },
    }


def scout_block(pick: str) -> dict:
    from cricdex import leagues
    from cricdex.common.display import display_name
    from cricdex.web_parity import load_retentions, load_scout_index, scout_price, similar_to

    idx = load_scout_index("ipl")
    sel = next(p for p in idx["ipl"] if display_name(p) == pick)
    role = sel["role"]
    sel_price = scout_price(sel)
    same_role = sorted(
        (p for p in idx["ipl"] if p["role"] == role and p.get("z") is not None),
        key=lambda p: -p["z"],
    )
    rank = next(i for i, p in enumerate(same_role) if p["cricsheet_id"] == sel["cricsheet_id"]) + 1
    real = None
    for team, rows in (load_retentions("ipl").get("mega") or {}).items():
        for r in rows:
            if r.get("cricsheet_id") == sel["cricsheet_id"]:
                real = {"team": team, "price": r1(r["price"])}
    pos = "" if role == "bowler" else "same"
    hits = []
    for lg in leagues.scout_pools():
        if lg.tier not in idx:
            continue
        found = similar_to(sel, idx[lg.tier], role, pos, 3, country="all")
        if not found:
            continue
        h = found[0]
        stale = h.get("data_as_of") if h.get("stale") else None
        hits.append(
            {
                "tier": lg.tier,
                "league": lg.short,
                "name": display_name(h),
                "type": h.get("bowling_category") or role,
                "country": COUNTRY.get(h.get("country") or "", h.get("country") or ""),
                "domestic": lg.tier == "smat",
                "sim": round(h["sim"] * 100),
                "price": r1(scout_price(h)),
                "saving": r1(max(0.0, sel_price - scout_price(h))),
                "stale": stale,
                "ipl_peer": lg.tier == "ipl",
            }
        )
    peer = [h for h in hits if h["ipl_peer"]]
    rest, seen = [], {h["name"] for h in peer}
    for h in sorted((h for h in hits if not h["ipl_peer"]), key=lambda h: -h["sim"]):
        if h["name"] not in seen:
            seen.add(h["name"])
            rest.append(h)
    reg = _read(SITE / "leagues.json")
    side = "bowler" if role == "bowler" else "batter"
    trans = []
    for lg in reg["leagues"]:
        t = lg.get("translation")
        if t and lg.get("scout_pool"):
            trans.append(
                {
                    "league": lg["short"],
                    "at10": r1(t[side]["a"] + t[side]["b"] * 10),
                    "pairs": t[side]["pairs"],
                }
            )
    trans.sort(key=lambda x: -x["at10"])
    return {
        "pick": {
            "name": display_name(sel),
            "role": role,
            "type": sel.get("bowling_category"),
            "country": COUNTRY.get(sel.get("country") or "", sel.get("country")),
            "price": r1(sel_price),
            "value": r1(sel["value"]),
            "rank": rank,
            "rank_of": len(same_role),
            "real": real,
        },
        "rows": peer[:1] + rest[:6],
        "side": side,
        "translations": trans,
        "n_pools": len(leagues.scout_pools()),
    }


def ratings_block() -> dict:
    from cricdex.scout.ratings.head_to_head import compare_rows

    rows = _read(SITE / "ipl/ratings.json")
    players = {p["cricsheet_id"]: p for p in _read(SITE / "ipl/players.json")}
    by: dict[str, dict] = {}
    for r in rows:
        by.setdefault(r["cricsheet_id"], {})[r["role"]] = r

    def cid(name: str) -> str:
        return next(r["cricsheet_id"] for r in rows if r.get("display_name") == name)

    def bat(name: str) -> dict:
        r = by[cid(name)]["batter"]
        return {"name": name, "mean": r1(r["value"]), "sd": r1(r["value_sd"]), "balls": r["balls"]}

    def h2h(a: str, b: str) -> dict:
        c = compare_rows(a, b, by[cid(a)], by[cid(b)], "batter")
        return {"a": a, "b": b, "p": c["p_a_better"], "verdict": c["verdict"]}

    def board(role: str) -> list[dict]:
        out = []
        for r in rows:
            p = players.get(r["cricsheet_id"]) or {}
            # on a current IPL squad, not retired, 600+ balls in the role
            if (
                r["role"] != role
                or not p.get("team")
                or p.get("retired")
                or (r["balls"] or 0) < 600
            ):
                continue
            out.append(
                {
                    "name": r.get("display_name") or r["unique_name"],
                    "team": p["team"],
                    "mean": r1(r["value"]),
                    "sd": r1(r["value_sd"]),
                }
            )
        return sorted(out, key=lambda x: -x["mean"])[:8]

    return {
        "a": bat("Virat Kohli"),
        "b": bat("Vaibhav Suryavanshi"),
        "h2h": [
            h2h("Vaibhav Suryavanshi", "Virat Kohli"),
            h2h("Sai Sudharsan", "Virat Kohli"),
            h2h("Shubman Gill", "Virat Kohli"),
        ],
        "batters": board("batter"),
        "bowlers": board("bowler"),
    }


def ngi_block() -> dict:
    rows = _read(SITE / "ipl/leaderboards/ngi.json")
    top = sorted(rows, key=lambda r: -r["ngi_per_match"])[:3]
    return {
        "top": [
            {
                "name": r["display_name"],
                "pct": r1(100 * r["ngi_per_match"]),
                "matches": r["matches"],
            }
            for r in top
        ]
    }


def backtest_block() -> dict | None:
    fr, fn = METRICS / "ratings_backtest_ipl.json", METRICS / "newcomer_backtest_ipl.json"
    if not (fr.exists() and fn.exists()):
        return None
    s = _read(fr)["variants"]["v2"]["summary"]
    nb = _read(fn)

    def nc(role: str) -> dict:
        a = nb[role]["all"]
        return {
            "n": nb[role]["n"],
            "model": r2(a["model"]),
            "base": r2(a["raw"]),
            "ci": [r2(a["gap_ci95"][0]), r2(a["gap_ci95"][1])],
            "p_ahead": round(100 * a["p_model_better"]),
            "p_holm": a["p_holm"],
        }

    return {
        "est": {
            "bat": {
                "model": r2(s["batter"]["all"]["model"]),
                "base": r2(s["batter"]["all"]["career"]),
            },
            "bowl": {
                "model": r2(s["bowler"]["all"]["model"]),
                "base": r2(s["bowler"]["all"]["career"]),
            },
        },
        "new": {"bat": nc("batter"), "bowl": nc("bowler")},
        "seasons": nb["seasons"],
        "n_leagues": len(nb["leagues"]),
        "resamples": 2000,
    }


def keep_block(team: str) -> dict:
    from cricdex.web_parity import build_pool, load_auction_pool
    from cricdex.web_parity.keep import BORDER_BAND, KEEP_CALL, evaluate, market_for, squad_of
    from cricdex.web_parity.loader import load_keep

    data = load_keep("ipl")
    pool = build_pool(load_auction_pool("ipl"))
    comp = data["competition"]
    rules = dict(comp["rules"])
    market = market_for(
        team, data["players"], pool, data.get("pool_tags") or {}, data.get("form"), rules
    )
    res = evaluate(squad_of(data, team), market, rules, {}, {}, data.get("form"))
    ps = sorted(res["players"], key=lambda p: -(p.get("p_keep") or 0))
    out = {
        "team": team,
        "competition": comp["name"],
        "deadline": comp["retention_deadline"],
        "purse": rules["purse"],
        "purse_assumed": "purse" in (comp.get("assumed") or []),
        "bands": {"keep": KEEP_CALL + BORDER_BAND, "release": KEEP_CALL - BORDER_BAND},
        "players": [
            {
                "name": p["name"],
                "role": p["role"].replace("_", "-"),
                "overseas": bool(p.get("overseas")),
                "captain": bool(p.get("captain")),
                "cost": r1(p["cost"]),
                "price": None if p["price"] is None else r1(p["price"]),
                "p_keep": None if p.get("p_keep") is None else round(100 * p["p_keep"]),
                "rec": p["rec"],
                "outlook": p.get("forecast_note"),
            }
            for p in ps
        ],
        "kept": res["kept"],
        "released": res["released"],
        "purse_left": r1(res["purse_left"]),
        "slots_left": res["slots_left"],
        "overseas_slots_left": res["overseas_slots_left"],
        "gaps": [
            {"label": g["label"], "gap": g["gap"], "target": g["target"], "kept": g["kept"]}
            for g in res["gaps"]
        ],
    }
    fk = METRICS / "keep_backtest_ipl.json"
    if fk.exists():
        # each validation deadline against its own majority call (2025 mega, 2026 mini; METHODOLOGY §10)
        v = _read(fk)["validation"]
        model = next(x for k, x in v.items() if k.startswith("L"))
        out["test"] = {
            y: {
                "accuracy": round(100 * model[y]["accuracy"]),
                "majority": round(100 * model[y]["majority_accuracy"]),
                "majority_call": model[y]["majority_call"],
                "n": model[y]["n"],
            }
            for y in ("2025", "2026")
        }
    return out


def bidplan_sheet(team: str) -> dict:
    """Bid plan's live sheet for one team (the CLI's `cricdex bidplan --team <team>` defaults: Keep or
    release's plan, 8 places opened, 200 rival runs): its top five targets and the fallback chain for
    the role it is shortest of (else the first chain)."""
    from cricdex.web_parity import build_pool, load_auction_pool
    from cricdex.web_parity.bidplan import (
        OPEN_SLOTS,
        SLOT_LABEL,
        TRIALS,
        build_context,
        plan,
        rival_prices,
    )
    from cricdex.web_parity.loader import load_auction_register, load_keep

    data = load_keep("ipl")
    raw = load_auction_pool("ipl")
    display = {r["cricsheet_id"]: r["display_name"] for r in raw if r.get("display_name")}
    ctx = build_context(data, build_pool(raw), team, {}, None, OPEN_SLOTS, None,
                        load_auction_register("ipl"), display)  # fmt: skip
    res = plan(ctx, None, None, TRIALS, rival_prices(ctx, TRIALS))
    need_slot = {"keeper": "keeper", "opener": "opener", "death": "death", "spinner": "spinner",
                 "pace": "pace"}  # fmt: skip
    want = [need_slot[m["need"]] for m in res["missing"]]
    chain = next((c for s in want for c in res["chains"] if c["slot"] == s), None) or (
        res["chains"][0] if res["chains"] else None
    )
    return {
        "team": team,
        "trials": res["trials"],
        "purse_left": r1(ctx["purse_left"]),
        "kept": len(ctx["kept"]),
        "lam": r2(res["lam"]),
        "missing": [m["label"] for m in res["missing"]],
        "targets": [
            {
                "name": x["name"],
                "slot": SLOT_LABEL[x["slot"]],
                "from": x.get("from_team"),
                "rivals": r1(x["expected_price"]),
                "max": r1(x["max_bid"]),
                "p_le": round(100 * x["p_le_max"]),
                "gain": r2(x["gain"]),
            }
            for x in res["targets"][:5]
        ],
        "chain": None
        if chain is None
        else {
            "label": chain["label"],
            "steps": [{"name": s["name"], "max": r1(s["max_bid"])} for s in chain["steps"][:3]],
        },  # fmt: skip
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-team", default="RCB")
    ap.add_argument("--bidplan-team", default="RCB")
    ap.add_argument("--scout", default="Jasprit Bumrah")
    a = ap.parse_args()
    prev: dict = {}
    if OUT.exists():
        m = re.search(r"window\.MEDIA = (\{.*\});", OUT.read_text(encoding="utf-8"), re.S)
        prev = json.loads(m.group(1)) if m else {}
    meta = _read(SITE / "ipl/meta.json")
    media = {
        "generated": date.today().isoformat(),
        "data_as_of": meta["data_as_of"],
        "auction": auction_block(),
        "keep": keep_block(a.keep_team),
        "bidplan": {**BIDPLAN_DOC, "sheet": bidplan_sheet(a.bidplan_team)},
        "scout": scout_block(a.scout),
        "ratings": ratings_block(),
        "ngi": ngi_block(),
        "backtest": backtest_block() or prev.get("backtest"),
    }
    if media["backtest"] is None:
        raise SystemExit(
            "no backtest results: run scripts/backtest_ratings.py and backtest_newcomers.py"
        )
    if "test" not in media["keep"] and (prev.get("keep") or {}).get("test"):
        media["keep"]["test"] = prev["keep"]["test"]
    body = json.dumps(media, ensure_ascii=False, indent=1, allow_nan=False)
    OUT.write_text(
        "// Written by scripts/media_data.py: the numbers the README visuals show. Do not edit by hand.\n"
        f"window.MEDIA = {body};\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main()
