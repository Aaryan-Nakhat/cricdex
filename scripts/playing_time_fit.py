"""Fit and validate the playing-time model: expected balls, replacement levels and P(plays)
(docs/METHODOLOGY.md §6c; `src/cricdex/scout/playing_time.py`).

The frozen protocol (audit items 4 and 6, 2026-10-22): every candidate is declared below before any
test number; candidates are fitted on seasons up to 2023 and chosen on 2024 (validation); the chosen
one is refitted on seasons up to 2024 and scored **once** on the held-out 2025 and 2026 seasons; the
shipped model is then refitted on everything up to 2026.

    uv run python scripts/playing_time_fit.py usage            # player-match usage, all pool leagues (~30 s)
    uv run python scripts/playing_time_fit.py balls            # expected balls: select, test, report
    uv run python scripts/playing_time_fit.py play             # P(plays): rows, select, test, report
    uv run python scripts/playing_time_fit.py ship             # write config/playing_time_model.json

Results: data/metrics/playing_time_ipl.json.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ipl_price_model as ipm  # noqa: E402

from cricdex import leagues  # noqa: E402
from cricdex.config import DATA_DIR  # noqa: E402
from cricdex.scout import playing_time as pt  # noqa: E402
from cricdex.scout import translation  # noqa: E402
from cricdex.scout.identity import captains, master  # noqa: E402
from cricdex.scout.identity.sources import IPL_TEAM_CODES_ALL  # noqa: E402
from cricdex.scout.ratings import bayesian  # noqa: E402

app = typer.Typer(add_completion=False)

OUT = DATA_DIR / "metrics" / "playing_time_ipl.json"
HISTORY_PATH = DATA_DIR / "metrics" / ".forecast_history_ipl.parquet"
POOL_COLS = [lg.key for lg in leagues.auction_pool()]
ROLE_MAP = {
    "wk_batter": "keeper",
    "allrounder": "all_rounder",
    "bowler": "bowler",
    "batter": "batter",
}

BALLS_FIRST = 2012  # first target season of the expected-balls fit (other leagues from ~2011)
VALID = 2024
TEST = (2025, 2026)
PLAY_SEASONS = (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)  # complete retained lists
REPL_FIRST = 2012  # min-price buys from this auction on set the replacement levels

# Expected-balls candidates, declared before any test number (2026-10-22).
BALLS_CANDIDATES = {
    "E0 role mean (reference)": {"kind": "role"},
    "E1 last IPL season's share, else role mean (reference)": {"kind": "last"},
    "E2 credibility: IPL history only": {"kind": "cred", "other": False, "era": False},
    "E3 credibility: IPL + other leagues": {"kind": "cred", "other": True, "era": False},
    "E4 E3 with impact-era role means (2023+)": {"kind": "cred", "other": True, "era": True},
}
K0_GRID = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0)
KO_GRID = (0.1, 0.25, 0.5, 1.0)
DECAY_GRID = (0.4, 0.6, 0.8, 1.0)

# P(plays) candidates, declared before any test number (2026-10-22).
_P_RANK = ("contrib", "in_xi", "margin", "rank_log")
_P_OS = ("overseas", "os_out", "os_rank_gt4")
_P_EXP = ("ipl_exp", "never_ipl", "age", "age_gt32")
_P_AVAIL = ("last_share", "no_last")
_P_OTHER = ("keeper", "captain", "impact_era")
_P_ALL = _P_RANK + _P_OS + _P_EXP + _P_AVAIL + _P_OTHER
PLAY_CANDIDATES = {
    "P0 base rate (reference)": (),
    "P1 rank in the squad": _P_RANK,
    "P2 P1 + overseas places": _P_RANK + _P_OS,
    "P3 P2 + experience and age": _P_RANK + _P_OS + _P_EXP,
    "P4 P3 + availability (last season's share)": _P_RANK + _P_OS + _P_EXP + _P_AVAIL,
    "P5 P4 + keeper, captain, impact era": _P_RANK + _P_OS + _P_EXP + _P_AVAIL + _P_OTHER,
    # declared 2026-10-27 (an analyst's review: the impact player), before any of its numbers: P5 with
    # each squad's projected side 12 players from 2023 (pt.xi_size), as Cricsheet's match lists show
    # (11.95-11.97 players a side a match 2023-26, 11.0 before)
    "P6 P5 with a side of 12 in the impact-player era": _P_ALL,
}
# the candidates whose projected side is 12 from 2023 (the rest: 11 in every season)
PLAY_XI_BY_ERA = {"P6 P5 with a side of 12 in the impact-player era"}
PLAY_ALPHAS = (0.1, 1.0, 10.0, 100.0)
DISC = {"sf": "bat", "sb": "bowl"}


def _u() -> pl.DataFrame:
    return pt.usage_all(bayesian.DEFAULT_DB_PATH, POOL_COLS)


def _roles() -> dict[str, str]:
    pm = master.load()
    return {cid: ROLE_MAP.get((r or {}).get("primary_role") or "", "batter")
            for cid, r in pm.items() if isinstance(r, dict)}  # fmt: skip


def season_starts(u: pl.DataFrame) -> dict[int, str]:
    i = u.filter(pl.col("league") == "ipl")
    return dict(i.group_by("season").agg(pl.col("date").min()).iter_rows())


# ---- expected balls --------------------------------------------------------------------------------


def balls_targets(u: pl.DataFrame) -> pl.DataFrame:
    """One row per (IPL season, player): his matches, and his share of his side's legal balls faced
    and bowled over the matches he played."""
    i = u.filter(
        (pl.col("league") == "ipl")
        & pl.col("team_faced").is_not_null()
        & pl.col("team_bowled").is_not_null()
        & (pl.col("team_faced") > 0)
        & (pl.col("team_bowled") > 0)
    )
    return i.group_by("season", "cid").agg(
        pl.len().alias("m"),
        (pl.col("faced").sum() / pl.col("team_faced").sum()).alias("sf"),
        (pl.col("bowled").sum() / pl.col("team_bowled").sum()).alias("sb"),
    )


def _priors(u: pl.DataFrame, starts: dict[int, str], seasons, decay: float) -> dict:
    return {s: pt.prior_usage(u, starts[s], decay) for s in seasons}


def _last_share(u: pl.DataFrame, seasons) -> dict:
    """(season, cid) → (bat share, bowl share) in his last IPL season before it (None if none)."""
    t = balls_targets(u)
    out = {}
    by: dict[str, list[tuple[int, float, float]]] = {}
    for s, cid, _m, sf, sb in t.sort("season").iter_rows():
        by.setdefault(cid, []).append((s, sf, sb))
    for cid, v in by.items():
        for s in seasons:
            prev = [x for x in v if x[0] < s]
            if prev:
                out[(s, cid)] = (prev[-1][1], prev[-1][2])
    return out


def _mu(rows: list[dict], disc: str, era: bool) -> dict[str, float]:
    """Mean share by role (weighted by matches); with `era`, separate means for 2023+ under
    "<role>@impact"."""
    acc: dict[str, list[float]] = {}
    for r in rows:
        keys = [r["role"], "all"]
        if era and r["season"] >= 2023:
            keys = [f"{r['role']}@impact", "all@impact"]
        for k in keys:
            a = acc.setdefault(k, [0.0, 0.0])
            a[0] += r["m"]
            a[1] += r["m"] * r[disc]
    return {k: s / n for k, (n, s) in acc.items() if n > 0}


def _role_key(role: str, season: int, era: bool, mu: dict) -> str:
    if era and season >= 2023 and f"{role}@impact" in mu:
        return f"{role}@impact"
    return role


def _pred_cred(rows, priors, disc, k0, ko, mu, era, other) -> np.ndarray:
    out = np.empty(len(rows))
    for i, r in enumerate(rows):
        p = priors[r["season"]].get(r["cid"], pt.EMPTY_PRIOR)
        rk = _role_key(r["role"], r["season"], era, mu)
        m = pt.BallsModel(disc, k0, ko if other else 0.0, 0.0, {rk: mu.get(rk, mu["all"]),
                                                                  "all": mu["all"]})  # fmt: skip
        out[i] = m.predict(pt._disc(p, DISC[disc]), rk)
    return out


def _wmae(pred: np.ndarray, rows: list[dict], disc: str, T: float) -> float:
    y = np.array([r[disc] for r in rows])
    w = np.array([r["m"] for r in rows], dtype=float)
    return float(np.sum(w * np.abs(pred - y)) / w.sum() * T)


def _wmse(pred, rows, disc) -> float:
    y = np.array([r[disc] for r in rows])
    w = np.array([r["m"] for r in rows], dtype=float)
    return float(np.sum(w * (pred - y) ** 2) / w.sum())


def _balls_rows(u, roles, seasons) -> list[dict]:
    t = balls_targets(u).filter(pl.col("season").is_in(list(seasons)))
    return [{"season": s, "cid": cid, "m": m, "sf": sf, "sb": sb, "role": roles.get(cid, "batter")}
            for s, cid, m, sf, sb in t.iter_rows()]  # fmt: skip


def fit_balls(rows, priors_by_decay, disc, spec) -> dict:
    """Grid-fit a candidate on `rows` (weighted MSE of the share). Returns its parameters."""
    if spec["kind"] in ("role", "last"):
        return {"mu": _mu(rows, disc, False)}
    best = None
    for d, priors in priors_by_decay.items():
        mu = _mu(rows, disc, spec["era"])
        for k0 in K0_GRID:
            for ko in KO_GRID if spec["other"] else (0.0,):
                e = _wmse(_pred_cred(rows, priors, disc, k0, ko, mu, spec["era"], spec["other"]),
                          rows, disc)  # fmt: skip
                if best is None or e < best[0]:
                    best = (e, {"decay": d, "k0": k0, "k_o": ko, "mu": mu})
    return best[1]


def predict_balls(rows, priors_by_decay, last, disc, spec, par) -> np.ndarray:
    if spec["kind"] == "role":
        return np.array([par["mu"].get(r["role"], par["mu"]["all"]) for r in rows])
    if spec["kind"] == "last":
        j = 0 if disc == "sf" else 1
        return np.array([
            last[(r["season"], r["cid"])][j] if (r["season"], r["cid"]) in last
            else par["mu"].get(r["role"], par["mu"]["all"]) for r in rows])  # fmt: skip
    pri = priors_by_decay[par["decay"]]
    return _pred_cred(rows, pri, disc, par["k0"], par["k_o"], par["mu"], spec["era"], spec["other"])


@app.command()
def usage(refresh: bool = typer.Option(True, "--refresh/--cached")) -> None:
    """Build the player-match usage cache for every auction-pool league."""
    u = pt.usage_all(bayesian.DEFAULT_DB_PATH, POOL_COLS, refresh=refresh)
    typer.echo(f"{u.height} player-matches, {u['league'].n_unique()} leagues")


def _balls_select(u, roles, starts, report: dict) -> tuple[str, dict]:
    seasons = list(range(BALLS_FIRST, 2027))
    pri = {d: _priors(u, starts, seasons, d) for d in DECAY_GRID}
    last = _last_share(u, seasons)
    rows = _balls_rows(u, roles, seasons)
    T = {s: pt.team_balls(u, starts[s]) for s in seasons}
    tr = [r for r in rows if r["season"] < VALID]
    va = [r for r in rows if r["season"] == VALID]
    sel: dict = {}
    for name, spec in BALLS_CANDIDATES.items():
        sel[name] = {}
        for disc in ("sf", "sb"):
            par = fit_balls(tr, pri, disc, spec)
            p = predict_balls(va, pri, last, disc, spec, par)
            sel[name][disc] = {"mae_balls": round(_wmae(p, va, disc, T[VALID]), 3),
                               **{k: v for k, v in par.items() if k != "mu"}}  # fmt: skip
        typer.echo(f"{name[:60]:60} faced MAE {sel[name]['sf']['mae_balls']:.2f}  "
                   f"bowled MAE {sel[name]['sb']['mae_balls']:.2f}")  # fmt: skip
    cands = [n for n, s in BALLS_CANDIDATES.items() if s["kind"] == "cred"]
    chosen = min(cands, key=lambda n: sel[n]["sf"]["mae_balls"] + sel[n]["sb"]["mae_balls"])
    report["selection"] = sel
    report["chosen"] = chosen
    typer.echo(f"chosen: {chosen}")
    # the test, once: the chosen and the references refitted on seasons up to 2024
    tr2 = [r for r in rows if r["season"] <= VALID]
    te = [r for r in rows if r["season"] in TEST]
    test: dict = {}
    for name in (chosen, *[n for n, s in BALLS_CANDIDATES.items() if s["kind"] != "cred"]):
        spec = BALLS_CANDIDATES[name]
        test[name] = {}
        for disc in ("sf", "sb"):
            par = fit_balls(tr2, pri, disc, spec)
            p = predict_balls(te, pri, last, disc, spec, par)
            per = {}
            for s in TEST:
                idx = [i for i, r in enumerate(te) if r["season"] == s]
                per[str(s)] = round(_wmae(p[idx], [te[i] for i in idx], disc, T[s]), 3)
            test[name][disc] = {"mae_balls": round(
                sum(_wmae(p[[i for i, r in enumerate(te) if r["season"] == s]],
                          [r for r in te if r["season"] == s], disc, T[s])
                    * sum(r["m"] for r in te if r["season"] == s) for s in TEST)
                / sum(r["m"] for r in te), 3), "by_season": per}  # fmt: skip
        typer.echo(f"TEST {name[:55]:55} faced {test[name]['sf']['mae_balls']:.2f}  "
                   f"bowled {test[name]['sb']['mae_balls']:.2f}")  # fmt: skip
    report["test"] = test
    # realism on whole XIs: per real team-match in the test seasons, the XI's predicted balls
    # against the side's real balls (the chosen model, fitted up to 2024)
    spec = BALLS_CANDIDATES[chosen]
    pars = {d: fit_balls(tr2, pri, d, spec) for d in ("sf", "sb")}
    report["xi_check"] = _xi_check(u, roles, pri, pars, spec, starts, T)
    return chosen, pars


def _xi_check(u, roles, pri, pars, spec, starts, T) -> dict:
    """Σ over a real XI of the predicted balls faced (bowled), against the side's real balls, per
    team-match of the test seasons: mean ratio and mean absolute difference."""
    out = {}
    for s in TEST:
        i = u.filter((pl.col("league") == "ipl") & (pl.col("season") == s))
        sf, sb = {}, {}
        for disc, store in (("sf", sf), ("sb", sb)):
            par = pars[disc]
            mu = par["mu"]
            for cid in i["cid"].unique().to_list():
                role = roles.get(cid, "batter")
                rk = _role_key(role, s, spec["era"], mu)
                p = pri[par["decay"]][s].get(cid, pt.EMPTY_PRIOR)
                m = pt.BallsModel(disc, par["k0"], par["k_o"], 0.0,
                                  {rk: mu.get(rk, mu["all"]), "all": mu["all"]})  # fmt: skip
                store[cid] = m.predict(pt._disc(p, DISC[disc]), rk) * T[s]
        g = i.group_by("match_id", "team").agg(
            pl.col("cid"), pl.col("team_faced").first(), pl.col("team_bowled").first()
        )
        rf, rb, df_, db_ = [], [], [], []
        for _mid, _t, cids, tf, tb in g.iter_rows():
            pf = sum(sf[c] for c in cids)
            pb = sum(sb[c] for c in cids)
            if tf:
                rf.append(pf / tf)
                df_.append(abs(pf - tf))
            if tb:
                rb.append(pb / tb)
                db_.append(abs(pb - tb))
        out[str(s)] = {"team_matches": len(rf),
                       "faced_ratio": round(float(np.mean(rf)), 3),
                       "faced_mad": round(float(np.mean(df_)), 2),
                       "bowled_ratio": round(float(np.mean(rb)), 3),
                       "bowled_mad": round(float(np.mean(db_)), 2)}  # fmt: skip
    return out


@app.command()
def balls() -> None:
    """Select the expected-balls model on 2024 (fitted to 2023), test it once on 2025-26."""
    u = _u()
    roles = _roles()
    starts = season_starts(u)
    rep: dict = _read()
    r: dict = {"protocol": "candidates fitted on IPL seasons 2012-2023, chosen on 2024 by the "
               "matches-weighted MAE in balls per match (faced + bowled); the chosen one refitted "
               "on 2012-2024 and scored once on 2025-2026"}  # fmt: skip
    _balls_select(u, roles, starts, r)
    rep["balls"] = r
    _write(rep)


# ---- as-of contributions (the P(plays) rows, the price and Keep backtests) ----------------------------


def asof_roles(season: int, date: str) -> dict[str, dict[str, tuple[float, float]]]:
    """cid → {"batter": (value, sd), "bowler": (value, sd)} as of an auction, each role blended
    across leagues exactly as the auction pool blends it (every league translated onto the IPL scale
    and combined with the IPL rating by precision: cricdex.scout.translation.blend). The protocol
    runs (`play`, `free`, `asof-contrib`) use the translation fitted on seasons ≤ 2024, so the 2025-26
    test sees no later outcome; `ship` uses the shipped one (`_WHICH`)."""
    own, other = ipm.asof_sources(season, date)
    tm = translation.load_model()
    out: dict[str, dict[str, tuple[float, float]]] = {}
    shares: dict[tuple[str, str], dict[str, float]] = {}
    for key in set(own) | set(other):
        cid, role = key
        if role not in translation.ROLES:
            continue
        o = own.get(key)
        val, vsd, sh = translation.blend(role, (o[0], o[1]) if o else None, other.get(key, {}), tm,
                                         _WHICH["which"])  # fmt: skip
        out.setdefault(cid, {})[role] = (val, vsd)
        shares[key] = sh
    return _time_aware(out, shares, season, date)


def _time_aware(vals: dict, shares: dict, season: int, date: str) -> dict:
    """The as-of values moved from his career level to his level in `season` (scout/ratings/drift.py,
    METHODOLOGY §4b): the protocol runs use the time-aware model fitted on seasons up to 2024
    (`model_le2024`), `ship` the shipped one. Unchanged when config/rating_drift.json is missing."""
    from cricdex.scout.ratings import drift

    m = drift.load_model(which="model" if _WHICH["which"] == "roles" else "model_le2024")
    if m is None:
        return vals
    if "obs" not in _DRIFT:
        pm = master.load()
        _DRIFT["dob"] = {c: str(r["dob"])[:10] for c, r in pm.items()
                         if isinstance(r, dict) and r.get("dob")}  # fmt: skip
        _DRIFT["cat"] = {c: r.get("bowling_category") for c, r in pm.items() if isinstance(r, dict)}
        _DRIFT["obs"] = drift.season_obs(bayesian.DEFAULT_DB_PATH, POOL_COLS, [date])
    o = _DRIFT["obs"]
    if o.filter(pl.col("cut") == date).height == 0 and date[5:] != "01-01":
        o = _DRIFT["obs"] = drift.season_obs(bayesian.DEFAULT_DB_PATH, POOL_COLS, [date])
    out, _ = drift.adjust(vals, shares, o, date, season, _DRIFT["dob"], _DRIFT["cat"], m,
                          _WHICH["which"])  # fmt: skip
    # how far each value is trusted (scout/ratings/shrink.py, METHODOLOGY §4c): shrunk toward its
    # role's mean by the fitted calibration (`model_le2024` in the protocol runs)
    from cricdex.scout.ratings import shrink

    sm = shrink.load_model(which="model" if _WHICH["which"] == "roles" else "model_le2024")
    out, _ = shrink.adjust(out, shares, shrink.years_since(o, date), sm)
    return out


_DRIFT: dict = {}


# which fitted translation the as-of values use (`ship` switches to the shipped one)
_WHICH = {"which": "roles_le2024"}


def balls_models(pars: dict, spec_name: str) -> dict[str, pt.BallsModel]:
    """The fitted expected-balls models ("bat", "bowl") from a candidate's parameters."""
    spec = BALLS_CANDIDATES[spec_name]
    out = {}
    for disc, key in (("sf", "bat"), ("sb", "bowl")):
        p = pars[disc]
        mu = dict(p["mu"])
        if spec.get("era"):  # the shipped / forward model predicts impact-era seasons
            for k in list(mu):
                if k.endswith("@impact"):
                    mu[k.split("@")[0]] = mu[k]
        out[key] = pt.BallsModel(key, p["k0"], p["k_o"], p["decay"],
                                 {k: v for k, v in mu.items() if "@" not in k})  # fmt: skip
    return out


