"""Fit, choose and test the time-aware rating (docs/METHODOLOGY.md §4b; `src/cricdesk/scout/ratings/drift.py`;
ROADMAP Tier D #34, I18).

The frozen protocol. The candidates below were declared on 2026-10-27 before any number was seen.

* Validation, walk-forward: for every IPL season s = 2019 … 2024, every candidate is fitted on the season
  values known before that season's auction and scored on what the players then did in season s. The
  primary metric is the error of next season's contribution per match (runs above replacement a match
  he plays: `bidplan_backtest._next_season_values`), predicted as the export predicts it (his as-of
  ratings per role, blended across leagues, shifted by the candidate; his expected balls and the
  replacement levels as of that auction, `playing_time_fit` `play`). Also the rank correlation.
* The candidate with the lowest pooled error on 2019-2024 is chosen; it is refitted on the season values
  up to 2024 (before the 2025 auction) and scored **once** on 2025 and 2026, with the career rating.
* `ship` refits the chosen one on everything before the next auction and writes config/rating_drift.json
  (`model`, and `model_le2024` for the other protocol runs, which must not see 2025-26).

    uv run python scripts/rating_drift_fit.py obs         # season values per league and year (~15 min, cached)
    uv run python scripts/rating_drift_fit.py validate    # 2019-2024, every candidate (~30 min)
    uv run python scripts/rating_drift_fit.py test        # the chosen one, once, on 2025-26
    uv run python scripts/rating_drift_fit.py ship        # config/rating_drift.json

Results: data/metrics/rating_drift_ipl.json.
"""

from __future__ import annotations

import json
import math
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ipl_price_model as ipm  # noqa: E402
import playing_time_fit as ptf  # noqa: E402

from cricdesk.config import DATA_DIR  # noqa: E402
from cricdesk.scout import playing_time as pt  # noqa: E402
from cricdesk.scout import translation  # noqa: E402
from cricdesk.scout.identity import master  # noqa: E402
from cricdesk.scout.ratings import (
    bayesian,  # noqa: E402
    drift,  # noqa: E402
)

app = typer.Typer(add_completion=False)

OUT = DATA_DIR / "metrics" / "rating_drift_ipl.json"
VALID = (2019, 2020, 2021, 2022, 2023, 2024)
TEST = (2025, 2026)
NEXT_AUCTION = "2026-12-16"  # the 2027 auction (competitions: ipl 2027)

# Candidates, declared 2026-10-27 before any validation number. Every one but C0 and C6 carries the
# selection model (drift.py: whether he plays a season, given his level), the survivorship correction:
# without it the in-sample fits (before 2024, seen while building the model, no validation score) put the
# random walk at almost nothing and the batting curve flat after 28, the survivors' picture.
CANDIDATES = {
    "C0 career rating (reference, shipped until now)": None,
    "C1 aging only (q = 0: a fixed level plus the fitted aging curve)": "aging",
    "C2 drift only (random walk, no aging curve)": "walk",
    "C3 random walk + aging curve; one bowling curve": "pooled",
    "C4 random walk + aging curve; pace and spin curves apart": "split",
    "C5 random walk + aging curve; pace and spin partially pooled (empirical Bayes)": "partial",
    "C6 C3 without the selection model (survivors only)": "pooled_nosel",
}


def _say(msg: str) -> None:
    typer.echo(msg)
    sys.stdout.flush()


def _hist() -> dict:
    return json.loads(ipm.HISTORY.read_text(encoding="utf-8"))


def _master() -> tuple[dict[str, str], dict[str, str | None]]:
    pm = master.load()
    dob = {cid: str(r["dob"])[:10] for cid, r in pm.items() if isinstance(r, dict) and r.get("dob")}
    cat = {cid: r.get("bowling_category") for cid, r in pm.items() if isinstance(r, dict)}
    return dob, cat


def _cuts() -> list[str]:
    h = _hist()
    return sorted({a["date"] for a in h["auctions"].values()} | {NEXT_AUCTION})


