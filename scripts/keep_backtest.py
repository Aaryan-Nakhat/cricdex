"""Keep or release, backtested on what franchises really did (docs/METHODOLOGY.md §10).

Every retention deadline with a complete published retained list (2018-2026: the 2018, 2022 and 2025
mega auctions and the mini auctions in between) is replayed with only what was known before it:

* the squad each franchise held before the deadline: everyone who played for it the season before
  (Cricsheet), plus its retained and bought players of that season (the auction history); a player
  another franchise lists as retained was traded and is left out, as is a published retirement;
* each player's market price from the price model fitted on the earlier auctions only (the shipped
  recipe, `ipl_price_model.fit_price_part`), his value, captaincy, caps and age as of the auction
  (`ipl_price_model.feature_fn`), and his three-season Form forecast built from the seasons up to the
  deadline (`scout/forecast.build_forecast` on the walk-forward ratings);
* what keeping him cost the purse: his contract salary in a mini year, the cycle's retention slab in a
  mega year (in order: 2018 15 / 11 / 7 cr capped, 3 cr uncapped; 2022 16 / 12 / 8 / 6, 4; 2025
  18 / 14 / 11 / 18 / 14, 4), and in 2026 the 2025 slab holders at the slab they free
  (web_parity/keep.retention_costs).

The label is the published retained list. Candidate rules (declared before any test number) are
chosen by leave-one-season-out on the deadlines up to 2024 and scored once on 2025 + 2026.

    uv run python scripts/keep_backtest.py rows --work <dir>      # build the rows (resumable, cached)
    uv run python scripts/keep_backtest.py score --work <dir> [--out data/metrics/keep_backtest_ipl.json]
"""

from __future__ import annotations

import json
import math
import pickle
import sys
from pathlib import Path

import numpy as np
import polars as pl
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ipl_price_model as ipm  # noqa: E402

from cricdex.config import DATA_DIR  # noqa: E402
from cricdex.scout import forecast as fc  # noqa: E402
from cricdex.scout.identity import captains, master  # noqa: E402
from cricdex.scout.ratings import bayesian  # noqa: E402
from cricdex.web_parity import keep as kp  # noqa: E402
from cricdex.web_parity import pricing  # noqa: E402

app = typer.Typer(add_completion=False)

SEASONS = (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)
SELECT_LAST = 2024
TEST = (2025, 2026)
OUT = DATA_DIR / "metrics" / "keep_backtest_ipl.json"
MODEL_OUT = Path(__file__).resolve().parents[1] / "config" / "keep_model.json"

# Mega-auction retention rules (purse deduction per retained player, in retention order). Sources:
# 2018 - IPL Governing Council, 6 Dec 2017 (ESPNcricinfo "IPL 2018: franchises can retain up to five
# players", three by retention at 15 / 11 / 7 cr, an uncapped player 3 cr); 2022 - IPL retention rules,
# Nov 2021 (ESPNcricinfo "IPL 2022 retention: what you need to know": four at 16 / 12 / 8 / 6 cr, an
# uncapped player 4 cr, at most three Indians and two overseas); 2025 - IPL Player Regulations
# 2025-27, 28 Sep 2024 (BCCI media release: six retentions or RTMs, capped 18 / 14 / 11 / 18 / 14 cr,
# uncapped 4 cr, at most five capped and two uncapped).
MEGA_RULES = {
    2018: {"capped": [15.0, 11.0, 7.0], "uncapped": 3.0, "max": 3, "max_uncapped": 2},
    2022: {"capped": [16.0, 12.0, 8.0, 6.0], "uncapped": 4.0, "max": 4, "max_uncapped": 2},
    2025: {"capped": [18.0, 14.0, 11.0, 18.0, 14.0], "uncapped": 4.0, "max": 6, "max_uncapped": 2},
}
# The 2025-27 cycle charges the 2025 mega-auction retentions by slab while they stay (keep.py)
SLAB_RULES_2025 = {
    "retained_cost": "slabs",
    "retention_slabs": MEGA_RULES[2025]["capped"],
    "uncapped_retention_slab": MEGA_RULES[2025]["uncapped"],
}
# The squads a deadline's franchises held: the season before, except the two sides suspended in 2016-17
PREV_SEASON = {(2018, "CSK"): 2015, (2018, "RR"): 2015}


def _played() -> tuple[dict, dict]:
    """((season, team) → cids who played for it; cid → [(season, team)] in order)."""
    import duckdb

    from cricdex.scout.identity import sources

    with duckdb.connect(str(bayesian.DEFAULT_DB_PATH), read_only=True) as con:
        hist = sources.ipl_team_seasons(con)
    by: dict[tuple[int, str], set[str]] = {}
    for cid, v in hist.items():
        for y, code in v:
            by.setdefault((y, code), set()).add(cid)
    return by, hist


