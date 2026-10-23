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
PLAY_CANDIDATES = {
    "P0 base rate (reference)": (),
    "P1 rank in the squad": _P_RANK,
    "P2 P1 + overseas places": _P_RANK + _P_OS,
    "P3 P2 + experience and age": _P_RANK + _P_OS + _P_EXP,
    "P4 P3 + availability (last season's share)": _P_RANK + _P_OS + _P_EXP + _P_AVAIL,
    "P5 P4 + keeper, captain, impact era": _P_RANK + _P_OS + _P_EXP + _P_AVAIL + _P_OTHER,
}
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
    for key in set(own) | set(other):
        cid, role = key
        if role not in translation.ROLES:
            continue
        o = own.get(key)
        val, vsd, _ = translation.blend(role, (o[0], o[1]) if o else None, other.get(key, {}), tm,
                                        _WHICH["which"])  # fmt: skip
        out.setdefault(cid, {})[role] = (val, vsd)
    return out


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


def replacement_from_minbuys(
    hist: dict, u: pl.DataFrame, before: int, bm: dict[str, pt.BallsModel], T: float
) -> dict[str, dict]:
    """The replacement levels: the mean rating, at the auction, of the players bought at that
    auction's lowest price (no franchise bid more: freely available talent), by the slot group of his
    usual batting position and by bowling group (frontline when he is expected to bowl
    FRONTLINE_BALLS+ a match), over the auctions REPL_FIRST ... before - 1. `bm` / `T`: the
    expected-balls models and balls per innings fitted before `before`."""
    floors: dict[int, float] = {}
    for r in hist["lots"]:
        if r.get("sold") and r.get("price_cr"):
            floors[r["season"]] = min(floors.get(r["season"], math.inf), float(r["price_cr"]))
    acc: dict[tuple[str, str], list[float]] = {}
    roles = _roles()
    for s in range(REPL_FIRST, before):
        a = hist["auctions"].get(str(s))
        if not a:
            continue
        date = a["date"]
        buys = [r["cricsheet_id"] for r in hist["lots"]
                if r["season"] == s and r.get("sold") and r.get("cricsheet_id")
                and r.get("price_cr") and float(r["price_cr"]) <= floors[s] + 1e-9]  # fmt: skip
        if not buys:
            continue
        vals = _asof(s, date)
        us_all = pt.expected_usage(u, date, buys, bm, T, roles)
        for cid in buys:
            v = vals.get(cid, {})
            us = us_all[cid]
            if "batter" in v:
                x = acc.setdefault(("bat", pt.slot_group(us["pos"])), [0.0, 0.0])
                x[0] += 1
                x[1] += v["batter"][0]
            if "bowler" in v:
                g = "frontline" if us["bowled"] >= pt.FRONTLINE_BALLS else "part_time"
                x = acc.setdefault(("bowl", g), [0.0, 0.0])
                x[0] += 1
                x[1] += v["bowler"][0]
    out: dict[str, dict] = {"bat": {}, "bowl": {}, "n": {}}
    for (d, g), (n, s) in acc.items():
        out[d][g] = round(s / n, 3)
        out["n"][f"{d}:{g}"] = int(n)
    return out


# ---- P(plays): the squads of every season with a complete retained list ------------------------------

_ASOF: dict = {}


def _asof(season: int, date: str) -> dict:
    if season not in _ASOF:
        _ASOF[season] = asof_roles(season, date)
    return _ASOF[season]


def walk_forward(u, roles, starts, hist, s: int, chosen: str) -> tuple[dict, float, dict]:
    """(expected-balls models, balls per innings, replacement levels) fitted on what was known
    before season `s`'s auction."""
    seasons = list(range(BALLS_FIRST, s))
    spec = BALLS_CANDIDATES[chosen]
    rows = _balls_rows(u, roles, seasons)
    pri = {d: _priors(u, starts, seasons, d) for d in DECAY_GRID}
    pars = {disc: fit_balls(rows, pri, disc, spec) for disc in ("sf", "sb")}
    bm = balls_models(pars, chosen)
    date = hist["auctions"][str(s)]["date"]
    T = pt.team_balls(u, date)
    repl = replacement_from_minbuys(hist, u, s, bm, T)
    return bm, T, repl


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


def _all_play_rows() -> list[dict]:
    import pickle

    data = pickle.loads((CACHE_PLAY).read_bytes())
    rows = [r for s in PLAY_SEASONS for r in data[s]["rows"]]
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
    rows = _all_play_rows()
    tr = [r for r in rows if r["season"] < VALID]
    va = [r for r in rows if r["season"] == VALID]
    sel = {}
    best = None
    for name, feats in PLAY_CANDIDATES.items():
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
    p_te, _ = _fit_predict(tr2, te, PLAY_CANDIDATES[chosen], alpha)
    rep["play"] = {
        "protocol": "candidates fitted on the squads of 2018-2023, chosen on 2024 by the binomial "
                    "log loss per match; the chosen one refitted on 2018-2024 and scored once on "
                    "the 2025 and 2026 squads",
        "selection": sel, "chosen": chosen, "alpha": alpha, "test": test,
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
        lines = []
        for _t, members in prev_sq.items():
            sq = [pt.squad_member(c, con[c]["c"], roles.get(c, "batter"),
                                  bool(country(c)) and country(c) != "IND") for c in members]  # fmt: skip
            lines.append(pt.xi_line(sq))
        line = float(np.median(lines)) if lines else 0.0
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
    rows = [r for s in PLAY_SEASONS for r in data[s]]
    for r in rows:
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
    repl = replacement_from_minbuys(hist, u, last + 1, bm, T)
    prow = _all_play_rows()
    pm_ = pt.fit_play_model(prow, PLAY_CANDIDATES[chosen_play], alpha)
    import pickle

    fa = pickle.loads(CACHE_FA.read_bytes())
    frows = [r for s in PLAY_SEASONS for r in fa[s]]
    for r in frows:
        r["_f"] = pt.fa_features(r)
    chosen_fa, alpha_fa = rep["free_agent"]["chosen"], rep["free_agent"]["alpha"]
    fm_ = pt.fit_play_model(frows, FA_CANDIDATES[chosen_fa], alpha_fa)
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