def _obs() -> pl.DataFrame:
    return drift.season_obs(bayesian.DEFAULT_DB_PATH, ptf.POOL_COLS, _cuts(), log=_say)


@app.command()
def obs() -> None:
    """Every pool league's season values by calendar year, and up to each auction date (cached)."""
    t = time.time()
    o = _obs()
    _say(f"{o.height} rows, {o['league'].n_unique()} leagues, {time.time() - t:.0f} s")


# ---- fitting a candidate ---------------------------------------------------------------------------------


def fit_candidate(kind: str, o: pl.DataFrame, date: str, dob, cat, which: str,
                  warm: drift.DriftModel | None = None) -> drift.DriftModel:  # fmt: skip
    """Fit candidate `kind` on the season values known before `date` (`warm`: the same candidate's
    fit at an earlier date, a starting point only)."""
    oa = drift.obs_asof(o, date)
    da = drift.debut_age(oa, dob)
    s = drift.sequences(oa, dob, cat, None, which, da, None, int(date[:4]))
    bat = drift.subset(s, s.group == "bat")
    bowl = drift.subset(s, s.group != "bat")
    sel = kind != "pooled_nosel"

    def st(g: str):
        return warm.groups.get(g) if warm else None

    groups: dict[str, drift.GroupParams] = {}
    if kind == "aging":
        groups["bat"] = drift.fit_group(bat, fix_q0=True, with_sd=False, start=st("bat"))
        groups["bowl"] = drift.fit_group(bowl, fix_q0=True, with_sd=False, start=st("bowl"))
    elif kind == "walk":
        groups["bat"] = drift.fit_group(bat, no_curve=True, start=st("bat"))
        groups["bowl"] = drift.fit_group(bowl, no_curve=True, start=st("bowl"))
    else:
        groups["bat"] = drift.fit_group(bat, start=st("bat"), use_sel=sel)
        groups["bowl"] = drift.fit_group(bowl, start=st("bowl"), use_sel=sel)
        if kind in ("split", "partial"):
            for g in ("pace", "spin"):
                groups[g] = drift.fit_group(drift.subset(s, s.group == g),
                                            start=st(g) or groups["bowl"])  # fmt: skip
        if kind == "partial":
            groups = partial_pool(groups, s)
    return drift.DriftModel(groups, da, date, kind)


def partial_pool(
    groups: dict[str, drift.GroupParams], s: drift.Seqs
) -> dict[str, drift.GroupParams]:
    """Empirical-Bayes partial pooling of the pace and spin curves toward the pooled bowling curve:
    each knot's departure d = curve_g − curve_pooled is shrunk by tau² / (tau² + se²), tau² the
    method-of-moments spread of the departures beyond their standard errors; then the group's other
    parameters are refitted with its curve held there."""
    ref = drift.KNOTS.index(drift.AGE_REF)
    pooled = np.array(groups["bowl"].curve)
    devs, ses = [], []
    for g in ("pace", "spin"):
        c = np.array(groups[g].curve)
        se = np.array(groups[g].curve_sd or [np.nan] * len(c))
        for j in range(len(c)):
            if j != ref and np.isfinite(se[j]):
                devs.append(c[j] - pooled[j])
                ses.append(se[j])
    devs, ses = np.array(devs), np.array(ses)
    tau2 = max(float(np.mean(devs**2) - np.mean(ses**2)), 0.0) if len(devs) else 0.0
    out = dict(groups)
    for g in ("pace", "spin"):
        c = np.array(groups[g].curve)
        se = np.array(groups[g].curve_sd or [np.nan] * len(c), dtype=float)
        ok = np.isfinite(se) & (se > 0)
        # a knot with no standard error (no data there) is pooled fully
        k = np.where(ok, tau2 / (tau2 + np.where(ok, se, 1.0) ** 2), 0.0)
        shrunk = pooled + k * (c - pooled)
        shrunk[ref] = 0.0
        out[g] = drift.fit_group(drift.subset(s, s.group == g), fix_curve=shrunk, start=groups[g],
                                 with_sd=False)  # fmt: skip
        out[g].curve_sd = groups[g].curve_sd
    out["_tau"] = drift.GroupParams(0.0, tau2, 0.0, 1.0, 1.0)  # recorded, not a group
    return out