def _forecasts(work: Path, origin: int) -> dict:
    """The Form forecast as it stood at the end of season `origin` (ratings and seasons up to it)."""
    f = work / f"forecast_{origin}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    import form_forecast as ff

    history = ff._history(False, 2026)
    history = history.filter(pl.col("season") <= origin)
    ratings = {t: pl.read_parquet(ipm.ipl_fit_path(t + 1)) for t in range(2008, origin + 1)}
    payload = fc.build_forecast(ratings, history, ff._dobs(), origin)
    f.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _outlook(fcst: dict, cid: str, role: str) -> dict | None:
    """keep_outlook's pick for this player (batting for batters / keepers, bowling for bowlers, the
    better three-season average for an all-rounder)."""
    o = fc.keep_outlook(fcst, cid, role)
    return o


@app.command()
def rows(work: Path = typer.Option(..., "--work")) -> None:
    """Build one row per (deadline, franchise, squad player) with the inputs and the label."""
    work.mkdir(parents=True, exist_ok=True)
    out_f = work / "rows.pkl"
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    features_in, hist, apps = ipm.feature_fn()
    played, team_hist = _played()
    pm = master.load()
    sq = json.loads((DATA_DIR / "curated" / "ipl_squads_2026.json").read_text(encoding="utf-8"))
    retired_2026 = {r.get("wiki_title") or r["name"] for r in sq.get("retired") or []}
    mega25 = (sq.get("mega_retentions_2025") or {}).get("teams") or {}
    done: dict = pickle.loads(out_f.read_bytes()) if out_f.exists() else {}
    for s in SEASONS:
        if s in done:
            typer.echo(f"{s}: cached ({len(done[s])} rows)")
            continue
        a = hist["auctions"][str(s)]
        date, purse, cycle = a["date"], float(a["purse_cr"]), a["kind"]
        fcst = _forecasts(work, s - 1)
        vals = ipm.asof_values(s, date)
        kept: dict[str, str] = {}
        for r in hist["retentions"]:
            if r["season"] == s and r["kind"] == "retained" and r.get("cricsheet_id"):
                kept[r["cricsheet_id"]] = r["team"]
        # the franchises of season s that held a squad before it (2022's two new sides had none)
        teams = sorted({r["team"] for r in hist["lots"] if r["season"] == s and r.get("sold")}
                       & {t for (y, t) in played if y == PREV_SEASON.get((s, t), s - 1)})  # fmt: skip
        out = []
        for team in teams:
            prev = PREV_SEASON.get((s, team), s - 1)
            members = set(played.get((prev, team), set()))
            for r in hist["retentions"]:
                if r["season"] == prev and r["team"] == team and r.get("cricsheet_id"):
                    members.add(r["cricsheet_id"])
            for r in hist["lots"]:
                if (
                    r["season"] == prev
                    and r.get("sold")
                    and r["team"] == team
                    and r.get("cricsheet_id")
                ):
                    members.add(r["cricsheet_id"])
            for cid in sorted(members):
                if cid in kept and kept[cid] != team and kept[cid] in teams:
                    continue  # traded to another franchise before the deadline
                # (a pick of a new franchise's draft, 2022, was released by this one: kept = False)
                rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
                if s == 2026 and (rec.get("wiki_title") in retired_2026):
                    continue
                f = features_in(cid, s, date, vals, None)
                # his contract salary: the latest price paid for him (auction or retention) before s
                lots_prev = [r for r in hist["lots"] if r.get("cricsheet_id") == cid
                             and r.get("sold") and r["season"] < s]  # fmt: skip
                rets_prev = [r for r in hist["retentions"] if r.get("cricsheet_id") == cid
                             and r["season"] < s and r.get("salary_cr")]  # fmt: skip
                paid = [(r["season"], float(r["price_cr"])) for r in lots_prev if r.get("price_cr")]
                paid += [(r["season"], float(r["salary_cr"])) for r in rets_prev]
                salary = max(paid)[1] if paid else None
                bought_prev = any(r["season"] == prev and r["team"] == team for r in lots_prev)
                seasons_here = sorted({y for y, t in team_hist.get(cid, []) if t == team and y < s})
                first_team = (
                    team_hist.get(cid, [(None, None)])[0][1] if team_hist.get(cid) else None
                )
                o = _outlook(fcst, cid, f["role"])
                cap = captains.as_of(cid, s)
                out.append({
                    **f, "team": team, "season": s, "cycle": cycle, "purse": purse,
                    "name": rec.get("display_name") or cid,
                    "kept": kept.get(cid) == team, "salary": salary, "salary_known": salary is not None,
                    "bought_prev": bought_prev, "seasons_here": len(seasons_here),
                    "home_grown": first_team == team,
                    "captain_here": team in (cap.get("captain_teams") or []),
                    "forecast_avg3": o["avg3"] if o else None,
                    "forecast_p_regular": o["p_regular_last"] if o else None,
                    "forecast_median": o["median"] if o else None,
                    "slab_holder_2025": None,
                })  # fmt: skip
        # 2026: the 2025 mega retentions still at their franchise are charged by slab
        if s == 2026:
            for team, block in mega25.items():
                for kind in ("capped", "uncapped"):
                    for name in block.get(kind, []):
                        for r in out:
                            if r["team"] == team and r["name"] == name:
                                r["slab_holder_2025"] = kind
        done[s] = out
        out_f.write_bytes(pickle.dumps(done))
        n_kept = sum(r["kept"] for r in out)
        typer.echo(f"{s}: {len(out)} squad players, {n_kept} kept, {len(teams)} teams")
    typer.echo("done")