def minbuy_pairs(hist: dict, u: pl.DataFrame, season: int, bm: dict[str, pt.BallsModel],
                 T: float) -> list[dict]:  # fmt: skip
    """The players bought at auction `season`'s lowest price (no franchise bid more: freely
    available talent), each with his ratings at the auction and his usage before it: {season, cid,
    pos (usual batting position, his role's typical one if none), bat (batting value or None),
    bowled (expected balls bowled a match), bowl (bowling value or None)}. `bm` / `T`: the
    expected-balls models and balls per innings fitted before that auction."""
    a = hist["auctions"].get(str(season))
    if not a:
        return []
    prices = [float(r["price_cr"]) for r in hist["lots"]
              if r["season"] == season and r.get("sold") and r.get("price_cr")]  # fmt: skip
    if not prices:
        return []
    floor = min(prices)
    date = a["date"]
    buys = sorted({r["cricsheet_id"] for r in hist["lots"]
                   if r["season"] == season and r.get("sold") and r.get("cricsheet_id")
                   and r.get("price_cr") and float(r["price_cr"]) <= floor + 1e-9})  # fmt: skip
    if not buys:
        return []
    vals = _asof(season, date)
    us_all = pt.expected_usage(u, date, buys, bm, T, _roles())
    out = []
    for cid in buys:
        v = vals.get(cid, {})
        us = us_all[cid]
        out.append({"season": season, "cid": cid, "pos": us["pos"],
                    "bat": v["batter"][0] if "batter" in v else None,
                    "bowled": us["bowled"],
                    "bowl": v["bowler"][0] if "bowler" in v else None})  # fmt: skip
    return out


