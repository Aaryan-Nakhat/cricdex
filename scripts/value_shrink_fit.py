"""Fit, choose and test how far a value is trusted given its evidence (docs/METHODOLOGY.md §4c;
`src/cricdex/scout/ratings/shrink.py`; ROADMAP I18).

Frozen protocol. The candidates below were declared on 2026-10-27 before any number.

* Rows: for every IPL season 2012-2026, every player who then played it (per role): his value as of that
  season's auction (the blend of every league, moved to his age by the time-aware model fitted to 2024,
  `model_le2024`), its sd, the IPL's share of its blend, the years since his last season anywhere, and
  what he did that season (`runs_value.observed_value`, his balls).
* Validation, walk-forward 2019-2024: each candidate fitted on the rows of the seasons before, scored on
  that season's contribution per match (as `rating_drift_fit.py`: runs above replacement a match he
  played, predicted the way the export predicts it). Chosen on the pooled mean absolute error.
* Test, once: the chosen one fitted on the rows up to 2024, scored on 2025 and 2026 with no calibration.
* `ship`: refitted on every row (`model`) and on the rows up to 2024 (`model_le2024`, for the other
  protocol runs) into config/value_shrink.json.

    uv run python scripts/value_shrink_fit.py rows       # the rows (cached, ~5 min)
    uv run python scripts/value_shrink_fit.py validate
    uv run python scripts/value_shrink_fit.py test
    uv run python scripts/value_shrink_fit.py ship
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

import playing_time_fit as ptf  # noqa: E402
import rating_drift_fit as rf  # noqa: E402

from cricdex.config import DATA_DIR  # noqa: E402
from cricdex.scout.ratings import bayesian, drift, shrink  # noqa: E402

app = typer.Typer(add_completion=False)

OUT = DATA_DIR / "metrics" / "value_shrink_ipl.json"
ROWS = DATA_DIR / "metrics" / ".drift" / "shrink_rows.pkl"
FIRST = 2012
VALID = (2019, 2020, 2021, 2022, 2023, 2024)
TEST = (2025, 2026)

# Candidates, declared 2026-10-27 before any number.
CANDIDATES = {
    "K0 no calibration (reference, shipped until now)": None,
    "K1 one shrink factor per role toward the role's mean": "flat",
    "K2 shrink by the value's own posterior sd (its uncertainty carried through)": "sd",
    "K3 K2 + the non-IPL share of the evidence + years since his last season": "full",
}


def _say(msg: str) -> None:
    typer.echo(msg)
    sys.stdout.flush()


_OBS: dict = {}


def _obs() -> pl.DataFrame:
    if "o" not in _OBS:
        _OBS["o"] = drift.season_obs(bayesian.DEFAULT_DB_PATH, ptf.POOL_COLS, rf._cuts())
    return _OBS["o"]


def asof_inputs(s: int, date: str) -> tuple[dict, dict, dict]:
    """(cid → {role: (time-aware value, sd)}, shares, cid → years since his last season) as of the
    auction of season s, with the protocol's models (translation and time-aware model to 2024)."""
    vals, shares = rf.asof_roles_shares(s, date, "roles_le2024")
    dob, cat = rf._master()
    m = drift.load_model(which="model_le2024")
    vals, _ = drift.adjust(vals, shares, _obs(), date, s, dob, cat, m, "roles_le2024")
    return vals, shares, shrink.years_since(_obs(), date)


@app.command()
def rows() -> None:
    """Every (season, player, role) of IPL seasons 2012-2026 with its as-of inputs and outcome."""
    hist = rf._hist()
    h = pl.read_parquet(ptf.HISTORY_PATH)
    done: dict = pickle.loads(ROWS.read_bytes()) if ROWS.exists() else {}
    for s in range(FIRST, 2027):
        if s in done or str(s) not in hist["auctions"]:
            continue
        date = hist["auctions"][str(s)]["date"]
        vals, shares, yrs = asof_inputs(s, date)
        out = []
        for cid, role, _s, y, n in h.filter(pl.col("season") == s).iter_rows():
            v = (vals.get(cid) or {}).get(role)
            if v is None or n is None or n <= 0 or y is None or not math.isfinite(y):
                continue
            out.append({"season": s, "cid": cid, "role": role, "v": v[0], "sd": v[1],
                        "share": (shares.get((cid, role)) or {}).get("ipl", 0.0),
                        "years": yrs.get(cid, 0.0), "y": float(y), "n": float(n)})  # fmt: skip
        done[s] = out
        ROWS.parent.mkdir(parents=True, exist_ok=True)
        ROWS.write_bytes(pickle.dumps(done))
        _say(f"{s}: {len(out)} rows")