# ---- scoring ---------------------------------------------------------------------------------------


def _market(work: Path, data: dict, letter: str | None) -> dict:
    """(season, team, cid) → (market price, the upper quartile on his central value) from the price
    recipe (`letter`, else the shipped one) fitted on the auctions before each deadline only."""
    spec_name = letter or "shipped"
    f = work / f"market_{spec_name}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    price_rows, _risk, hist, ret_rows = ipm.build_rows()
    spec = (
        ipm.shipped_spec()
        if not letter
        else next(v for k, v in ipm.CANDIDATES.items() if k.split()[0] == letter)
    )
    # the shipped resale rule (ipl_price_model.py resale), refitted on the resold lots before each
    # deadline only
    rs = ((pricing.load_price_model() or {}).get("price") or {}).get("resale")
    lots = ipm.resale_lots(price_rows, ret_rows, spec) if rs and not letter else []
    out: dict = {}
    for s, rows in data.items():
        a = hist["auctions"][str(s)]
        model = {
            "floor_cr": 0.2 if s < 2025 else 0.3,
            "competition": {"cycle": a["kind"], "purse": float(a["purse_cr"])},
            # 2018 and 2019 have too few auctions since 2018 to fit on: 2011 on for those two
            "price": ipm.fit_price_part(price_rows, ret_rows, spec, 2018 if s > 2019 else 2011, s),
            "bought": (pricing.load_price_model() or {}).get("bought"),
        }
        before = [r for r in lots if r["season"] < s and r["prior_share"]
                  and r["prior_years"] is not None and r["prior_years"] <= rs["max_years"]]  # fmt: skip
        if len(before) >= RESALE_MIN_LOTS:
            model["price"]["resale"] = {"max_years": rs["max_years"],
                                        **ipm.resale_coefs(ipm._resale_fit(before, rs.get("rule", "R1")))}  # fmt: skip
        for r in rows:
            # the row as the recipe prices it (its value input: ipl_price_model._valued)
            rv = ipm._valued(r)
            mk = pricing.market_price(rv, model["competition"], model)
            hi = pricing.market_price({**rv, "value_sd": 0.0}, model["competition"], model)["high"]
            out[(s, r["team"], r["cricsheet_id"])] = (mk["price"], hi)
        typer.echo(f"market {s}: {len(rows)} priced")
    f.write_bytes(pickle.dumps(out))
    return out


def _capped(r: dict) -> bool:
    return (r.get("intl_caps") or 0) > 0


def _costs(rows: list[dict], s: int) -> None:
    """Each row's `cost`: what keeping him cost the purse. Mini: his salary (the lowest base price
    when unknown), and in 2026 the 2025 slab holders at the slab their release frees. Mega: the slab
    of his position, the team's players taken in market-price order (capped and uncapped slabs
    apart; None past the last slab: he can't be retained)."""
    floor = 0.2 if s < 2025 else 0.3
    if s in MEGA_RULES:
        rule = MEGA_RULES[s]
        by_team: dict[str, list[dict]] = {}
        for r in rows:
            by_team.setdefault(r["team"], []).append(r)
        for team_rows in by_team.values():
            kc = ku = 0
            for r in sorted(team_rows, key=lambda x: -x["market"]):
                if _capped(r):
                    r["cost"] = rule["capped"][kc] if kc < len(rule["capped"]) else None
                    kc += 1
                else:
                    r["cost"] = rule["uncapped"] if ku < rule["max_uncapped"] else None
                    ku += 1
        return
    for r in rows:
        r["cost"] = float(r["salary"]) if r.get("salary") else floor
    if s == 2026:
        by_team = {}
        for r in rows:
            by_team.setdefault(r["team"], []).append(r)
        for team, team_rows in by_team.items():
            sq = [{"id": r["cricsheet_id"], "team": team, "name": r["name"], "salary": r["cost"],
                   "slab_holder": r.get("slab_holder_2025")} for r in team_rows]  # fmt: skip
            c = kp.retention_costs(sq, SLAB_RULES_2025)
            for r, q in zip(team_rows, sq, strict=True):
                r["cost"] = c[kp.player_key(q)]


