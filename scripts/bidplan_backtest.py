"""Does Bid plan help? Replay the 2025 mega auction and the 2026 mini auction (docs/METHODOLOGY.md §12).

For each auction and each franchise, using only what was known before that auction:

* **Values** are the IPL ratings fitted on the matches before the auction date (the walk-forward
  fits `scripts/ipl_price_model.py fits` caches) blended with the other leagues' fits whose
  cut-off is on or before it, then discounted for IPL relevance as the auction pool does.
* **Market prices** come from a price model fitted only on the auctions before (2018 to the year
  before; the shipped recipe: Huber + quantile map + group shifts), on the features as of the
  auction (`ipl_price_model.build_rows`). The P(bought) part isn't refitted: the plan doesn't use it.
* **The pool** is every player sold at that auction with a Cricsheet id (the pages list no
  unsold players, so this is the one set known to have been available), at his real base price.
* **Squads and purses** are the real retentions (data/curated/ipl_auction_history.json): the purse
  less what each retained player cost. Rivals bid with the Auction room's personalities.

Then Bid plan builds the team's plan (200 rival runs) twice: with its real purse left, and with a
purse equal to what the team actually spent ("same spend"). Scored against what really happened:

(a) **strength**: the plan's bidding rule played against the real prices (a player is ours if our
    bid reaches what he actually sold for, purse and room permitting), against the squad the team
    actually bought: XI value and total strength (the plan's own measure; same values for both);
(b) **targets**: how many of the plan's top 10 targets the team actually bought, and at what price
    against our max bid; and over every target, whether he sold at or under our max bid against the
    plan's P(we land him at ≤ max bid) (a calibration check of the rival model).

Resumable: each team's result is cached under --work; rerun to continue. About 10 minutes.

    uv run python scripts/bidplan_backtest.py --work <dir> [--trials 200] [--out report.json]
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ipl_price_model as ipm  # noqa: E402

from cricdex.scout.identity import master  # noqa: E402
from cricdex.web_parity import bidplan as bp  # noqa: E402
from cricdex.web_parity.auction import IPL_TEAMS_DEFAULT  # noqa: E402
from cricdex.web_parity.pricing import load_price_model, market_price  # noqa: E402

app = typer.Typer(add_completion=False)
SEASONS = (2025, 2026)
RULES = {"squad_min": 18, "squad_max": 25, "overseas_max": 8}
PEN_SCALE = 36.0  # export_site.PEN_SCALE_VALUE: value removed at IPL relevance 0
TOP = 10


def _fit_price_model(price_rows: list[dict], ret_rows: list[dict], season: int) -> dict:
    """The shipped price recipe (its features, regression and retention treatment), trained on
    auctions 2018 … season − 1 only."""
    spec = ipm.shipped_spec()
    shipped = load_price_model() or {}
    return {
        "floor_cr": 0.3,
        "competition": {"cycle": "mini", "purse": 125.0},
        "price": ipm.fit_price_part(price_rows, ret_rows, spec, 2018, season),
        "bought": shipped.get("bought"),
        "trained_on": [2018, season - 1],
    }


def _slab_extra(season: int, team: str, hist: dict) -> float:
    """What the purse counted beyond the retained salaries under the 2025-27 retention slabs: the
    team's 2025 mega-auction retentions (still with it, for 2026) cost max(the first n capped slabs +
    4 cr per uncapped one, their salaries) (web_parity/keep.slab_charge; reproduces every team's
    published 2025 and 2026 purse). 0 outside that cycle."""
    if season not in (2025, 2026):
        return 0.0
    from cricdex import competitions
    from cricdex.web_parity.keep import slab_charge

    comp = competitions.get("ipl_2027")
    sq = competitions.load_squads(comp)
    block = ((sq.get("mega_retentions_2025") or {}).get("teams") or {}).get(team) or {}
    kept = {(r["name"]): float(r["salary_cr"]) for r in hist["retentions"]
            if r["season"] == season and r["team"] == team and r.get("salary_cr")}  # fmt: skip
    holders = [{"salary": kept[n], "slab_holder": k} for k in ("capped", "uncapped")
               for n in block.get(k, []) if n in kept]  # fmt: skip
    if not holders:
        return 0.0
    return slab_charge(holders, comp.rules()) - sum(h["salary"] for h in holders)


def _tags_fn():
    """Keep or release's role tags (keeper, opener, death bowler, spinner, overseas) from the
    player master and every league's ball-by-ball (export_site's own helpers)."""
    import export_site as ex

    tax = ex._load_taxonomy()
    with duckdb.connect(str(ex.DUCKDB_PATH), read_only=True) as con:
        death = ex._keep_death_bowlers(con)

    def tags(cid: str | None, role: str, overseas: bool) -> str:
        rec = tax.get(cid or "", {}) if cid else {}
        return ex._keep_tags(rec if isinstance(rec, dict) else {}, role, overseas, death, cid)

    return tags


def _age(dob: str | None, date: str) -> float | None:
    if not dob:
        return None
    try:
        return ipm._years(date, str(dob)[:10])
    except ValueError:
        return None


def _pool_value(
    v: float | None, cid: str, country: str | None, date: str, pm, apps
) -> float | None:
    """The auction pool's value: blended value less the IPL-relevance discount."""
    if v is None:
        return None
    rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
    ipl = [d for d in apps.get(cid, []) if d < date]
    rel = ipm._relevance(ipl[-1] if ipl else None, _age(rec.get("dob"), date), country, date)
    return v - (1 - rel) * PEN_SCALE