# The replacement-curve candidates (ROADMAP I17a), declared 2026-10-26 before any test number. The
# pairs are (usual batting position, batting value) and (expected balls bowled a match, bowling value)
# of the minimum-price buys; R0 is the slot-group means shipped until then.
REPL_CANDIDATES = {
    "R0 slot groups (reference)": {"method": "groups"},
    "R1 linear": {"method": "linear"},
    "R2 isotonic (monotone)": {"method": "isotonic"},
    "R3 kernel": {"method": "kernel"},
}
# The impact player (2023-): declared 2026-10-27 (an analyst's review), before any of their numbers.
# The replacement level is fitted on minimum-price buys pooled over 2012 onward; with 12 players a side
# a match since 2023, the next man up may differ. Each declared candidate (R0-R3) is also fitted with
# the buys of the auctions before 2023 weighted by `era_w` (1 = pooled; 0 = impact era only). Because
# the question is the impact era, these are scored on the impact-era validation auctions (2023, 2024)
# only, against the same smoothers pooled (the `era_w` = 1 rows of that table).
REPL_ERA_FIRST = 2023
REPL_ERA_W = (1.0, 0.5, 0.25, 0.0)
REPL_ERA_VALID = (2023, 2024)
REPL_BANDWIDTH = {"bat": (0.5, 1.0, 1.5, 2.0, 3.0), "bowl": (2.0, 4.0, 6.0, 9.0, 12.0)}
REPL_VALID = tuple(range(2018, VALID + 1))  # each predicted from the auctions before it
# batting: a lower position has the weaker replacement; bowling: a heavier load the better one
REPL_INCREASING = {"bat": False, "bowl": True}


def _pairs_xy(pairs: list[dict], disc: str) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for p in pairs:
        y = p[disc]
        if y is None or not math.isfinite(y):
            continue
        if disc == "bat":
            x = pt.NO_POSITION if p["pos"] is None else float(p["pos"])
        else:
            x = float(p["bowled"])
        xs.append(x)
        ys.append(float(y))
    return xs, ys


def _group_curve(pairs: list[dict], disc: str) -> dict:
    """R0: the slot-group (bowling-group) means, the form shipped until 2026-10-26."""
    acc: dict[str, list[float]] = {}
    for p in pairs:
        y = p[disc]
        if y is None or not math.isfinite(y):
            continue
        if disc == "bat":
            g = pt.slot_group(p["pos"])
        else:
            g = "frontline" if p["bowled"] >= pt.FRONTLINE_BALLS else "part_time"
        a = acc.setdefault(g, [0.0, 0.0])
        a[0] += 1
        a[1] += y
    return {g: round(s / n, 3) for g, (n, s) in acc.items()}


def _pair_weights(pairs: list[dict], disc: str, era_w: float) -> list[float]:
    """Each usable pair's weight: 1 for an impact-era auction (REPL_ERA_FIRST on), `era_w` before."""
    return [1.0 if p["season"] >= REPL_ERA_FIRST else era_w for p in pairs
            if p[disc] is not None and math.isfinite(p[disc])]  # fmt: skip


def fit_replacement(pairs: list[dict], spec: dict) -> dict:
    """{"bat": curve or groups, "bowl": ..., "n": {"bat", "bowl"}, "method": ...} from minimum-price
    buys' pairs with a candidate spec ({"method", "h": {"bat", "bowl"}} for the kernel, `era_w`: the
    weight of a pre-2023 buy, 1 when absent)."""
    out: dict = {"method": spec["method"], "n": {}}
    era_w = spec.get("era_w")
    if era_w is not None:
        out["era_w"] = era_w
    for disc in ("bat", "bowl"):
        xs, ys = _pairs_xy(pairs, disc)
        out["n"][disc] = len(xs)
        if spec["method"] == "groups":
            out[disc] = _group_curve(pairs, disc)
        else:
            knots = pt.BAT_KNOTS if disc == "bat" else pt.BOWL_KNOTS
            h = (spec.get("h") or {}).get(disc)
            ws = None if era_w is None else _pair_weights(pairs, disc, era_w)
            out[disc] = pt.fit_curve(xs, ys, spec["method"], knots, REPL_INCREASING[disc], h, ws)
            if h:
                out[disc]["h"] = h
    return out


def _repl_err(repl: dict, pairs: list[dict], disc: str) -> list[float]:
    """Squared errors of the replacement level against held-out minimum-price buys' values."""
    out = []
    for p in pairs:
        y = p[disc]
        if y is None or not math.isfinite(y):
            continue
        r = pt.repl_bat(repl, p["pos"]) if disc == "bat" else pt.repl_bowl(repl, p["bowled"])
        out.append((y - r) ** 2)
    return out


CACHE_PAIRS = DATA_DIR / "metrics" / ".playing_time" / "minbuy_pairs.pkl"


def all_minbuy_pairs(hist: dict, u: pl.DataFrame, last: int) -> dict[int, list[dict]]:
    """season → minimum-price buys' pairs, auctions REPL_FIRST ... last, each with the expected-balls
    models fitted before it (the walk-forward ones cached by `play` from 2018; the 2018 ones for the
    earlier auctions, fitted on 2012-2017: a small look-ahead in the shrinkage constants only, as in
    `asof-contrib`). Cached per translation (`_WHICH`)."""
    import pickle

    cache: dict = pickle.loads(CACHE_PAIRS.read_bytes()) if CACHE_PAIRS.exists() else {}
    key = _WHICH["which"]
    got = cache.setdefault(key, {})
    balls = _balls_by_season(hist, u)
    for s in range(REPL_FIRST, last + 1):
        if s in got:
            continue
        b = balls[max(s, PLAY_SEASONS[0])] if max(s, PLAY_SEASONS[0]) in balls else None
        if b is None:
            continue
        got[s] = minbuy_pairs(hist, u, s, b["bm"], b["T"])
        CACHE_PAIRS.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PAIRS.write_bytes(pickle.dumps(cache))
        typer.echo(f"  min-price buys {s}: {len(got[s])}")
    return {s: v for s, v in got.items() if s <= last}


CACHE_BALLS = DATA_DIR / "metrics" / ".playing_time" / "walk_balls.pkl"


def _balls_by_season(hist: dict, u: pl.DataFrame) -> dict[int, dict]:
    """season → {"bm", "T"}: the expected-balls models and balls per innings fitted before each
    auction of PLAY_SEASONS (walk-forward), cached; seeded from `play`'s row cache when present."""
    import pickle

    cache: dict = pickle.loads(CACHE_BALLS.read_bytes()) if CACHE_BALLS.exists() else {}
    if not cache and CACHE_PLAY.exists():
        old = pickle.loads(CACHE_PLAY.read_bytes())
        cache = {s: {"bm": d["bm"], "T": d["T"]} for s, d in old.items()}
    missing = [s for s in PLAY_SEASONS if s not in cache]
    if missing:
        roles = _roles()
        starts = season_starts(u)
        chosen = (_read().get("balls") or {}).get("chosen")
        for s in missing:
            bm, T = walk_forward_balls(u, roles, starts, hist, s, chosen)
            cache[s] = {"bm": {k: v.to_json() for k, v in bm.items()}, "T": T}
    CACHE_BALLS.parent.mkdir(parents=True, exist_ok=True)
    CACHE_BALLS.write_bytes(pickle.dumps(cache))
    return {s: {"bm": {k: pt.BallsModel.from_json(v) for k, v in d["bm"].items()}, "T": d["T"]}
            for s, d in cache.items()}  # fmt: skip