def _feats(r: dict) -> dict[str, float]:
    """The candidate inputs of one row (all known before the deadline): web_parity/keep.py
    `keep_features`, the same function the page and the CLI use."""
    return kp.keep_features(
        r["market"], r["cost"] or 0.0, r["cycle"] == "mega", r.get("forecast_avg3"),
        r.get("forecast_p_regular"), bool(r.get("captain_here")), int(r.get("seasons_here") or 0),
        bool(r.get("home_grown")), _capped(r) and not r.get("is_overseas"),
        bool(r.get("is_overseas")), r.get("age"), r.get("ipl_balls"), bool(r.get("bought_prev")),
        r.get("p_play"), r.get("contrib"), bool(r.get("mega_retained")),
    )  # fmt: skip


def _mega_retained(data: dict) -> None:
    """Each mini-year row's `mega_retained`: his franchise retained him at the cycle's mega auction
    (2018 for 2019-21, 2022 for 2023-24, 2025 for 2026), from the published retained lists. In place."""
    hist = json.loads(ipm.HISTORY.read_text(encoding="utf-8"))
    megas = sorted(MEGA_RULES)
    ret = {(r["season"], r["cricsheet_id"]): r["team"] for r in hist["retentions"]
           if r["season"] in MEGA_RULES and r["kind"] == "retained" and r.get("cricsheet_id")}  # fmt: skip
    for s, rows in data.items():
        last = max((m for m in megas if m < s), default=None)
        for r in rows:
            r["mega_retained"] = (
                s not in MEGA_RULES and last is not None
                and ret.get((last, r["cricsheet_id"])) == r["team"]
            )  # fmt: skip


def _playing_time(data: dict) -> None:
    """Each row's playing time before the deadline (METHODOLOGY §6c): his contribution per match as
    of the auction (`playing_time_fit.py asof-contrib`) and P(plays a match) in the squad his
    franchise held before the deadline, from the squad model (playing_time_fit `play`) fitted
    out of fold: for a deadline up to 2024 on the other seasons up to 2024, for 2025-26 on
    2018-2024 (the model of the test). In place: `contrib`, `p_play`."""
    import playing_time_fit as ptf

    from cricdex.scout import playing_time as pt

    rep_ = ptf._read()
    feats = ptf.PLAY_CANDIDATES[rep_["play"]["chosen"]]
    alpha = rep_["play"]["alpha"]
    prows = ptf._all_play_rows(bool(rep_["play"].get("xi_by_era")))
    contrib = {(s_, c): v for (s_, c), v in ipm._asof_contrib().items()}
    u = ptf._u()
    _team_m, _played, share = ptf.ipl_shares(u)
    i = u.filter(pl.col("league") == "ipl")
    roles = ptf._roles()
    models: dict[int, pt.PlayModel] = {}
    for s in SEASONS:
        tr = [r for r in prows if r["season"] <= SELECT_LAST and r["season"] != s]
        models[s] = pt.fit_play_model(tr, feats, alpha)
    for s, rows in data.items():
        date = ipm.AUCTIONS_DATES.get(s) or ipm.auction_dates()[s]
        ipl_m = dict(i.filter(pl.col("date") < date).group_by("cid").agg(pl.len()).iter_rows())
        by_team: dict[str, list[dict]] = {}
        for r in rows:
            by_team.setdefault(r["team"], []).append(r)
        for team_rows in by_team.values():
            squad = []
            for r in team_rows:
                c = contrib.get((s, r["cricsheet_id"]))
                r["contrib"] = c[0] if c else None
                squad.append(pt.squad_member(r["cricsheet_id"], c[0] if c else 0.0,
                                             r["role"], bool(r.get("is_overseas"))))  # fmt: skip
            xi = pt.projected_xi(squad, pt.xi_size(s, bool(rep_["play"].get("xi_by_era"))))
            for r in team_rows:
                cid = r["cricsheet_id"]
                x = xi[cid]
                meta = {
                    "contrib": squad[[q["cid"] for q in squad].index(cid)]["c"],
                    "in_xi": x["in_xi"], "margin": x["margin"], "rank": x["rank"],
                    "os_rank": x["os_rank"], "overseas": bool(r.get("is_overseas")),
                    "ipl_matches": ipl_m.get(cid, 0), "age": r.get("age"),
                    "last_share": share.get((s - 1, cid), 0.0),
                    "keeper": roles.get(cid) == "keeper",
                    "captain": bool(captains.as_of(cid, s).get("captain_ipl_last")),
                    "season": s,
                }  # fmt: skip
                r["p_play"] = models[s].prob(pt.play_features(meta))