NEXT_MIN_BALLS = 60  # a role needs this many balls in the next season to count, else replacement


def _next_season_values(season: int) -> dict[str, float]:
    """What each player actually did in the IPL season the auction was for (runs per 100 balls
    above that season's average ball, `runs_value.observed_value`), in his better role with
    NEXT_MIN_BALLS+ balls in it. Missing = he barely played: replacement level."""
    from cricdex.scout.ratings import bayesian, runs_value

    tab = runs_value.league_tables(
        bayesian.DEFAULT_DB_PATH, "ipl", since=f"{season}-01-01", before=f"{season + 1}-01-01"
    )
    out: dict[str, float] = {}
    for role in ("batter", "bowler"):
        ids = [pid for pid, t in tab.totals.get(role, {}).items()
               if t[:, 3].sum() >= NEXT_MIN_BALLS]  # fmt: skip
        if not ids:
            continue
        for pid, v in zip(ids, runs_value.observed_value(tab, role, ids), strict=True):
            if not math.isnan(v):
                out[pid] = max(out.get(pid, -math.inf), float(v))
    return out


def _next_strength(pieces: list[dict], nxt: dict[str, float], needs: dict) -> dict:
    """The plan's strength measure on next-season performance instead of our pre-auction values."""
    re = [bp.piece(p["id"], p["name"], nxt.get(p["id"]), p["role"], p["os"], p["tags"])
          for p in pieces]  # fmt: skip
    return bp.strength(re, needs)