def _rows() -> list[dict]:
    return [r for v in pickle.loads(ROWS.read_bytes()).values() for r in v]


def fit(rows_: list[dict], kind: str) -> dict[str, shrink.RoleShrink] | None:
    """Maximum likelihood per role: y ~ N(mu + k (v − mu), c × 100 / n + psi)."""
    from scipy.optimize import minimize

    if kind is None:
        return None
    out = {}
    for role in shrink.ROLES:
        R = [r for r in rows_ if r["role"] == role]
        v = np.array([r["v"] for r in R])
        sd = np.array([r["sd"] for r in R])
        sh = np.array([r["share"] for r in R])
        yr = np.array([r["years"] for r in R])
        y = np.array([r["y"] for r in R])
        n = np.array([r["n"] for r in R])

        def unpack(z):
            mu, c, psi = z[0], math.exp(z[1]), math.exp(z[2])
            if kind == "flat":
                return shrink.RoleShrink(mu, 1.0, k_flat=float(z[3])), c, psi
            tau2, s = math.exp(z[3]), math.exp(z[4])
            wo = math.exp(z[5]) if kind == "full" else 0.0
            wr = math.exp(z[6]) if kind == "full" else 0.0
            return shrink.RoleShrink(mu, tau2, s, wo, wr), c, psi

        def nll(z, v=v, sd=sd, sh=sh, yr=yr, y=y, n=n):
            m, c, psi = unpack(z)
            if m.k_flat is not None:
                k = np.full(len(v), m.k_flat)
            else:
                k = m.tau2 / (m.tau2 + m.s * sd * sd + m.w_o * (1 - sh) + m.w_r * yr)
            mean = m.mu + k * (v - m.mu)
            var = c * 100.0 / n + psi
            return float(np.sum(np.log(var) + (y - mean) ** 2 / var))

        z0 = [float(np.mean(v)), math.log(900.0), math.log(30.0)]
        z0 += (
            [0.8]
            if kind == "flat"
            else [math.log(60.0), 0.0] + ([0.0, 0.0] if kind == "full" else [])
        )
        best = None
        for start in (z0, [z0[0], z0[1], z0[2], *[x - 1.0 for x in z0[3:]]]):
            res = minimize(nll, np.array(start), method="Nelder-Mead",
                           options={"maxiter": 20000, "maxfev": 20000, "xatol": 1e-6, "fatol": 1e-8})  # fmt: skip
            if best is None or res.fun < best.fun:
                best = res
        out[role] = unpack(best.x)[0]
    return out


def _years_at(date: str) -> dict:
    return shrink.years_since(_obs(), date)


def _score(seasons, fit_until_each: bool, kinds: dict) -> dict:
    allr = _rows()
    dob, cat = rf._master()
    m_le = drift.load_model(which="model_le2024")
    res: dict = {}
    for s in seasons:
        d = rf.season_inputs(s, "roles_le2024")
        sub = {c: d["vals"][c] for c in d["cids"]}
        vt, _ = drift.adjust(sub, d["shares"], _obs(), d["date"], s, dob, cat, m_le, "roles_le2024")
        yrs = _years_at(d["date"])
        thin = np.array([(d["shares"].get((c, "batter")) or d["shares"].get((c, "bowler")) or {})
                         .get("ipl", 0.0) < 0.5 for c in d["cids"]])  # fmt: skip
        y = np.array([d["nv"][c][0] for c in d["cids"]])
        for name, kind in kinds.items():
            train = [r for r in allr if r["season"] < s] if fit_until_each else [
                r for r in allr if r["season"] <= VALID[-1]]  # fmt: skip
            m = fit(train, kind)
            vals, _ = shrink.adjust(vt, d["shares"], yrs, m)
            p = rf.predictions(d, vals)
            sc = rf.score(p, d)
            sc["n_thin"] = int(thin.sum())
            sc["mae_thin"] = float(np.mean(np.abs(p[thin] - y[thin]))) if thin.any() else None
            sc["bias_thin"] = float(np.mean(p[thin] - y[thin])) if thin.any() else None
            res.setdefault(name, {})[s] = sc
            _say(f"{s} {name[:60]:60} MAE {sc['mae']:.3f} rho {sc['spearman']:.3f} bias "
                 f"{sc['bias']:+.3f} | IPL share < 0.5: MAE {sc['mae_thin'] or 0:.3f} bias "
                 f"{sc['bias_thin'] or 0:+.3f} (n {sc['n_thin']})")  # fmt: skip
    return res