# a deadline's resale rule needs this many resold lots before it (else the model's price alone)
RESALE_MIN_LOTS = 20


# Candidate rules, declared before any test number (2026-10-22). "rule": a threshold on one index;
# "logit": a logistic regression of the franchise's decision on the inputs.
BASE = ["log_ratio", "mega", "mega_x_log_ratio"]
FORECAST = ["forecast", "forecast_regular", "no_forecast"]
FRANCHISE = ["captain_here", "seasons_here", "home_grown"]
STATUS = ["capped_indian", "overseas", "age", "age_over_33", "ipl_balls", "bought_prev", "log_cost"]
# playing time (declared 2026-10-22 evening, audit items 4 and 6, before any of its numbers): P(plays a
# match) in his squad and P × his contribution per match (runs above replacement)
PLAY = ["p_play", "play_value", "no_play"]
# retained at the cycle's mega auction (declared 2026-10-29, before any of its numbers: the owner's
# reality check that Rohit Sharma, retained by MI in 2025, is no toss-up)
MEGA_RET = ["mega_retained"]
# reference only (not a candidate): keep everyone the rules allow
BASELINE = ("B0 keep everyone the rules allow", ("all", None))
CANDIDATES = {
    "C0 shipped rule (market vs cost, 0.5 cr / 15% margins, age 35)": ("current", None),
    "C1 market price vs cost, threshold fitted": ("rule", "log_ratio"),
    "C2 market price on the 3-season forecast vs cost, threshold fitted": ("rule", "log_ratio_fc"),
    "L1 logistic: market vs cost": ("logit", BASE),
    "L2 L1 + 3-season forecast": ("logit", BASE + FORECAST),
    "L3 L2 + franchise ties (captain, seasons there, home-grown)": ("logit", BASE + FORECAST + FRANCHISE),
    "L4 L3 + status (capped Indian, overseas, age, IPL balls, last auction's buy, cost)": (
        "logit", BASE + FORECAST + FRANCHISE + STATUS),
    "L5 L4 + playing time (P(plays) in his squad, P(plays) x contribution per match)": (
        "logit", BASE + FORECAST + FRANCHISE + STATUS + PLAY),
    "L6 L5 without the Form forecast": ("logit", BASE + FRANCHISE + STATUS + PLAY),
    "L7 L4 + retained at the cycle's mega auction": (
        "logit", BASE + FORECAST + FRANCHISE + STATUS + MEGA_RET),
}  # fmt: skip
C_GRID = (0.03, 0.1, 0.3, 1.0, 3.0)


def _current(r: dict) -> bool:
    """The shipped rule before 2026-10-22 (keep.py): Release when even the upper quartile on his
    central value is 0.5 cr / 15% below what he costs; everything else kept by default."""
    if r["cost"] is None:
        return False
    m = max(OLD_MARGIN_MIN, OLD_MARGIN_SHARE * r["cost"])
    return not (r["market_central"] - r["cost"] <= -m)


OLD_MARGIN_MIN, OLD_MARGIN_SHARE = 0.5, 0.15  # keep.py's KEEP_MARGIN_MIN / _SHARE until 2026-10-22


def _apply_caps(rows: list[dict], keep: list[bool], score: list[float]) -> list[bool]:
    """A mega deadline's retention limits: per team at most `max` players (`max_uncapped`
    uncapped), the highest scores first; a player past the last slab can't be kept."""
    out = list(keep)
    s = rows[0]["season"] if rows else 0
    if s not in MEGA_RULES:
        return out
    rule = MEGA_RULES[s]
    by_team: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_team.setdefault(r["team"], []).append(i)
    for idx in by_team.values():
        n = nu = 0
        for i in sorted(idx, key=lambda i: -score[i]):
            if not out[i]:
                continue
            if rows[i]["cost"] is None or n >= rule["max"]:
                out[i] = False
                continue
            if not _capped(rows[i]):
                if nu >= rule["max_uncapped"]:
                    out[i] = False
                    continue
                nu += 1
            n += 1
    return out