def _season_inputs(season: int, rows, hist, pm, apps, tags) -> dict:
    a = hist["auctions"][str(season)]
    date, purse, cycle = a["date"], float(a["purse_cr"]), a["kind"]
    price_rows, ret_rows = rows[0], rows[1]
    risk_rows = rows[2] if len(rows) > 2 else []
    model = _fit_price_model(price_rows, ret_rows, season)
    comp = {"cycle": cycle, "purse": purse}
    vals = ipm.asof_values(season, date)
    lots = [r for r in hist["lots"] if r["season"] == season and r.get("sold")]
    feats = {r["cricsheet_id"]: r for r in price_rows if r["season"] == season}
    avail = []
    for lot in lots:
        cid = lot.get("cricsheet_id")
        if not cid or cid in {x["cricsheet_id"] for x in avail}:
            continue
        f = feats.get(cid)
        if f is None:
            continue
        mk = market_price(f, comp, model)
        role = f["role"]
        ov = bool(f["is_overseas"])
        avail.append(
            {
                "cricsheet_id": cid,
                "name": lot["name"],
                "role": role,
                "is_overseas": ov,
                "value": _pool_value(f.get("price_value"), cid, f.get("country"), date, pm, apps),
                "projected_value": mk["price"],
                "p_bought": mk["p_bought"],
                "base_price": float(lot.get("base_price_cr") or 0.3),
                "tags": tags(cid, role, ov),
                "from_team": None,
                "anchor_price": (f["prev_share"] * purse) if f.get("prev_share") else None,
                "_sold_to": lot["team"],
                "_price": float(lot["price_cr"]),
            }
        )
    # the unsold: recent IPL players neither retained nor bought (the P(bought) risk set; the pages list
    # no unsold lots, so this mixes unsold, unregistered and retired players). They are alternatives the
    # simulated teams can buy, never something the real replay counts as bought (`_price` None).
    from cricdex.web_parity.pricing import price_tier

    seen = {x["cricsheet_id"] for x in avail}
    for f in risk_rows:
        cid = f["cricsheet_id"]
        if f["season"] != season or f["bought"] or cid in seen:
            continue
        seen.add(cid)
        mk = market_price(f, comp, model)
        role, ov = f["role"], bool(f["is_overseas"])
        rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
        avail.append(
            {
                "cricsheet_id": cid,
                "name": rec.get("display_name") or cid,
                "role": role,
                "is_overseas": ov,
                "value": _pool_value(f.get("price_value"), cid, f.get("country"), date, pm, apps),
                "projected_value": mk["price"],
                "p_bought": mk["p_bought"],
                "base_price": price_tier(mk["price"]),
                "tags": tags(cid, role, ov),
                "from_team": None,
                "anchor_price": (f["prev_share"] * purse) if f.get("prev_share") else None,
                "_sold_to": None,
                "_price": None,
            }
        )
    avail.sort(key=bp._lot_order)
    teams: dict[str, dict] = {}
    for r in hist["retentions"]:
        if r["season"] != season or r["kind"] != "retained":
            continue
        t = teams.setdefault(r["team"], {"kept": [], "cost": 0.0})
        cid = r.get("cricsheet_id")
        rec = pm.get(cid) if cid and isinstance(pm.get(cid), dict) else {}
        role = ipm.ROLE_MAP.get(rec.get("primary_role") or "", "batter")
        country = r.get("country") or rec.get("country")
        ov = bool(country) and country != "IND"
        v = vals.get(cid) if cid else None
        value = _pool_value(v["value"] if v else None, cid or "", country, date, pm, apps)
        t["kept"].append(bp.piece(cid or f"name:{r['name']}", r["name"], value, role, ov,
                                  tags(cid, role, ov)))  # fmt: skip
        t["cost"] += float(r.get("purse_deduction_cr") or r.get("salary_cr") or 0.0)
    for lot in lots:
        teams.setdefault(lot["team"], {"kept": [], "cost": 0.0})
    for t, v in teams.items():
        v["cost"] += _slab_extra(season, t, hist)
    return {"season": season, "date": date, "purse": purse, "cycle": cycle, "model": model,
            "avail": avail, "teams": teams, "lots": lots,
            "next": _next_season_values(season)}  # fmt: skip