def _pool(per: dict) -> dict:
    out = rf._pooled(per)
    nt = sum(v["n_thin"] for v in per.values())
    if nt:
        out["mae_thin"] = round(
            sum((v["mae_thin"] or 0) * v["n_thin"] for v in per.values()) / nt, 4
        )
        out["bias_thin"] = round(
            sum((v["bias_thin"] or 0) * v["n_thin"] for v in per.values()) / nt, 4
        )
        out["n_thin"] = nt
    return out


def _read() -> dict:
    return json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}


def _write(rep: dict) -> None:
    OUT.write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


@app.command()
def validate() -> None:
    res = _score(VALID, True, CANDIDATES)
    sel = {
        n: {"pooled": _pool(per), **{str(s): v for s, v in per.items()}} for n, per in res.items()
    }
    for n, v in sel.items():
        _say(f"POOLED {n[:62]:62} {json.dumps(v['pooled'])}")
    chosen = min(sel, key=lambda n: (sel[n]["pooled"]["mae"], n))
    _say(f"chosen: {chosen}")
    rep = _read()
    rep["validation"] = {"candidates": CANDIDATES, "selection": sel, "chosen": chosen,
                         "protocol": "walk-forward 2019-2024, each candidate fitted on the seasons "
                                     "before; chosen by the pooled MAE of next season's contribution "
                                     "per match"}  # fmt: skip
    _write(rep)


@app.command()
def test() -> None:
    rep = _read()
    chosen = rep["validation"]["chosen"]
    ref = next(iter(CANDIDATES))
    kinds = {k: CANDIDATES[k] for k in dict.fromkeys([ref, chosen])}
    res = _score(TEST, False, kinds)
    out = {
        n: {"pooled": _pool(per), **{str(s): v for s, v in per.items()}} for n, per in res.items()
    }
    for n, v in out.items():
        _say(f"TEST {n[:62]:62} {json.dumps(v['pooled'])}")
    rep["test"] = {"protocol": "fitted on the rows up to 2024, scored once on 2025 and 2026",
                   "result": out}  # fmt: skip
    _write(rep)


@app.command()
def ship() -> None:
    import datetime as _dt

    rep = _read()
    chosen = rep["validation"]["chosen"]
    kind = CANDIDATES[chosen]
    allr = _rows()
    full = fit(allr, kind)
    le = fit([r for r in allr if r["season"] <= VALID[-1]], kind)
    out = {"schema": 1, "fitted": _dt.date.today().isoformat(), "chosen": chosen,
           "method": "value used = mu + k (value - mu), k = tau2 / (tau2 + s sd^2 + w_o (1 - IPL "
                     "share) + w_r years since his last season); scripts/value_shrink_fit.py, "
                     "docs/METHODOLOGY.md section 4c",
           "model": None if full is None else {r: m.to_json() for r, m in full.items()},
           "model_le2024": None if le is None else {r: m.to_json() for r, m in le.items()},
           "evaluation": {"validation": rep["validation"]["selection"][chosen]["pooled"],
                          "test": rep.get("test", {}).get("result")}}  # fmt: skip
    shrink.MODEL_PATH.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    _say(f"wrote {shrink.MODEL_PATH}: {json.dumps(out['model'])}")


if __name__ == "__main__":
    app()