# ---- scoring on the next season ---------------------------------------------------------------------------


def asof_roles_shares(season: int, date: str, which: str):
    """cid → {role: (value, sd)} and (cid, role) → {league: blend share}, as playing_time_fit.asof_roles."""
    own, other = ipm.asof_sources(season, date)
    tm = translation.load_model()
    vals: dict[str, dict[str, tuple[float, float]]] = {}
    shares: dict[tuple[str, str], dict[str, float]] = {}
    for key in set(own) | set(other):
        cid, role = key
        if role not in translation.ROLES:
            continue
        o = own.get(key)
        v, sd, sh = translation.blend(role, (o[0], o[1]) if o else None, other.get(key, {}), tm,
                                      which)  # fmt: skip
        vals.setdefault(cid, {})[role] = (v, sd)
        shares[key] = sh
    return vals, shares


_SEASON: dict = {}


def season_inputs(s: int, which: str) -> dict:
    """What every candidate needs for season s: the as-of values and shares, the realised
    contributions, expected usage and replacement levels."""
    import bidplan_backtest as bt

    if (s, which) in _SEASON:
        return _SEASON[(s, which)]
    hist = _hist()
    date = hist["auctions"][str(s)]["date"]
    vals, shares = asof_roles_shares(s, date, which)
    nv = bt._next_season_values(s)
    play = pickle.loads(ptf.CACHE_PLAY.read_bytes())[s]
    bm = {k: pt.BallsModel.from_json(v) for k, v in play["bm"].items()}
    cids = sorted(c for c in nv if c in vals)
    roles = ptf._roles()
    us = pt.expected_usage(ptf._u(), date, cids, bm, play["T"], roles)
    d = {"date": date, "vals": vals, "shares": shares, "nv": nv, "cids": cids, "us": us,
         "repl": play["repl"]}  # fmt: skip
    _SEASON[(s, which)] = d
    return d


def predictions(d: dict, vals: dict) -> np.ndarray:
    out = []
    for cid in d["cids"]:
        v = vals.get(cid, {})
        x = d["us"][cid]
        c, _sd, _p = pt.contribution(v.get("batter"), v.get("bowler"), x["faced"], x["bowled"],
                                     x["pos"], d["repl"])  # fmt: skip
        out.append(c)
    return np.array(out)


def shifted_values(d: dict, model: drift.DriftModel | None, o, dob, cat, s: int, which: str):
    if model is None:
        return d["vals"], {}
    sub = {c: d["vals"][c] for c in d["cids"]}
    return drift.adjust(sub, d["shares"], o, d["date"], s, dob, cat, model, which)


def score(pred: np.ndarray, d: dict) -> dict:
    from scipy.stats import spearmanr

    y = np.array([d["nv"][c][0] for c in d["cids"]])
    return {"n": len(y), "mae": float(np.mean(np.abs(pred - y))),
            "rmse": float(np.sqrt(np.mean((pred - y) ** 2))),
            "bias": float(np.mean(pred - y)),
            "spearman": float(spearmanr(pred, y).statistic)}  # fmt: skip


def _ages(d: dict, dob: dict, s: int) -> np.ndarray:
    return np.array([drift.age_on(dob.get(c), s) or np.nan for c in d["cids"]])