def _team_result(si: dict, team: str, trials: int, tags) -> dict:
    purse = si["purse"]
    pers = {c["team"]: c["personality"] for c in IPL_TEAMS_DEFAULT}
    rivals = [
        {"team": t, "personality": pers.get(t, "Balanced"), "kept": v["kept"],
         "purse_left": purse - v["cost"]}
        for t, v in sorted(si["teams"].items()) if t != team
    ]  # fmt: skip
    me = si["teams"][team]
    avail = [{k: v for k, v in r.items() if not k.startswith("_")} for r in si["avail"]]
    ctx = {
        "team": team,
        "rules": {**RULES, "purse": purse},
        "cycle": si["cycle"],
        "open_slots": 0,
        "squad": [],
        "kept": me["kept"],
        "purse_left": purse - me["cost"],
        "salary_kept": me["cost"],
        "warnings": [],
        "rivals": rivals,
        "available": avail,
        "register": True,
    }
    prices = bp.rival_prices(ctx, trials)
    real = [math.inf if r["_price"] is None else r["_price"] for r in si["avail"]]
    actual_lots = [lot for lot in si["lots"] if lot["team"] == team]
    actual_spend = sum(float(lot["price_cr"]) for lot in actual_lots)
    by_id = {r["cricsheet_id"]: r for r in si["avail"]}
    actual_pieces = []
    for lot in actual_lots:
        cid = lot.get("cricsheet_id")
        r = by_id.get(cid or "")
        if r:
            actual_pieces.append(bp.piece(cid, r["name"], r["value"], r["role"], r["is_overseas"],
                                          r["tags"]))  # fmt: skip
        else:  # an uncapped player with no ball-by-ball: replacement level, role unknown
            ov = (lot.get("country") or "IND") != "IND"
            actual_pieces.append(bp.piece(f"name:{lot['name']}", lot["name"], None, "batter", ov,
                                          "x" if ov else ""))  # fmt: skip
    out: dict = {"team": team, "purse_left": ctx["purse_left"], "kept": len(me["kept"]),
                 "actual_spend": actual_spend, "actual_bought": len(actual_lots)}  # fmt: skip
    # the price to beat (this team's nine rivals) against what each of its real buys cost it
    out["bought_ptb"] = [
        {"name": r["name"], "real": r["_price"], "ptb_median": float(np.median(prices[i])),
         "ptb_p20": float(np.quantile(prices[i], 0.2)), "ptb_p80": float(np.quantile(prices[i], 0.8)),
         "pit": float(np.mean(np.array(prices[i]) < r["_price"]) + 0.5 * np.mean(np.array(prices[i]) == r["_price"])),
         "market": r["projected_value"]}
        for i, r in enumerate(si["avail"]) if r["_sold_to"] == team and r["_price"]
    ]  # fmt: skip
    for label, left in (
        ("full", ctx["purse_left"]),
        ("same", min(ctx["purse_left"], actual_spend)),
    ):
        c = {**ctx, "purse_left": left}
        res = bp.plan(c, prices=prices)
        fol = bp.follow_plan(c, res, real)
        act = bp.strength(me["kept"] + actual_pieces, res["needs"])
        got = set(fol["bought"])
        ours_pieces = me["kept"] + [p for p in bp._cands(c) if p["id"] in got]
        nx_ours = _next_strength(ours_pieces, si["next"], res["needs"])
        nx_act = _next_strength(me["kept"] + actual_pieces, si["next"], res["needs"])
        out[label] = {
            "lam": res["lam"],
            "before": res["before"]["total"],
            "before_xi": res["before"]["xi"],
            "plan_expected": res["mean_strength"],
            "plan_spend_expected": res["mean_spend"],
            "ours": fol["strength"]["total"],
            "ours_xi": fol["strength"]["xi"],
            "ours_spend": fol["spend"],
            "ours_bought": [by_id[i]["name"] for i in fol["bought"]],
            "actual": act["total"],
            "actual_xi": act["xi"],
            "next_ours": nx_ours["total"],
            "next_ours_xi": nx_ours["xi"],
            "next_actual": nx_act["total"],
            "next_actual_xi": nx_act["xi"],
            "targets": [
                {
                    "name": x["name"],
                    "priority": x["priority"],
                    "max_bid": x["max_bid"],
                    "expected_price": x["expected_price"],
                    "p_le_max": x["p_le_max"],
                    "sold_to": by_id[x["id"]]["_sold_to"],
                    "price": by_id[x["id"]]["_price"],
                }
                for x in res["targets"]
            ],
        }
    return out