def _fit_rule(train: list[dict], key: str) -> float:
    """The threshold on `key` with the best F1 for 'kept' on `train`."""
    xs = sorted({round(r["_f"][key], 3) for r in train})
    best = (-1.0, 0.0)
    for t in xs:
        f1 = _prf([r["_f"][key] >= t for r in train], [r["kept"] for r in train])["f1"]
        if f1 > best[0]:
            best = (f1, t)
    return best[1]


def _fit_logit(train: list[dict], names: list[str], c: float):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X = np.array([[r["_f"][k] for k in names] for r in train])
    y = np.array([r["kept"] for r in train], dtype=int)
    return make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=5000)).fit(X, y)


def _logit_p(m, rows: list[dict], names: list[str]) -> np.ndarray:
    X = np.array([[r["_f"][k] for k in names] for r in rows])
    return m.predict_proba(X)[:, 1]


def _prf(pred: list[bool], y: list[bool]) -> dict:
    tp = sum(1 for p, t in zip(pred, y, strict=True) if p and t)
    fp = sum(1 for p, t in zip(pred, y, strict=True) if p and not t)
    fn = sum(1 for p, t in zip(pred, y, strict=True) if not p and t)
    tn = len(y) - tp - fp - fn
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    rel_ok = tn / (tn + fn) if tn + fn else 0.0  # of the players we release, the share released
    spec = tn / (tn + fp) if tn + fp else 0.0  # of the players released, the share we release
    return {"n": len(y), "kept": tp + fn, "called_keep": tp + fp, "precision": round(prec, 3),
            "recall": round(rec, 3), "f1": round(f1, 3), "release_precision": round(rel_ok, 3),
            "release_recall": round(spec, 3), "balanced_accuracy": round((rec + spec) / 2, 3),
            "accuracy": round((tp + tn) / len(y), 3) if y else 0.0}  # fmt: skip


def _tier(r: dict) -> str:
    """Star: what is at stake is at least 8% of the purse (10 cr at 125), on his cost or his market
    price; regular: 2-8%; depth: below."""
    x = max(r["cost"] or 0.0, r["market"]) / r["purse"]
    return "star" if x >= 0.08 else "regular" if x >= 0.02 else "depth"


def _report(rows: list[dict], pred: list[bool]) -> dict:
    out = {"all": _prf(pred, [r["kept"] for r in rows])}
    for t in ("star", "regular", "depth"):
        idx = [i for i, r in enumerate(rows) if _tier(r) == t]
        out[t] = _prf([pred[i] for i in idx], [rows[i]["kept"] for i in idx])
    for cyc in ("mega", "mini"):
        idx = [i for i, r in enumerate(rows) if r["cycle"] == cyc]
        if idx:
            out[cyc] = _prf([pred[i] for i in idx], [rows[i]["kept"] for i in idx])
    return out


def _predict(kind, arg, train: list[dict], test: list[dict], c: float | None = None):
    """(kept calls, scores, fitted parameter) for `test` from a candidate fitted on `train`."""
    if kind == "all":
        keep = [r["cost"] is not None for r in test]
        score = [r["_f"]["log_ratio"] for r in test]
        return _apply_caps(test, keep, score), score, None
    if kind == "current":
        keep = [_current(r) for r in test]
        score = [r["_f"]["log_ratio"] for r in test]
        return _apply_caps(test, keep, score), score, None
    if kind == "rule":
        out_k, out_s = [False] * len(test), [0.0] * len(test)
        par = {}
        for cyc in ("mega", "mini"):
            tr = [r for r in train if r["cycle"] == cyc and r["cost"] is not None]
            idx = [i for i, r in enumerate(test) if r["cycle"] == cyc]
            if not idx:
                continue
            t = _fit_rule(tr, arg)
            par[cyc] = t
            for i in idx:
                out_s[i] = test[i]["_f"][arg]
                out_k[i] = test[i]["cost"] is not None and out_s[i] >= t
        return _apply_caps(test, out_k, out_s), out_s, par
    tr = [r for r in train if r["cost"] is not None]
    m = _fit_logit(tr, arg, c)
    # past the last retention slab a player can't be kept at all: P = 0
    p = np.where([r["cost"] is None for r in test], 0.0, _logit_p(m, test, arg))
    keep = [bool(x >= 0.5) and r["cost"] is not None for x, r in zip(p, test, strict=True)]
    return _apply_caps(test, keep, list(p)), list(p), m


def _logloss(p: list[float], y: list[bool]) -> float:
    q = np.clip(np.array(p), 1e-6, 1 - 1e-6)
    t = np.array(y, dtype=float)
    return float(-np.mean(t * np.log(q) + (1 - t) * np.log(1 - q)))