def _pooled(per: dict[int, dict]) -> dict:
    n = sum(v["n"] for v in per.values())
    return {"n": n,
            "mae": round(sum(v["mae"] * v["n"] for v in per.values()) / n, 4),
            "rmse": round(math.sqrt(sum(v["rmse"] ** 2 * v["n"] for v in per.values()) / n), 4),
            "bias": round(sum(v["bias"] * v["n"] for v in per.values()) / n, 4),
            "spearman_mean": round(float(np.mean([v["spearman"] for v in per.values()])), 4)}  # fmt: skip


def _read() -> dict:
    return json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}


def _write(rep: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


MODEL_CACHE = drift.CACHE_DIR / "fits.pkl"


def _fit_cached(kind: str, o, date: str, dob, cat, which: str) -> drift.DriftModel:
    cache = pickle.loads(MODEL_CACHE.read_bytes()) if MODEL_CACHE.exists() else {}
    key = (kind, date, which)
    if key not in cache:
        t = time.time()
        earlier = sorted(d for (k, d, w) in cache if k == kind and w == which and d < date)
        warm = _model(cache[(kind, earlier[-1], which)]) if earlier else None
        cache[key] = fit_candidate(kind, o, date, dob, cat, which, warm).to_json()
        MODEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        MODEL_CACHE.write_bytes(pickle.dumps(cache))
        _say(f"    fitted {kind} before {date} in {time.time() - t:.0f} s")
    return _model(cache[key])


def _model(js: dict) -> drift.DriftModel:
    m = dict(js)
    m["groups"] = {g: p for g, p in m["groups"].items() if not g.startswith("_")}
    return drift.DriftModel.from_json(m)


def _run(seasons, which: str, kinds: dict[str, str | None], fit_date=None) -> dict:
    """Every candidate in `kinds` scored on `seasons`; each fitted before that season's auction, or
    before `fit_date` when given (the test: fitted once, up to 2024)."""
    o = _obs()
    dob, cat = _master()
    res: dict = {}
    for s in seasons:
        d = season_inputs(s, which)
        ages = _ages(d, dob, s)
        y = np.array([d["nv"][c][0] for c in d["cids"]])
        for name, kind in kinds.items():
            m = (
                None
                if kind is None
                else _fit_cached(kind, o, fit_date or d["date"], dob, cat, which)
            )
            vals, _ = shifted_values(d, m, o, dob, cat, s, which)
            p = predictions(d, vals)
            sc = score(p, d)
            old = ages >= 34
            sc["mae_age34plus"] = float(np.mean(np.abs(p[old] - y[old]))) if old.any() else None
            sc["bias_age34plus"] = float(np.mean(p[old] - y[old])) if old.any() else None
            sc["n_age34plus"] = int(old.sum())
            res.setdefault(name, {})[s] = sc
            _say(f"{s} {name[:58]:58} MAE {sc['mae']:.3f} rho {sc['spearman']:.3f} "
                 f"bias {sc['bias']:+.3f} | 34+: MAE {sc['mae_age34plus'] or 0:.3f} "
                 f"bias {sc['bias_age34plus'] or 0:+.3f} (n {sc['n_age34plus']})")  # fmt: skip
    return res


@app.command()
def validate() -> None:
    """Every candidate, walk-forward on 2019-2024: choose the lowest pooled error."""
    res = _run(VALID, "roles_le2024", CANDIDATES)
    sel = {name: {"pooled": _pooled(per), **{str(s): v for s, v in per.items()}}
           for name, per in res.items()}  # fmt: skip
    for name, v in sel.items():
        _say(f"POOLED {name[:62]:62} {json.dumps(v['pooled'])}")
    cands = [n for n, k in CANDIDATES.items() if k is not None]
    chosen = min(cands, key=lambda n: (sel[n]["pooled"]["mae"], -sel[n]["pooled"]["spearman_mean"]))
    _say(f"chosen: {chosen}")
    rep = _read()
    rep["validation"] = {
        "protocol": "candidates declared 2026-10-27 before any number; each fitted on the season values "
                    "known before each auction 2019-2024 and scored on that season's contribution per "
                    "match (runs above replacement a match he plays) of every player who played it; "
                    "chosen by the pooled mean absolute error",
        "candidates": CANDIDATES, "selection": sel, "chosen": chosen,
    }  # fmt: skip
    _write(rep)


@app.command()
def test() -> None:
    """The chosen candidate, fitted on the season values up to 2024 (before the 2025 auction), scored
    once on 2025 and 2026 with the career rating."""
    rep = _read()
    chosen = rep["validation"]["chosen"]
    fit_date = _hist()["auctions"]["2025"]["date"]
    kinds = {k: CANDIDATES[k] for k in dict.fromkeys(
        ["C0 career rating (reference, shipped until now)", chosen])}  # fmt: skip
    res = _run(TEST, "roles_le2024", kinds, fit_date=fit_date)
    out = {name: {"pooled": _pooled(per), **{str(s): v for s, v in per.items()}}
           for name, per in res.items()}  # fmt: skip
    for name, v in out.items():
        _say(f"TEST {name[:62]:62} {json.dumps(v['pooled'])}")
    rep["test"] = {"protocol": "the chosen candidate fitted on the season values before the 2025 "
                               "auction (seasons up to 2024), scored once on 2025 and 2026",
                   "fitted_before": fit_date, "result": out}  # fmt: skip
    _write(rep)


@app.command()
def ship() -> None:
    """Refit the chosen candidate on everything before the next auction (`model`) and up to 2024
    (`model_le2024`) and write config/rating_drift.json."""
    import datetime as _dt

    rep = _read()
    chosen = rep["validation"]["chosen"]
    kind = CANDIDATES[chosen]
    o = _obs()
    dob, cat = _master()
    le = _fit_cached(kind, o, _hist()["auctions"]["2025"]["date"], dob, cat, "roles_le2024")
    full = _fit_cached(kind, o, NEXT_AUCTION, dob, cat, "roles")
    out = {
        "schema": 1, "version": drift.VERSION, "fitted": _dt.date.today().isoformat(),
        "method": "value now = career rating + E[level next season - career-average level | season "
                  "values in every auction-pool league]; level = random walk + fitted aging curve per "
                  "group; scripts/rating_drift_fit.py, docs/METHODOLOGY.md section 4b",
        "chosen": chosen, "knots": list(drift.KNOTS),
        "model": full.to_json(), "model_le2024": le.to_json(),
        "evaluation": {"validation": rep["validation"]["selection"].get(chosen, {}).get("pooled"),
                       "test": rep.get("test", {}).get("result")},
    }  # fmt: skip
    drift.MODEL_PATH.write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _say(f"wrote {drift.MODEL_PATH}")
    for g, p in full.groups.items():
        _say(f"  {g}: q {p.q:.2f} c {p.c:.0f} e {p.e:.1f} tau2 {p.tau2:.1f} curve "
             f"{[round(x, 1) for x in p.curve]}")  # fmt: skip


@app.command()
def curves(date: str = typer.Option(NEXT_AUCTION, "--before"), kind: str = "pooled",
           which: str = "roles") -> None:  # fmt: skip
    """Fit (or read from the cache) one candidate and print its parameters."""
    o = _obs()
    dob, cat = _master()
    m = _fit_cached(kind, o, date, dob, cat, which)
    for g, p in m.groups.items():
        _say(f"{g}: mu0 {p.mu0:.1f} tau2 {p.tau2:.1f} q {p.q:.2f} c {p.c:.0f} e {p.e:.1f} "
             f"(keys {p.n_keys}, obs {p.n_obs})")  # fmt: skip
        _say(
            "   curve "
            + " ".join(f"{a:.0f}:{v:+.1f}" for a, v in zip(drift.KNOTS, p.curve, strict=True))
        )
        if p.curve_sd:
            _say(
                "   sd    "
                + " ".join(f"{a:.0f}:{v:.1f}" for a, v in zip(drift.KNOTS, p.curve_sd, strict=True))
            )


if __name__ == "__main__":
    app()