def replacement_from_minbuys(hist: dict, u: pl.DataFrame, before: int) -> dict[str, dict]:
    """The replacement levels for auction `before`: the shipped curve (`_read()["replacement"]`'s
    chosen candidate; the slot groups if `repl` hasn't run) fitted on the minimum-price buys of
    auctions REPL_FIRST ... before - 1."""
    pairs = [p for s, ps in all_minbuy_pairs(hist, u, before - 1).items() if s < before for p in ps]
    rep = _read().get("replacement") or {}
    spec = rep.get("chosen_spec") or REPL_CANDIDATES["R0 slot groups (reference)"]
    return fit_mixed(pairs, spec)


@app.command()
def repl() -> None:
    """Replacement curves (ROADMAP I17a): each candidate fitted on the minimum-price buys of the
    auctions before each of 2018-2024 and scored on that auction's buys (validation, pooled); the
    best per discipline refitted on 2012-2024 and scored once on 2025 and 2026."""
    u = _u()
    hist = json.loads(ipm.HISTORY.read_text(encoding="utf-8"))
    pairs = all_minbuy_pairs(hist, u, max(TEST))
    specs: dict[str, dict] = {}
    for name, sp in REPL_CANDIDATES.items():
        if sp["method"] == "kernel":
            for hb, hw in zip(REPL_BANDWIDTH["bat"], REPL_BANDWIDTH["bowl"], strict=True):
                specs[f"{name} (h bat {hb}, bowl {hw})"] = {**sp, "h": {"bat": hb, "bowl": hw}}
        else:
            specs[name] = sp
    sel: dict[str, dict] = {}
    for label, sp in specs.items():
        errs: dict[str, list[float]] = {"bat": [], "bowl": []}
        for s in REPL_VALID:
            train = [p for y, ps in pairs.items() if y < s for p in ps]
            r = fit_replacement(train, sp)
            for disc in errs:
                errs[disc] += _repl_err(r, pairs.get(s, []), disc)
        sel[label] = {d: {"mse": round(float(np.mean(e)), 2), "n": len(e)} for d, e in errs.items()}
        typer.echo(f"{label[:52]:52} bat MSE {sel[label]['bat']['mse']:8.1f} (n {len(errs['bat'])})"
                   f"  bowl MSE {sel[label]['bowl']['mse']:7.1f} (n {len(errs['bowl'])})")  # fmt: skip
    chosen: dict[str, str] = {}
    for disc in ("bat", "bowl"):
        chosen[disc] = min(sel, key=lambda k, d=disc: (sel[k][d]["mse"], k))
    typer.echo(f"chosen: bat {chosen['bat']}; bowl {chosen['bowl']}")
    # the impact era (declared 2026-10-27): the chosen smoother per discipline with the pre-2023 buys
    # down-weighted, scored on the impact-era validation auctions only; era_w = 1 is the pooled fit
    era_sel: dict[str, dict] = {}
    for disc in ("bat", "bowl"):
        for w in REPL_ERA_W:
            sp = {**specs[chosen[disc]], "era_w": w}
            e: list[float] = []
            for s in REPL_ERA_VALID:
                train = [p for y, ps in pairs.items() if y < s for p in ps]
                e += _repl_err(fit_replacement(train, sp), pairs.get(s, []), disc)
            era_sel.setdefault(disc, {})[str(w)] = {"mse": round(float(np.mean(e)), 2), "n": len(e)}
            typer.echo(f"ERA {disc} {chosen[disc][:40]:40} pre-2023 weight {w:4}: MSE "
                       f"{era_sel[disc][str(w)]['mse']:8.1f} (n {len(e)})")  # fmt: skip
    era_w = {d: float(min(era_sel[d], key=lambda w, d=d: (era_sel[d][w]["mse"], -float(w))))
             for d in ("bat", "bowl")}  # fmt: skip
    typer.echo(f"era weights chosen: {era_w}")
    for d in ("bat", "bowl"):
        if era_w[d] != 1.0:
            specs[chosen[d]] = {**specs[chosen[d]], "era_w": era_w[d]}
    # the chosen spec per discipline (a kernel's own bandwidth for that discipline)
    spec_bat, spec_bowl = specs[chosen["bat"]], specs[chosen["bowl"]]
    chosen_spec = {"method": "mixed", "bat": spec_bat, "bowl": spec_bowl}
    train = [p for y, ps in pairs.items() if y <= VALID for p in ps]
    test: dict[str, dict] = {}
    for label in dict.fromkeys([chosen["bat"], chosen["bowl"], "R0 slot groups (reference)",
                                "R1 linear"]):  # fmt: skip
        r = fit_replacement(train, specs[label])
        test[label] = {}
        for s in TEST:
            test[label][str(s)] = {d: {"mse": round(float(np.mean(e)), 2), "n": len(e)}
                                   for d in ("bat", "bowl")
                                   if (e := _repl_err(r, pairs.get(s, []), d))}  # fmt: skip
        typer.echo(f"TEST {label[:52]:52} {json.dumps(test[label])}")
    rep = _read()
    rep["replacement"] = {
        "protocol": "candidates fitted on the minimum-price buys of the auctions before each of "
                    "2018-2024 and scored on that auction's (pooled squared error of the replacement "
                    "level against each buy's value at his position / bowling load); the best per "
                    "discipline refitted on 2012-2024 and scored once on the 2025 and 2026 buys",
        "selection": sel, "chosen": chosen, "chosen_spec": chosen_spec, "test": test,
        "era": {"protocol": "the chosen smoother per discipline, pre-2023 buys weighted by each of "
                            f"{list(REPL_ERA_W)}, fitted on the auctions before each of "
                            f"{list(REPL_ERA_VALID)} and scored on that auction's buys; the lowest "
                            "squared error wins (ties: the larger weight)",
                "selection": era_sel, "chosen": era_w},
        "curve_le2024": fit_mixed(train, chosen_spec),
        "pairs_by_season": {str(s): len(v) for s, v in sorted(pairs.items())},
    }  # fmt: skip
    _write(rep)


def fit_mixed(pairs: list[dict], spec: dict) -> dict:
    """fit_replacement with a per-discipline spec ({"method": "mixed", "bat": spec, "bowl": spec}) or
    one spec for both."""
    if spec.get("method") != "mixed":
        return fit_replacement(pairs, spec)
    b = fit_replacement(pairs, spec["bat"])
    w = fit_replacement(pairs, spec["bowl"])
    return {
        "method": f"bat {spec['bat']['method']}, bowl {spec['bowl']['method']}",
        "bat": b["bat"],
        "bowl": w["bowl"],
        "n": {"bat": b["n"]["bat"], "bowl": w["n"]["bowl"]},
    }


# ---- P(plays): the squads of every season with a complete retained list ------------------------------

_ASOF: dict = {}


def _asof(season: int, date: str) -> dict:
    if season not in _ASOF:
        _ASOF[season] = asof_roles(season, date)
    return _ASOF[season]


def walk_forward_balls(u, roles, starts, hist, s: int, chosen: str) -> tuple[dict, float]:
    """(expected-balls models, balls per innings) fitted on what was known before season `s`'s
    auction."""
    seasons = list(range(BALLS_FIRST, s))
    spec = BALLS_CANDIDATES[chosen]
    rows = _balls_rows(u, roles, seasons)
    pri = {d: _priors(u, starts, seasons, d) for d in DECAY_GRID}
    pars = {disc: fit_balls(rows, pri, disc, spec) for disc in ("sf", "sb")}
    bm = balls_models(pars, chosen)
    date = hist["auctions"][str(s)]["date"]
    return bm, pt.team_balls(u, date)


def walk_forward(u, roles, starts, hist, s: int, chosen: str) -> tuple[dict, float, dict]:
    """(expected-balls models, balls per innings, replacement levels) fitted on what was known
    before season `s`'s auction (the balls models from `_balls_by_season`'s cache when there)."""
    b = _balls_by_season(hist, u).get(s)
    if b is not None:
        bm, T = b["bm"], b["T"]
    else:
        bm, T = walk_forward_balls(u, roles, starts, hist, s, chosen)
    return bm, T, replacement_from_minbuys(hist, u, s)


def squads(hist: dict, s: int) -> dict[str, set[str]]:
    """team -> the cids it retained or bought for season `s`."""
    out: dict[str, set[str]] = {}
    for r in hist["retentions"]:
        if r["season"] == s and r["kind"] == "retained" and r.get("cricsheet_id"):
            out.setdefault(r["team"], set()).add(r["cricsheet_id"])
    for r in hist["lots"]:
        if r["season"] == s and r.get("sold") and r.get("cricsheet_id") and r.get("team"):
            out.setdefault(r["team"], set()).add(r["cricsheet_id"])
    return out


def squad_contribs(cids, vals, usage_, repl) -> dict[str, dict]:
    out = {}
    for cid in cids:
        v = vals.get(cid, {})
        us = usage_[cid]
        c, sd, parts = pt.contribution(v.get("batter"), v.get("bowler"), us["faced"], us["bowled"],
                                       us["pos"], repl)  # fmt: skip
        out[cid] = {"c": c, "sd": sd, **parts, **us}
    return out