@app.command()
def score(
    work: Path = typer.Option(..., "--work"),
    recipe: str = typer.Option(
        "", "--recipe", help="price recipe letter (default: the shipped one)"
    ),
    out: Path = typer.Option(OUT, "--out"),
    model_out: Path = typer.Option(MODEL_OUT, "--model-out", help="the shipped model (keep.py)"),
) -> None:
    """Choose the rule by leave-one-deadline-out on the deadlines up to 2024, score it once on 2025
    (mega) + 2026 (mini)."""
    data: dict = pickle.loads((work / "rows.pkl").read_bytes())
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    _playing_time(data)
    _mega_retained(data)
    mk = _market(work, data, recipe or None)
    for s, rows in data.items():
        for r in rows:
            r["market"], r["market_central"] = mk[(s, r["team"], r["cricsheet_id"])]
        _costs(rows, s)
    # the market price on the 3-season forecast (what a buyer buys over a contract)
    fcm = _forecast_market(work, data, recipe or None)
    for s, rows in data.items():
        for r in rows:
            r["_f"] = _feats(r)
            fm = fcm.get((s, r["team"], r["cricsheet_id"]))
            cost = r["cost"] if r["cost"] else 1e-3
            r["_f"]["log_ratio_fc"] = (
                math.log(max(fm, 1e-3) / cost) if fm is not None else r["_f"]["log_ratio"]
            )
    early = [s for s in SEASONS if s <= SELECT_LAST]
    res: dict = {"protocol": {
        "selection": "leave one deadline out over 2018-2024 (each deadline predicted by the rule "
                     "fitted on the others up to 2024); highest F1 for 'kept' on the pooled "
                     "held-out calls wins, a tie going to the lower held-out log loss (logistic C "
                     "chosen the same way)",
        "test": "fitted on 2018-2024, scored once on 2025 (mega) + 2026 (mini)",
        "label": "the published retained list; traded players and 2026's published retirements "
                 "left out",
    }, "selection": {}}  # fmt: skip
    best = None
    for name, (kind, arg) in [BASELINE, *CANDIDATES.items()]:
        cs = C_GRID if kind == "logit" else (None,)
        for c in cs:
            preds, ys, ps = [], [], []
            for s in early:
                tr = [r for t in early if t != s for r in data[t]]
                k, sc, _ = _predict(kind, arg, tr, data[s], c)
                preds += k
                ys += [r["kept"] for r in data[s]]
                ps += sc
            rows_all = [r for s in early for r in data[s]]
            rep = _report(rows_all, preds)
            label = name if c is None else f"{name} (C={c})"
            if kind == "logit":
                rep["log_loss"] = round(_logloss(ps, ys), 4)
            res["selection"][label] = rep
            typer.echo(
                f"{label[:78]:78} F1 {rep['all']['f1']:.3f} P {rep['all']['precision']:.3f} "
                f"R {rep['all']['recall']:.3f} BA {rep['all']['balanced_accuracy']:.3f} "
                f"star F1 {rep['star']['f1']:.3f}"
                + (f" LL {rep['log_loss']:.4f}" if kind == "logit" else "")
            )
            # a tie on F1 (to 3 places) goes to the lower held-out log loss (2026-10-29: L7 tied L4)
            key = (rep["all"]["f1"], -rep.get("log_loss", math.inf))
            if kind != "all" and (best is None or key > best[0]):
                best = (key, name, c)
    _, chosen, chosen_c = best
    res["chosen"] = chosen if chosen_c is None else f"{chosen} (C={chosen_c})"
    typer.echo(f"chosen: {res['chosen']}")

    # the test, once: fitted on 2018-2024, scored on 2025 + 2026 (chosen, and the shipped rule)
    train = [r for s in early for r in data[s]]
    res["test"] = {}
    ref = next(iter(CANDIDATES))
    cands = dict([BASELINE, *CANDIDATES.items()])
    for name in dict.fromkeys([chosen, ref, BASELINE[0]]):
        kind, arg = cands[name]
        c = chosen_c if name == chosen else None
        rows_t, preds_t, ps_t = [], [], []
        for s in TEST:
            k, sc, _ = _predict(kind, arg, train, data[s], c)
            rows_t += data[s]
            preds_t += k
            ps_t += sc
            res["test"].setdefault(name, {})[str(s)] = _report(data[s], k)
        rep = _report(rows_t, preds_t)
        if kind == "logit":
            rep["log_loss"] = round(_logloss(ps_t, [r["kept"] for r in rows_t]), 4)
        res["test"][name]["pooled"] = rep
        # where the call and the franchise disagree, stars first (the honest list)
        dis = []
        for r, k, sc in zip(rows_t, preds_t, ps_t, strict=True):
            if k != r["kept"] and _tier(r) == "star":
                dis.append({"season": r["season"], "team": r["team"], "name": r["name"],
                            "kept": r["kept"], "call": "keep" if k else "release",
                            "score": round(float(sc), 3), "cost": r["cost"],
                            "market": round(r["market"], 2), "age": r.get("age") and round(r["age"], 1),
                            "captain_here": r.get("captain_here"),
                            "seasons_here": r.get("seasons_here"),
                            "home_grown": r.get("home_grown")})  # fmt: skip
        res["test"][name]["star_disagreements"] = dis
        typer.echo(f"TEST {name[:60]}: {json.dumps(rep['all'])} star {json.dumps(rep['star'])}")

    # the shipped rule: the chosen candidate refitted on every deadline 2018-2026
    kind, arg = CANDIDATES[chosen]
    every = [r for s in SEASONS for r in data[s] if r["cost"] is not None]
    if kind == "logit":
        m = _fit_logit(every, arg, chosen_c)
        sc_, est = m[0], m[-1]
        names = list(arg)
        scale = np.where(sc_.scale_ == 0, 1.0, sc_.scale_)
        raw = est.coef_.ravel() / scale
        icpt = float(est.intercept_[0]) - float(np.sum(raw * sc_.mean_))
        res["model"] = {"kind": "logit", "C": chosen_c, "intercept": round(icpt, 6),
                        "coef": {k: round(float(v), 6) for k, v in zip(names, raw, strict=True)},
                        "trained_on": [SEASONS[0], SEASONS[-1]], "rows": len(every)}  # fmt: skip
    elif kind == "rule":
        res["model"] = {"kind": "rule", "index": arg,
                        "threshold": {cyc: _fit_rule([r for r in every if r["cycle"] == cyc], arg)
                                      for cyc in ("mega", "mini")}}  # fmt: skip
    else:
        res["model"] = {"kind": "current"}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    typer.echo(f"wrote {out}")
    if res["model"]["kind"] == "logit":
        import datetime as _dt

        shipped = {
            "schema": 1,
            "league": "ipl",
            "fitted": _dt.date.today().isoformat(),
            "method": "P(a franchise keeps him at the retention deadline) = logistic regression on "
                      "web_parity/keep.py keep_features (L2, standardised, refolded to raw units), "
                      f"recipe '{res['chosen']}', chosen by leave one deadline out on 2018-2024 "
                      "(scripts/keep_backtest.py)",
            "data": "the published retained lists of every deadline 2018-2026 "
                    "(data/curated/ipl_auction_history.json, Wikipedia, CC BY-SA 4.0) against each "
                    "franchise's squad before it",
            "intercept": res["model"]["intercept"],
            "coef": res["model"]["coef"],
            "trained_on": res["model"]["trained_on"],
            "rows": res["model"]["rows"],
            "evaluation": {"protocol": res["protocol"], "chosen": res["chosen"],
                           "test": {k: v["pooled"] for k, v in res["test"].items()}},
        }  # fmt: skip
        model_out.write_text(
            json.dumps(shipped, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        typer.echo(f"wrote {model_out}")


def _forecast_market(work: Path, data: dict, letter: str | None) -> dict:
    """(season, team, cid) → his market price with the 3-season forecast average as his value (what
    a buyer pays for over a contract; None without a forecast)."""
    spec_name = letter or "shipped"
    f = work / f"fcmarket_{spec_name}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    price_rows, _risk, hist, ret_rows = ipm.build_rows()
    spec = (
        ipm.shipped_spec()
        if not letter
        else next(v for k, v in ipm.CANDIDATES.items() if k.split()[0] == letter)
    )
    out: dict = {}
    for s, rows in data.items():
        a = hist["auctions"][str(s)]
        model = {
            "floor_cr": 0.2 if s < 2025 else 0.3,
            "competition": {"cycle": a["kind"], "purse": float(a["purse_cr"])},
            "price": ipm.fit_price_part(price_rows, ret_rows, spec, 2018 if s > 2019 else 2011, s),
            "bought": (pricing.load_price_model() or {}).get("bought"),
        }
        for r in rows:
            if r.get("forecast_avg3") is None:
                continue
            # the forecast is the value itself (no cautious discount: its range is already in it)
            row = {**ipm._valued(r), "price_value": float(r["forecast_avg3"]), "value_sd": 0.0}
            out[(s, r["team"], r["cricsheet_id"])] = pricing.market_price(
                row, model["competition"], model
            )["price"]
    f.write_bytes(pickle.dumps(out))
    return out


if __name__ == "__main__":
    app()