NAMED = [
    "Rishabh Pant",
    "Shreyas Iyer",
    "Venkatesh Iyer",
    "Arshdeep Singh",
    "Yuzvendra Chahal",
    "Jos Buttler",
    "Cameron Green",
    "Matheesha Pathirana",
    "Bhuvneshwar Kumar",
    "KL Rahul",
    "Mitchell Starc",
    "Jitesh Sharma",
    "Ishan Kishan",
    "Liam Livingstone",
    "Prasidh Krishna",
    "Mohammed Shami",
    "Ravi Bishnoi",
    "Kartik Sharma",
    "Prashant Veer",
    "Liam Livingstone",
]


def _rank_corr(a: list[float], b: list[float]) -> float:
    ra = np.argsort(np.argsort(a, kind="stable"), kind="stable")
    rb = np.argsort(np.argsort(b, kind="stable"), kind="stable")
    return float(np.corrcoef(ra, rb)[0, 1])


def _ptb_summary(teams: dict) -> dict:
    rows = [x for t in teams.values() for x in t.get("bought_ptb", [])]
    if not rows:
        return {}
    real = np.array([x["real"] for x in rows])
    ptb = np.array([x["ptb_median"] for x in rows])
    mkt = np.array([x["market"] for x in rows])
    top = np.argsort(-real)[:10]
    pit = np.array([x["pit"] for x in rows])
    named = []
    for nm in dict.fromkeys(NAMED):
        hit = [x for x in rows if x["name"].lower() == nm.lower()]
        if hit:
            named.append(hit[0])
    return {
        "n": len(rows),
        "median_ratio": float(np.median(real / ptb)),
        "mae_ln": float(np.mean(np.abs(np.log(real) - np.log(ptb)))),
        "rank_corr": _rank_corr(list(real), list(ptb)),
        "top10_ratio": float(np.exp(np.mean(np.log(ptb[top] / real[top])))),
        "market_median_ratio": float(np.median(real / mkt)),
        "market_mae_ln": float(np.mean(np.abs(np.log(real) - np.log(mkt)))),
        "inside_20_80": float(np.mean((pit >= 0.2) & (pit <= 0.8))),
        "named": named,
    }