def ipl_shares(u: pl.DataFrame) -> tuple[dict, dict, dict]:
    """((season, team code) -> matches, (season, code, cid) -> matches he played for it,
    (season, cid) -> his largest share of a side's matches that season)."""
    i = u.filter(pl.col("league") == "ipl").with_columns(
        pl.col("team").replace(IPL_TEAM_CODES_ALL).alias("code")
    )
    team_m = {(s, c): n for s, c, n in
              i.group_by("season", "code").agg(pl.col("match_id").n_unique()).iter_rows()}  # fmt: skip
    played = {(s, c, cid): n for s, c, cid, n in
              i.group_by("season", "code", "cid").agg(pl.len()).iter_rows()}  # fmt: skip
    share: dict[tuple[int, str], float] = {}
    for (s, c, cid), n in played.items():
        share[(s, cid)] = max(share.get((s, cid), 0.0), n / team_m[(s, c)])
    return team_m, played, share


def squad_rows(
    s: int,
    date: str,
    sq: dict[str, set[str]],
    in_prev: set[str],
    share_prev: dict,
    con: dict[str, dict],
    roles: dict,
    pm: dict,
    ipl_m: dict,
) -> list[dict]:
    """One row per squad player with his P(plays) inputs (playing_time.play_features keys)."""
    out = []
    for team, members in sorted(sq.items()):
        squad = []
        for cid in sorted(members):
            rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
            ctry = rec.get("country")
            role = roles.get(cid, "batter")
            squad.append({"cid": cid, "c": con[cid]["c"], "os": int(bool(ctry) and ctry != "IND"),
                          "k": int(role == "keeper"), "bowl": int(role in ("bowler", "all_rounder")),
                          "bat": int(role in ("batter", "keeper", "all_rounder"))})  # fmt: skip
        xi = pt.projected_xi(squad)
        for p in squad:
            cid = p["cid"]
            rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
            age = None
            if rec.get("dob"):
                try:
                    age = ipm._years(date, str(rec["dob"])[:10])
                except ValueError:
                    age = None
            x = xi[cid]
            out.append({
                "season": s, "team": team, "cid": cid, "name": rec.get("display_name") or cid,
                "contrib": con[cid]["c"], "contrib_sd": con[cid]["sd"],
                "faced": con[cid]["faced"], "bowled": con[cid]["bowled"],
                "in_xi": x["in_xi"], "margin": x["margin"], "rank": x["rank"],
                "overseas": bool(p["os"]), "os_rank": x["os_rank"],
                "ipl_matches": ipl_m.get(cid, 0), "age": age,
                "last_share": share_prev.get(cid, 0.0) if cid in in_prev else None,
                "keeper": bool(p["k"]), "captain": bool(captains.as_of(cid, s).get("captain_ipl_last")),
            })  # fmt: skip
    return out


def play_rows(u, roles, starts, hist, chosen: str, cache: Path) -> dict[int, dict]:
    """Every squad player of every season in PLAY_SEASONS with his P(plays) inputs as of the auction
    and the label (his share of his side's matches). Cached per season (resumable)."""
    import pickle

    done: dict = pickle.loads(cache.read_bytes()) if cache.exists() else {}
    pm = master.load()
    team_m, played, share = ipl_shares(u)
    i = u.filter(pl.col("league") == "ipl")
    for s in PLAY_SEASONS:
        if s in done:
            typer.echo(f"{s}: cached ({len(done[s]['rows'])} rows)")
            continue
        date = hist["auctions"][str(s)]["date"]
        bm, T, repl = walk_forward(u, roles, starts, hist, s, chosen)
        vals = _asof(s, date)
        sq = {t: m for t, m in squads(hist, s).items() if (s, t) in team_m}
        prev_sq = squads(hist, s - 1)
        in_prev = {cid for v in prev_sq.values() for cid in v} | {
            cid for (y, cid) in share if y == s - 1
        }
        share_prev = {cid: v for (y, cid), v in share.items() if y == s - 1}
        allc = sorted({c for v in sq.values() for c in v})
        us = pt.expected_usage(u, date, allc, bm, T, roles)
        con = squad_contribs(allc, vals, us, repl)
        ipl_m = dict(i.filter(pl.col("date") < date).group_by("cid").agg(pl.len()).iter_rows())
        rows = squad_rows(s, date, sq, in_prev, share_prev, con, roles, pm, ipl_m)
        for r in rows:
            n = played.get((s, r["team"], r["cid"]), 0)
            r["played"] = n
            r["team_m"] = team_m[(s, r["team"])]
            r["share"] = n / r["team_m"]
        done[s] = {"rows": rows, "T": T, "repl": repl,
                   "bm": {k: v.to_json() for k, v in bm.items()}}  # fmt: skip
        cache.write_bytes(pickle.dumps(done))
        typer.echo(f"{s}: {len(rows)} squad players, T {T:.1f}, replacement {repl['bat']} / "
                   f"{repl['bowl']}")  # fmt: skip
    return done


def _ll(p: np.ndarray, rows: list[dict]) -> float:
    """Binomial log loss per match (each squad player's matches played out of his side's)."""
    q = np.clip(p, 1e-6, 1 - 1e-6)
    k = np.array([r["played"] for r in rows], dtype=float)
    n = np.array([r["team_m"] for r in rows], dtype=float)
    return float(-np.sum(k * np.log(q) + (n - k) * np.log(1 - q)) / n.sum())


def _play_metrics(p: np.ndarray, rows: list[dict]) -> dict:
    from scipy.stats import spearmanr

    y = np.array([r["share"] for r in rows])
    w = np.array([r["team_m"] for r in rows], dtype=float)
    order = np.argsort(p)
    cal = [[round(float(p[b].mean()), 3), round(float(y[b].mean()), 3), int(len(b))]
           for b in np.array_split(order, 5) if len(b)]  # fmt: skip
    return {"n": len(rows), "log_loss": round(_ll(p, rows), 4),
            "brier_share": round(float(np.sum(w * (p - y) ** 2) / w.sum()), 4),
            "mae_share": round(float(np.sum(w * np.abs(p - y)) / w.sum()), 4),
            "spearman": round(float(spearmanr(p, y).statistic), 3),
            "calibration_fifths": cal}  # fmt: skip


def _fit_predict(train, test, feats, alpha):
    if not feats:
        k = sum(r["played"] for r in train)
        n = sum(r["team_m"] for r in train)
        return np.full(len(test), k / n), None
    m = pt.fit_play_model(train, feats, alpha)
    return np.array([m.prob(r["_f"]) for r in test]), m


def _all_play_rows(by_era: bool = False) -> list[dict]:
    """Every cached squad row with its features; with `by_era` the projected side (in_xi, margin) is
    recomputed at pt.xi_size(season) (12 from 2023) from the same contributions and roles."""
    import pickle

    data = pickle.loads((CACHE_PLAY).read_bytes())
    rows = [dict(r) for s in PLAY_SEASONS for r in data[s]["rows"]]
    if by_era:
        roles = _roles()
        teams: dict[tuple[int, str], list[dict]] = {}
        for r in rows:
            teams.setdefault((r["season"], r["team"]), []).append(r)
        for (s, _t), rs in teams.items():
            squad = [pt.squad_member(r["cid"], r["contrib"], roles.get(r["cid"], "batter"),
                                     r["overseas"]) for r in rs]  # fmt: skip
            xi = pt.projected_xi(squad, pt.xi_size(s))
            for r in rs:
                x = xi[r["cid"]]
                r["in_xi"], r["margin"], r["rank"], r["os_rank"] = (
                    x["in_xi"], x["margin"], x["rank"], x["os_rank"])  # fmt: skip
    for r in rows:
        r["_f"] = pt.play_features(r)
    return rows


CACHE_PLAY = DATA_DIR / "metrics" / ".playing_time" / "play_rows.pkl"


@app.command()
def play() -> None:
    """Build the squad rows, choose P(plays) on 2024 (fitted to 2023), test it once on 2025-26."""
    u = _u()
    roles = _roles()
    starts = season_starts(u)
    hist = json.loads(ipm.HISTORY.read_text(encoding="utf-8"))
    rep = _read()
    chosen_balls = (rep.get("balls") or {}).get("chosen")
    if not chosen_balls:
        raise typer.BadParameter("run `balls` first")
    CACHE_PLAY.parent.mkdir(parents=True, exist_ok=True)
    data = play_rows(u, roles, starts, hist, chosen_balls, CACHE_PLAY)
    by_rows = {False: _all_play_rows(False), True: _all_play_rows(True)}
    sel = {}
    best = None
    for name, feats in PLAY_CANDIDATES.items():
        rows = by_rows[name in PLAY_XI_BY_ERA]
        tr = [r for r in rows if r["season"] < VALID]
        va = [r for r in rows if r["season"] == VALID]
        for alpha in PLAY_ALPHAS if feats else (None,):
            p, _ = _fit_predict(tr, va, feats, alpha)
            m = _play_metrics(p, va)
            label = name if alpha is None else f"{name} (alpha={alpha})"
            sel[label] = m
            typer.echo(f"{label[:70]:70} LL {m['log_loss']:.4f} Brier {m['brier_share']:.4f} "
                       f"MAE {m['mae_share']:.3f} rho {m['spearman']:.3f}")  # fmt: skip
            if feats and (best is None or m["log_loss"] < best[0]):
                best = (m["log_loss"], name, alpha)
    _, chosen, alpha = best
    typer.echo(f"chosen: {chosen} (alpha={alpha})")
    by_era = chosen in PLAY_XI_BY_ERA
    rows = by_rows[by_era]
    tr2 = [r for r in rows if r["season"] <= VALID]
    te = [r for r in rows if r["season"] in TEST]
    test = {}
    for name in dict.fromkeys([chosen, "P0 base rate (reference)", "P1 rank in the squad"]):
        a = alpha if name == chosen else (None if name.startswith("P0") else 1.0)
        p, _ = _fit_predict(tr2, te, PLAY_CANDIDATES[name], a)
        test[name] = {"pooled": _play_metrics(p, te)}
        for s in TEST:
            idx = [i for i, r in enumerate(te) if r["season"] == s]
            test[name][str(s)] = _play_metrics(p[idx], [te[i] for i in idx])
        brief = {k: v for k, v in test[name]["pooled"].items() if k != "calibration_fifths"}
        typer.echo(f"TEST {name[:60]:60} {json.dumps(brief)}")
    _, m_te = _fit_predict(tr2, te, PLAY_CANDIDATES[chosen], alpha)
    if m_te:
        m_te.xi_by_era = by_era
    p_te, _ = _fit_predict(tr2, te, PLAY_CANDIDATES[chosen], alpha)
    rep["play"] = {
        "protocol": "candidates fitted on the squads of 2018-2023, chosen on 2024 by the binomial "
                    "log loss per match; the chosen one refitted on 2018-2024 and scored once on "
                    "the 2025 and 2026 squads",
        "selection": sel, "chosen": chosen, "alpha": alpha, "xi_by_era": by_era, "test": test,
        "test_model": m_te.to_json() if m_te else None,
        "test_rows": [{"season": r["season"], "team": r["team"], "name": r["name"],
                       "p": round(float(q), 3), "share": round(r["share"], 3),
                       "contrib": round(r["contrib"], 2), "in_xi": r["in_xi"]}
                      for r, q in zip(te, p_te, strict=True)],
        "replacement_by_season": {str(s): data[s]["repl"] for s in PLAY_SEASONS},
        "T_by_season": {str(s): round(data[s]["T"], 2) for s in PLAY_SEASONS},
    }  # fmt: skip
    _write(rep)