def _summarise(results: dict) -> dict:
    summ: dict = {}
    for season, teams in results.items():
        rows = []
        cal = []
        ratio = []
        for t in sorted(teams):
            r = teams[t]
            same, full = r["same"], r["full"]
            top = sorted(full["targets"], key=lambda x: x["priority"])[:TOP]
            got = [x for x in top if x["sold_to"] == t]
            for x in full["targets"]:
                if x["price"] is None:
                    continue  # unsold in reality: no price to compare
                cal.append((x["p_le_max"], 1.0 if x["price"] <= x["max_bid"] + 1e-9 else 0.0))
                ratio.append(x["price"] / x["expected_price"])
            rows.append(
                {
                    "team": t,
                    "kept": r["kept"],
                    "purse_left": r["purse_left"],
                    "actual_spend": r["actual_spend"],
                    "actual_bought": r["actual_bought"],
                    "same_ours": same["ours"],
                    "same_ours_xi": same["ours_xi"],
                    "same_ours_spend": same["ours_spend"],
                    "same_n": len(same["ours_bought"]),
                    "actual": same["actual"],
                    "actual_xi": same["actual_xi"],
                    "full_ours": full["ours"],
                    "full_ours_xi": full["ours_xi"],
                    "full_ours_spend": full["ours_spend"],
                    "full_expected": full["plan_expected"],
                    "next_ours": same["next_ours"],
                    "next_ours_xi": same["next_ours_xi"],
                    "next_actual": same["next_actual"],
                    "next_actual_xi": same["next_actual_xi"],
                    "full_next_ours": full["next_ours"],
                    "full_next_ours_xi": full["next_ours_xi"],
                    "top10_bought": len(got),
                    "top10_detail": [
                        (x["name"], round(x["price"], 2), round(x["max_bid"], 2)) for x in got
                    ],
                    "top10_le_max": sum(
                        1
                        for x in top
                        if x["price"] is not None and x["price"] <= x["max_bid"] + 1e-9
                    ),
                    "top10_unsold": sum(1 for x in top if x["price"] is None),
                }
            )
        n = len(rows)
        bins = []
        for lo, hi in ((0, 0.2), (0.2, 0.5), (0.5, 0.8), (0.8, 1.01)):
            sel = [(p, y) for p, y in cal if lo <= p < hi]
            if sel:
                bins.append({"band": f"{lo:.1f}-{min(hi, 1):.1f}", "n": len(sel),
                             "predicted": statistics.fmean(p for p, _ in sel),
                             "actual": statistics.fmean(y for _, y in sel)})  # fmt: skip
        summ[season] = {
            "price_to_beat": _ptb_summary(teams),
            "teams": rows,
            "same_ours_beats_actual": sum(1 for r in rows if r["same_ours"] > r["actual"]),
            "same_xi_beats_actual": sum(1 for r in rows if r["same_ours_xi"] > r["actual_xi"]),
            "mean_gap_total": statistics.fmean(r["same_ours"] - r["actual"] for r in rows)
            if n
            else 0,
            "mean_gap_xi": statistics.fmean(r["same_ours_xi"] - r["actual_xi"] for r in rows)
            if n
            else 0,
            "next_beats_actual": sum(1 for r in rows if r["next_ours"] > r["next_actual"]),
            "next_xi_beats_actual": sum(1 for r in rows if r["next_ours_xi"] > r["next_actual_xi"]),
            "next_mean_gap": statistics.fmean(r["next_ours"] - r["next_actual"] for r in rows)
            if n
            else 0,
            "next_mean_gap_xi": statistics.fmean(
                r["next_ours_xi"] - r["next_actual_xi"] for r in rows
            )
            if n
            else 0,
            "top10_bought_mean": statistics.fmean(r["top10_bought"] for r in rows) if n else 0,
            "calibration": bins,
            "brier": statistics.fmean((p - y) ** 2 for p, y in cal) if cal else None,
            "price_over_expected_median": statistics.median(ratio) if ratio else None,
            "n_targets": len(cal),
        }
    return summ