def _read() -> dict:
    return json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}


def _write(rep: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    typer.echo(f"wrote {OUT}")


# ---- P(plays) of a free agent: every past auction pool ------------------------------------------------

FA_CANDIDATES = {
    "F0 base rate (reference)": (),
    "F1 contribution and its distance to a squad's XI line": ("contrib", "margin"),
    "F2 F1 + IPL experience, years since his last IPL match, age": (
        "contrib", "margin", "ipl_exp", "never_ipl", "gap", "age", "age_gt32"),
    "F3 F2 + last season's share, overseas, keeper, captain, impact era": pt.FA_FEATURES_ALL,
}  # fmt: skip
CACHE_FA = DATA_DIR / "metrics" / ".playing_time" / "fa_rows.pkl"
POOL_RECENCY_DAYS = 1100  # export_site.AUCTION_RECENCY_DAYS


def fa_rows(u, roles, hist, play_data: dict, cache: Path) -> dict[int, list[dict]]:
    """Every free agent of every auction pool in PLAY_SEASONS (rated in a pool league as of the
    auction, a match in a pool league in the POOL_RECENCY_DAYS before it, a nationality the IPL
    auction admits, not retained), his inputs as of the auction and the label (his share of a side's
    matches that season, 0 if he didn't play). The expected-balls models, balls per innings and
    replacement levels are the walk-forward ones of `play_rows`. Cached per season."""
    import datetime as _dt
    import pickle

    from cricdex import leagues as _lg

    eligible = _lg.auction_target().auction_eligible
    done: dict = pickle.loads(cache.read_bytes()) if cache.exists() else {}
    pm = master.load()
    team_m, _played, share = ipl_shares(u)
    i = u.filter(pl.col("league") == "ipl")
    for s in PLAY_SEASONS:
        if s in done:
            typer.echo(f"{s}: cached ({len(done[s])} free agents)")
            continue
        date = hist["auctions"][str(s)]["date"]
        d = play_data[s]
        bm = {k: pt.BallsModel.from_json(v) for k, v in d["bm"].items()}
        T, repl = d["T"], d["repl"]
        vals = _asof(s, date)
        lo = (_dt.date.fromisoformat(date) - _dt.timedelta(days=POOL_RECENCY_DAYS)).isoformat()
        active = set(
            u.filter((pl.col("date") < date) & (pl.col("date") >= lo))["cid"].unique().to_list()
        )
        retained = {r["cricsheet_id"] for r in hist["retentions"]
                    if r["season"] == s and r["kind"] == "retained" and r.get("cricsheet_id")}  # fmt: skip

        def country(cid: str) -> str | None:
            rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
            return rec.get("country")

        pop = sorted(c for c in vals if c in active and c not in retained and eligible(country(c)))
        prev_sq = {t: m for t, m in squads(hist, s - 1).items() if (s - 1, t) in team_m}
        need = sorted(set(pop) | {c for m in prev_sq.values() for c in m})
        us = pt.expected_usage(u, date, need, bm, T, roles)
        con = squad_contribs(need, vals, us, repl)
        lines, lines_era = [], []
        for _t, members in prev_sq.items():
            sq = [pt.squad_member(c, con[c]["c"], roles.get(c, "batter"),
                                  bool(country(c)) and country(c) != "IND") for c in members]  # fmt: skip
            lines.append(pt.xi_line(sq))
            lines_era.append(pt.xi_line(sq, pt.xi_size(s)))
        line = float(np.median(lines)) if lines else 0.0
        line_era = float(np.median(lines_era)) if lines_era else 0.0
        before = i.filter(pl.col("date") < date)
        ipl_m = dict(before.group_by("cid").agg(pl.len()).iter_rows())
        last_d = dict(before.group_by("cid").agg(pl.col("date").max()).iter_rows())
        mean_tm = float(np.mean([n for (y, _t), n in team_m.items() if y == s]))
        out = []
        for cid in pop:
            rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
            age = None
            if rec.get("dob"):
                try:
                    age = ipm._years(date, str(rec["dob"])[:10])
                except ValueError:
                    age = None
            sh = share.get((s, cid), 0.0)
            # the side's matches (his, if he played; else the season's mean) weight the row
            tm = next(
                (n for (y, t), n in team_m.items() if y == s and (s, t, cid) in _played), mean_tm
            )
            out.append({
                "season": s, "cid": cid, "name": rec.get("display_name") or cid,
                "contrib": con[cid]["c"], "margin": con[cid]["c"] - line,
                "margin_era": con[cid]["c"] - line_era,
                "ipl_matches": ipl_m.get(cid, 0),
                "gap": ipm._years(date, last_d[cid]) if cid in last_d else None,
                "age": age, "last_share": share.get((s - 1, cid)),
                "overseas": bool(country(cid)) and country(cid) != "IND",
                "keeper": roles.get(cid) == "keeper",
                "captain": bool(captains.as_of(cid, s).get("captain_ipl_last")),
                "share": sh, "team_m": tm, "played": round(sh * tm),
            })  # fmt: skip
        done[s] = out
        cache.write_bytes(pickle.dumps(done))
        n_play = sum(1 for r in out if r["share"] > 0)
        typer.echo(f"{s}: {len(out)} free agents, {n_play} played, line {line:.2f}")
    return done


@app.command()
def free() -> None:
    """Free agents' P(plays): rows, choose on 2024 (fitted to 2023), test once on 2025-26."""
    import pickle

    u = _u()
    roles = _roles()
    hist = json.loads(ipm.HISTORY.read_text(encoding="utf-8"))
    play_data = pickle.loads(CACHE_PLAY.read_bytes())
    data = fa_rows(u, roles, hist, play_data, CACHE_FA)
    # the side size of the chosen squad model (`play`): the XI line a free agent is measured against
    by_era = bool((_read().get("play") or {}).get("xi_by_era"))
    rows = [dict(r) for s in PLAY_SEASONS for r in data[s]]
    for r in rows:
        if by_era:
            r["margin"] = r["margin_era"]
        r["_f"] = pt.fa_features(r)
    tr = [r for r in rows if r["season"] < VALID]
    va = [r for r in rows if r["season"] == VALID]
    sel, best = {}, None
    for name, feats in FA_CANDIDATES.items():
        for alpha in PLAY_ALPHAS if feats else (None,):
            p, _ = _fit_predict(tr, va, feats, alpha)
            m = _play_metrics(p, va)
            label = name if alpha is None else f"{name} (alpha={alpha})"
            sel[label] = m
            typer.echo(f"{label[:72]:72} LL {m['log_loss']:.4f} Brier {m['brier_share']:.4f} "
                       f"MAE {m['mae_share']:.3f} rho {m['spearman']:.3f}")  # fmt: skip
            if feats and (best is None or m["log_loss"] < best[0]):
                best = (m["log_loss"], name, alpha)
    _, chosen, alpha = best
    typer.echo(f"chosen: {chosen} (alpha={alpha})")
    tr2 = [r for r in rows if r["season"] <= VALID]
    te = [r for r in rows if r["season"] in TEST]
    test = {}
    for name in dict.fromkeys([chosen, "F0 base rate (reference)",
                               "F1 contribution and its distance to a squad's XI line"]):  # fmt: skip
        a = alpha if name == chosen else (None if name.startswith("F0") else 1.0)
        p, _ = _fit_predict(tr2, te, FA_CANDIDATES[name], a)
        test[name] = {"pooled": _play_metrics(p, te)}
        for s in TEST:
            idx = [k for k, r in enumerate(te) if r["season"] == s]
            test[name][str(s)] = _play_metrics(p[idx], [te[k] for k in idx])
        brief = {k: v for k, v in test[name]["pooled"].items() if k != "calibration_fifths"}
        typer.echo(f"TEST {name[:60]:60} {json.dumps(brief)}")
    p_te, m_te = _fit_predict(tr2, te, FA_CANDIDATES[chosen], alpha)
    if m_te:
        m_te.xi_by_era = by_era
    rep = _read()
    rep["free_agent"] = {
        "protocol": "candidates fitted on the free agents of the 2018-2023 auction pools, chosen on "
                    "2024 by the binomial log loss per match; the chosen one refitted on 2018-2024 "
                    "and scored once on the 2025 and 2026 pools",
        "selection": sel, "chosen": chosen, "alpha": alpha, "test": test,
        "test_model": m_te.to_json() if m_te else None,
        "rows_by_season": {str(s): len(data[s]) for s in PLAY_SEASONS},
        "played_by_season": {str(s): sum(1 for r in data[s] if r["share"] > 0) for s in PLAY_SEASONS},
        "test_top": sorted(
            [{"season": r["season"], "name": r["name"], "p": round(float(q), 3),
              "share": round(r["share"], 3), "contrib": round(r["contrib"], 2),
              "age": r["age"] and round(r["age"], 1)}
             for r, q in zip(te, p_te, strict=True)], key=lambda x: -x["p"])[:80],
    }  # fmt: skip
    _write(rep)


# ---- P(plays) of an auction buy, given the squad that bought him (ROADMAP I18, 2026-10-27) -------------

# Candidates declared 2026-10-27 before any number. B0 is what Bid plan used for a lot until then (his
# free-agent chance, which includes the chance nobody buys him); the others are conditional on the
# buy: his rank in the buying squad (the squad model's inputs), fitted on all squad players (B1) or
# on the buys alone (B2), and B3 adds what he cost (teams play the players they paid for).
BUY_CANDIDATES = {
    "B0 the free-agent model (reference)": "fa",
    "B1 the squad model, all squad players": "squad",
    "B2 the squad model's inputs, fitted on auction buys": "buys",
    "B3 B2 + his price (ln of price ÷ purse)": "buys_price",
}
BUY_FEATURES = PLAY_CANDIDATES["P5 P4 + keeper, captain, impact era"]


def _xi_by_era() -> bool:
    """Whether the chosen squad model (`play`) projects a side of 12 in the impact-player era."""
    return bool((_read().get("play") or {}).get("xi_by_era"))


def _fa_era(rows: list[dict], by_era: bool) -> list[dict]:
    """Free-agent rows with their margin against the XI line of the chosen side size."""
    out = [dict(r) for r in rows]
    for r in out:
        if by_era:
            r["margin"] = r["margin_era"]
        r["_f"] = pt.fa_features(r)
    return out


def _buy_rows() -> list[dict]:
    """The squad rows (`play`) of players bought at that season's auction, with ln(price ÷ purse)."""
    hist = json.loads(ipm.HISTORY.read_text(encoding="utf-8"))
    price = {(r["season"], r["team"], r["cricsheet_id"]): float(r["price_cr"]) for r in hist["lots"]
             if r.get("sold") and r.get("cricsheet_id") and r.get("price_cr")}  # fmt: skip
    rows_all = _all_play_rows(_xi_by_era())
    out = []
    for s in PLAY_SEASONS:
        purse = float(hist["auctions"][str(s)]["purse_cr"])
        for r in (q for q in rows_all if q["season"] == s):
            p = price.get((s, r["team"], r["cid"]))
            if p is None:
                continue
            r = {**r, "price_share": math.log(p / purse)}
            r["_f"] = {**pt.play_features(r), "price_share": r["price_share"]}
            out.append(r)
    return out


@app.command()
def buy() -> None:
    """P(plays) for an auction buy in the squad that bought him: candidates fitted on 2018-2023, chosen
    on the 2024 buys, the chosen one refitted on 2018-2024 and scored once on the 2025-26 buys."""
    import pickle

    rep = _read()
    by_era = _xi_by_era()
    rows = _buy_rows()
    allsq = _all_play_rows(by_era)
    fa = pickle.loads(CACHE_FA.read_bytes())
    fa = {s: _fa_era(fa[s], by_era) for s in PLAY_SEASONS}
    fa_by = {(r["season"], r["cid"]): r for s in PLAY_SEASONS for r in fa[s]}
    fa_feats = FA_CANDIDATES[rep["free_agent"]["chosen"]]
    fa_alpha = rep["free_agent"]["alpha"]

    def predict(kind: str, train_until: int, test: list[dict], alpha) -> np.ndarray:
        if kind == "fa":
            tr = [r for s in PLAY_SEASONS if s <= train_until for r in fa[s]]
            for r in tr:
                r["_f"] = pt.fa_features(r)
            m = pt.fit_play_model(tr, fa_feats, fa_alpha)
            return np.array([m.prob(pt.fa_features(fa_by[(r["season"], r["cid"])])) for r in test])
        if kind == "squad":
            tr = [r for r in allsq if r["season"] <= train_until]
            m = pt.fit_play_model(tr, BUY_FEATURES, alpha)
        else:
            feats = BUY_FEATURES + (("price_share",) if kind == "buys_price" else ())
            tr = [r for r in rows if r["season"] <= train_until]
            m = pt.fit_play_model(tr, feats, alpha)
        return np.array([m.prob(r["_f"]) for r in test])

    # B0 needs his free-agent row: score every candidate on the buys that have one
    rows = [r for r in rows if (r["season"], r["cid"]) in fa_by]
    va = [r for r in rows if r["season"] == VALID]
    te = [r for r in rows if r["season"] in TEST]
    sel, best = {}, None
    for name, kind in BUY_CANDIDATES.items():
        for alpha in PLAY_ALPHAS if kind != "fa" else (None,):
            p = predict(kind, VALID - 1, va, alpha)
            m = _play_metrics(p, va)
            label = name if alpha is None else f"{name} (alpha={alpha})"
            sel[label] = m
            typer.echo(f"{label[:66]:66} LL {m['log_loss']:.4f} Brier {m['brier_share']:.4f} "
                       f"MAE {m['mae_share']:.3f} rho {m['spearman']:.3f} (n {m['n']})")  # fmt: skip
            if kind != "fa" and (best is None or m["log_loss"] < best[0]):
                best = (m["log_loss"], name, alpha)
    _, chosen, alpha = best
    typer.echo(f"chosen: {chosen} (alpha={alpha})")
    test = {}
    for name in dict.fromkeys([chosen, "B0 the free-agent model (reference)"]):
        kind = BUY_CANDIDATES[name]
        p = predict(kind, VALID, te, alpha if name == chosen else None)
        test[name] = {"pooled": _play_metrics(p, te)}
        for s in TEST:
            idx = [k for k, r in enumerate(te) if r["season"] == s]
            test[name][str(s)] = _play_metrics(p[idx], [te[k] for k in idx])
        brief = {k: v for k, v in test[name]["pooled"].items() if k != "calibration_fifths"}
        typer.echo(f"TEST {name[:60]:60} {json.dumps(brief)}")
    rep["buy"] = {
        "protocol": "candidates fitted on the squads / buys of 2018-2023, chosen on the 2024 buys by the "
                    "binomial log loss per match; the chosen one refitted on 2018-2024 and scored once on "
                    "the 2025 and 2026 buys",
        "selection": sel, "chosen": chosen, "alpha": alpha, "test": test,
        "rows_by_season": {str(s): sum(1 for r in rows if r["season"] == s) for s in PLAY_SEASONS},
    }  # fmt: skip
    _write(rep)


# ---- what a buy actually adds: the expected contribution calibrated on real buys (ROADMAP I18) ----------

# Candidates declared 2026-10-27 before any number. x = P(plays | bought) (the buy model, fitted on the
# auctions before) × his contribution a match as of the auction; y = what he then added a match of his
# side's season (his realised contribution × the share of matches he played; 0 if he barely played).
# A lot the market passes over is often one our numbers overrate (a veteran whose career rating hides
# his decline, a domestic batter whose translated rating is thin), so the expected value of a buy is
# calibrated on what real buys delivered, by age, years away from the IPL and no IPL at all.
VALUE_CANDIDATES = {
    "V0 x as it stands (reference)": (),
    "V1 one shrink factor": ("one",),
    "V2 shrink by age past 32, years away, never in the IPL": (
        "one",
        "age_gt32",
        "gap",
        "never_ipl",
    ),
}


def _value_feats(r: dict) -> dict[str, float]:
    age = r.get("age")
    a = (age - 28.0) if age is not None else 0.0
    gap = r.get("gap")
    return {"one": 1.0, "age_gt32": max(0.0, a - 4.0) / 5.0,
            "gap": 0.0 if gap is None else min(max(gap, 0.0), pt.GAP_MAX),
            "never_ipl": 1.0 if gap is None else 0.0}  # fmt: skip


def _value_rows() -> list[dict]:
    """Every real buy of 2019-2026 with x (walk-forward buy model × his as-of contribution), y and
    the shrink inputs (age, years since his last IPL match)."""
    import pickle

    import bidplan_backtest as bt

    rep = _read()
    kind = BUY_CANDIDATES[rep["buy"]["chosen"]]
    feats = BUY_FEATURES + (("price_share",) if kind == "buys_price" else ())
    rows = _buy_rows()
    fa = pickle.loads(CACHE_FA.read_bytes())
    gap = {(r["season"], r["cid"]): r["gap"] for s in PLAY_SEASONS for r in fa[s]}
    out = []
    for s in PLAY_SEASONS[1:]:
        m = pt.fit_play_model([r for r in rows if r["season"] < s], feats, rep["buy"]["alpha"])
        nv = bt._next_season_values(s)
        for r in rows:
            if r["season"] != s:
                continue
            p = m.prob(r["_f"])
            got = nv.get(r["cid"])
            y = got[0] * got[1][-1] if got else 0.0
            g = gap.get((s, r["cid"]), "missing")
            if g == "missing":  # not in that auction's free-agent pool: no gap known
                continue
            out.append({"season": s, "cid": r["cid"], "name": r["name"], "x": p * r["contrib"],
                        "y": y, "age": r.get("age"), "gap": g})  # fmt: skip
    return out


def _fit_value(rows: list[dict], feats: tuple[str, ...]) -> dict[str, float]:
    """Least squares of y on x × each shrink input (no intercept): y ≈ x × Σ b_k f_k."""
    if not feats:
        return {}
    X = np.array([[r["x"] * _value_feats(r)[k] for k in feats] for r in rows])
    y = np.array([r["y"] for r in rows])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    return {k: float(v) for k, v in zip(feats, b, strict=True)}


def _pred_value(r: dict, coef: dict[str, float]) -> float:
    if not coef:
        return r["x"]
    f = _value_feats(r)
    return r["x"] * sum(c * f[k] for k, c in coef.items())


@app.command()
def value() -> None:
    """Calibrate a buy's expected contribution on what real buys delivered: candidates fitted on the
    2019-2023 buys, chosen on 2024, the chosen one refitted on 2019-2024 and scored once on 2025-26."""
    rows = _value_rows()
    va = [r for r in rows if r["season"] == VALID]
    sel, best = {}, None
    for name, feats in VALUE_CANDIDATES.items():
        coef = _fit_value([r for r in rows if r["season"] < VALID], feats)
        err = float(np.mean([(r["y"] - _pred_value(r, coef)) ** 2 for r in va]))
        bias = float(np.mean([_pred_value(r, coef) - r["y"] for r in va]))
        sel[name] = {"mse": round(err, 4), "bias": round(bias, 4), "n": len(va), "coef": coef}
        typer.echo(f"{name:60} MSE {err:.4f} mean(pred − real) {bias:+.3f} (n {len(va)}) {coef}")
        if best is None or err < best[0]:
            best = (err, name)
    chosen = best[1]
    typer.echo(f"chosen: {chosen}")
    test = {}
    for name in dict.fromkeys([chosen, "V0 x as it stands (reference)"]):
        coef = _fit_value([r for r in rows if r["season"] <= VALID], VALUE_CANDIDATES[name])
        test[name] = {}
        for s in TEST:
            te = [r for r in rows if r["season"] == s]
            test[name][str(s)] = {
                "mse": round(float(np.mean([(r["y"] - _pred_value(r, coef)) ** 2 for r in te])), 4),
                "bias": round(float(np.mean([_pred_value(r, coef) - r["y"] for r in te])), 4),
                "n": len(te)}  # fmt: skip
        typer.echo(f"TEST {name:55} {json.dumps(test[name])}")
    rep = _read()
    rep["value"] = {
        "protocol": "candidates fitted on the 2019-2023 buys, chosen on the 2024 buys by squared error "
                    "of what each buy added a match of his side's season; the chosen one refitted on "
                    "2019-2024 and scored once on the 2025 and 2026 buys",
        "selection": sel, "chosen": chosen, "test": test,
        "coef_le2024": _fit_value([r for r in rows if r["season"] <= VALID], VALUE_CANDIDATES[chosen]),
        "coef": _fit_value(rows, VALUE_CANDIDATES[chosen]),
        "rows_by_season": {str(s): sum(1 for r in rows if r["season"] == s) for s in PLAY_SEASONS},
    }  # fmt: skip
    _write(rep)


ASOF_CONTRIB = DATA_DIR / "metrics" / ".playing_time" / "asof_contrib.parquet"


@app.command("asof-contrib")
def asof_contrib() -> None:
    """Every active rated player's contribution per match as of every auction 2009-2026 (the price
    model's and the Keep backtest's training rows): his as-of ratings per role, his usage before
    the auction, the walk-forward expected-balls models and replacement levels of `play` (auctions
    before 2018 use the 2018 ones: fitted on 2012-2017 usage, a small look ahead in the shrinkage
    constants only, never in a player's own numbers)."""
    import datetime as _dt
    import pickle

    u = _u()
    roles = _roles()
    hist = json.loads(ipm.HISTORY.read_text(encoding="utf-8"))
    play_data = pickle.loads(CACHE_PLAY.read_bytes())
    out = []
    for ys in sorted(hist["auctions"], key=int):
        s = int(ys)
        if s < 2009 or not ipm.ipl_fit_path(s).exists():
            continue
        date = hist["auctions"][ys]["date"]
        d = play_data[max(s, PLAY_SEASONS[0])]
        bm = {k: pt.BallsModel.from_json(v) for k, v in d["bm"].items()}
        vals = _asof(s, date)
        lo = (_dt.date.fromisoformat(date) - _dt.timedelta(days=POOL_RECENCY_DAYS)).isoformat()
        active = set(
            u.filter((pl.col("date") < date) & (pl.col("date") >= lo))["cid"].unique().to_list()
        )
        cids = sorted(c for c in vals if c in active)
        us = pt.expected_usage(u, date, cids, bm, d["T"], roles)
        con = squad_contribs(cids, vals, us, d["repl"])
        for c in cids:
            x = con[c]
            out.append((s, c, x["c"], x["sd"], x["bat"], x["bowl"], x["faced"], x["bowled"]))
        typer.echo(f"{s}: {len(cids)} players")
    ASOF_CONTRIB.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "season",
        "cid",
        "contrib",
        "contrib_sd",
        "contrib_bat",
        "contrib_bowl",
        "balls_faced",
        "balls_bowled",
    ]
    pl.DataFrame(out, schema=cols, orient="row").write_parquet(ASOF_CONTRIB)
    typer.echo(f"wrote {ASOF_CONTRIB}")


@app.command()
def ship(next_auction: str = typer.Option("2026-12-16", "--before")) -> None:
    """Refit the chosen models on everything up to 2026 and write config/playing_time_model.json."""
    import datetime as _dt

    _WHICH["which"] = "roles"  # the shipped translation (fitted on every season)
    _ASOF.clear()
    _DRIFT.clear()
    u = _u()
    roles = _roles()
    starts = season_starts(u)
    hist = json.loads(ipm.HISTORY.read_text(encoding="utf-8"))
    rep = _read()
    chosen_balls = rep["balls"]["chosen"]
    chosen_play, alpha = rep["play"]["chosen"], rep["play"]["alpha"]
    seasons = sorted(starts)
    seasons = [s for s in seasons if s >= BALLS_FIRST]
    spec = BALLS_CANDIDATES[chosen_balls]
    rows = _balls_rows(u, roles, seasons)
    pri = {d: _priors(u, starts, seasons, d) for d in DECAY_GRID}
    pars = {disc: fit_balls(rows, pri, disc, spec) for disc in ("sf", "sb")}
    bm = balls_models(pars, chosen_balls)
    for m in bm.values():
        m.trained_on = (min(seasons), max(seasons))
    T = pt.team_balls(u, next_auction)
    last = max(int(k) for k in hist["auctions"])
    repl = replacement_from_minbuys(hist, u, last + 1)
    by_era = _xi_by_era()
    prow = _all_play_rows(by_era)
    pm_ = pt.fit_play_model(prow, PLAY_CANDIDATES[chosen_play], alpha)
    pm_.xi_by_era = by_era
    import pickle

    fa = pickle.loads(CACHE_FA.read_bytes())
    frows = _fa_era([r for s in PLAY_SEASONS for r in fa[s]], by_era)
    chosen_fa, alpha_fa = rep["free_agent"]["chosen"], rep["free_agent"]["alpha"]
    fm_ = pt.fit_play_model(frows, FA_CANDIDATES[chosen_fa], alpha_fa)
    fm_.xi_by_era = by_era
    # P(plays) of an auction buy in the squad that bought him (`buy`), refitted on every season's buys
    buy_model = None
    if rep.get("buy"):
        kind = BUY_CANDIDATES[rep["buy"]["chosen"]]
        feats = BUY_FEATURES + (("price_share",) if kind == "buys_price" else ())
        src = _all_play_rows(by_era) if kind == "squad" else _buy_rows()
        bm_ = pt.fit_play_model(src, feats, rep["buy"]["alpha"])
        bm_.xi_by_era = by_era
        buy_model = {**bm_.to_json(), "alpha": rep["buy"]["alpha"], "chosen": rep["buy"]["chosen"]}
    model = {
        "schema": 1,
        "version": pt.VERSION,
        "league": "ipl",
        "fitted": _dt.date.today().isoformat(),
        "method": "expected season value = P(plays a match | in the squad) x contribution per "
                  "match (runs above replacement: (batting value - replacement for his slot) x "
                  "balls faced per match / 100 + (bowling value - replacement for his group) x "
                  "balls bowled per match / 100); scripts/playing_time_fit.py, "
                  "docs/METHODOLOGY.md section 6c",
        "balls_per_innings": round(T, 3),
        "league_matches": pt.LEAGUE_MATCHES,
        "balls": {k: v.to_json() for k, v in bm.items()},
        "balls_chosen": chosen_balls,
        "replacement": repl,
        "play": {**pm_.to_json(), "alpha": alpha, "chosen": chosen_play},
        "free_agent": {**fm_.to_json(), "alpha": alpha_fa, "chosen": chosen_fa},
        "buy": buy_model,
        "evaluation": {
            "balls": {"protocol": rep["balls"]["protocol"], "test": rep["balls"]["test"]},
            "play": {"protocol": rep["play"]["protocol"],
                     "test": {k: v["pooled"] for k, v in rep["play"]["test"].items()}},
            "free_agent": {"protocol": rep["free_agent"]["protocol"],
                           "test": {k: v["pooled"] for k, v in rep["free_agent"]["test"].items()}},
        },
    }  # fmt: skip
    pt.MODEL_PATH.write_text(json.dumps(model, indent=1, ensure_ascii=False) + "\n",
                             encoding="utf-8")  # fmt: skip
    typer.echo(f"wrote {pt.MODEL_PATH}: T {T:.1f}, replacement {repl}")


if __name__ == "__main__":
    app()