def _md(summ: dict) -> str:
    lines = []
    for season, s in summ.items():
        lines.append(f"\n### {season}\n")
        lines.append(
            "| team | kept | purse left | real spend / buys | ours, same spend: spend, buys | next season, ours: XI / total | next season, real: XI / total | our values, ours: XI / total | our values, real: XI / total | full purse, next season: XI / total | top-10 bought by team | top-10 sold ≤ our max |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in s["teams"]:
            lines.append(
                f"| {r['team']} | {r['kept']} | {r['purse_left']:.1f} | {r['actual_spend']:.1f} / {r['actual_bought']} | "
                f"{r['same_ours_spend']:.1f}, {r['same_n']} | "
                f"{r['next_ours_xi']:.1f} / {r['next_ours']:.1f} | {r['next_actual_xi']:.1f} / {r['next_actual']:.1f} | "
                f"{r['same_ours_xi']:.1f} / {r['same_ours']:.1f} | {r['actual_xi']:.1f} / {r['actual']:.1f} | "
                f"{r['full_next_ours_xi']:.1f} / {r['full_next_ours']:.1f} | "
                f"{r['top10_bought']} | {r['top10_le_max']} |"
            )
        lines.append(
            f"\nNext season (what the players really did), same spend: ours ahead for {s['next_beats_actual']} of {len(s['teams'])} teams "
            f"(XI: {s['next_xi_beats_actual']}); mean gap {s['next_mean_gap']:+.1f} total, {s['next_mean_gap_xi']:+.1f} XI. "
            f"On our own pre-auction values (circular: the plan maximises exactly this), same spend: ours ahead on total strength for {s['same_ours_beats_actual']} of {len(s['teams'])} teams "
            f"(XI: {s['same_xi_beats_actual']}); mean gap {s['mean_gap_total']:+.1f} total, {s['mean_gap_xi']:+.1f} XI. "
            f"Top-10 targets the team really bought: {s['top10_bought_mean']:.1f} on average. "
            f"Real price / our expected price, median over {s['n_targets']} targets: {s['price_over_expected_median']:.2f}. "
            f"P(≤ max bid) Brier {s['brier']:.3f}; by band: "
            + "; ".join(
                f"{b['band']}: predicted {b['predicted']:.2f}, actual {b['actual']:.2f} (n={b['n']})"
                for b in s["calibration"]
            )
        )
    for season, s in summ.items():
        q = s.get("price_to_beat") or {}
        if not q:
            continue
        lines.append(
            f"\n{season} price to beat (rivals' median) vs real price, the {q['n']} lots each team bought: "
            f"median real/ptb {q['median_ratio']:.2f}, MAE ln {q['mae_ln']:.2f}, rank corr {q['rank_corr']:.2f}, "
            f"top-10 ptb/real {q['top10_ratio']:.2f}, real inside the 20-80% band {q['inside_20_80']:.2f} "
            f"(market price alone: median real/market {q['market_median_ratio']:.2f}, MAE ln {q['market_mae_ln']:.2f})"
        )
        lines.append(
            "| player | real price | rivals' price to beat: median (20-80%) | market price |"
        )
        lines.append("|---|---|---|---|")
        for x in q["named"]:
            lines.append(
                f"| {x['name']} | {x['real']:.2f} | {x['ptb_median']:.2f} ({x['ptb_p20']:.2f}-{x['ptb_p80']:.2f}) | {x['market']:.2f} |"
            )
    return "\n".join(lines)


@app.command()
def main(
    work: Path = typer.Option(..., "--work", help="Folder for the cached per-team results."),
    trials: int = typer.Option(bp.TRIALS, "--trials"),
    out: Path | None = typer.Option(None, "--out", help="Write the full report JSON here."),
) -> None:
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    print("building the auction-time features …", flush=True)
    price_rows, risk_rows, hist, ret_rows = ipm.build_rows()
    pm = master.load()
    apps = ipm.ipl_appearances()
    tags = _tags_fn()
    print(f"  features in {time.time() - t0:.0f}s", flush=True)
    results: dict = {}
    for season in SEASONS:
        si = _season_inputs(season, (price_rows, ret_rows, risk_rows), hist, pm, apps, tags)
        print(f"{season}: {sum(1 for r in si['avail'] if r['_price'])} sold lots + "
              f"{sum(1 for r in si['avail'] if not r['_price'])} unsold, {len(si['teams'])} teams; price model "
              f"trained on {si['model']['trained_on']}", flush=True)  # fmt: skip
        results[str(season)] = {}
        for team in sorted(si["teams"]):
            f = work / f"{season}_{team}_{trials}.json"
            if f.exists():
                results[str(season)][team] = json.loads(f.read_text(encoding="utf-8"))
                continue
            t = time.time()
            r = _team_result(si, team, trials, tags)
            f.write_text(json.dumps(r, indent=1), encoding="utf-8")
            results[str(season)][team] = r
            print(f"  {season} {team}: {time.time() - t:.0f}s", flush=True)
    summ = _summarise(results)
    report = {"trials": trials, "results": results, "summary": summ}
    if out:
        out.write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    print(_md(summ))
    print(f"done in {time.time() - t0:.0f}s")
    if any(math.isnan(x) for s in summ.values() for x in (s["mean_gap_total"],)):
        raise SystemExit(1)


if __name__ == "__main__":
    app()
