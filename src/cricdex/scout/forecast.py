"""Form forecast: a player's value over the next three seasons (docs/METHODOLOGY.md §11).

The quantity is the ratings' `value` - runs per 100 balls above the league's average ball, a wicket
priced at its run cost where he plays (`ratings/runs_value.py`) - projected one, two and three seasons
ahead, with an 80% range and the chance he is still a regular.

History
-------
For every IPL season 2008-2026 and every player, what he actually did that season in that currency
(`runs_value.observed_value` on the season's own tables, so each season is judged against its own
scoring level) and his legal balls. For every season-end t, his rating as it stood then: the model
fitted on matches before the next auction (= everything through season t, nothing after; the price
model's walk-forward cache). Both are leakage-free by construction: a season's value uses only that
season, a rating at t only matches up to t.

What changes from one season to the next
----------------------------------------
Per role (batting value, bowling value), one weighted ridge regression of the value he goes on to post
in season t + k (k = 1, 2, 3, stacked) on what is known at the end of season t:

    rating now (V), one slope per horizon     regression to the mean: V over-separates players,
    V x its posterior sd                      the less so the better he is measured
    a level per horizon
    age in season t + k: linear + a hinge at 32 (one curve shared by the horizons, ages clamped to
    19-40)                                    the aging curve, by role

Sharing the age curve across horizons keeps a player's three seasons on one coherent path. The age terms
are within-player: every row compares a player with his own rating, so the curve is the "delta method"
(Lichtman 2009; Thorley on survivor bias in cricket aging) in regression form. Recent form (each of the
last two seasons against the rating, shrunk by its balls; or the last three pooled), last season's balls, career balls and a finer
age spline were tried on validation origins 2014-2018 (targets up to 2021, before the test seasons):
they added nothing or (for bowlers) made it worse, so the value model leaves them out. They do drive the
playing-time models below. Missing birth dates (~4% of IPL players) are imputed as 23 at IPL debut.

Survivorship. A season's value is only seen for players who play it, and the ones who decline are the
ones who get dropped, so a curve fitted on survivors is too kind to age (the classic survivor bias of
aging curves). The correction is inverse-probability weighting (selection on observables; Hernan &
Robins, *Causal Inference: What If*, ch. 12): a logistic model per horizon gives each player-season the
chance of being observed in t + k (>= 10 balls) from what is known at t (rating, age spline, recent form,
balls last season and in his career, whether he missed last season); each observed row is weighted
1 / that chance (stabilised, capped at 10), so a 36-year-old who survived stands in for the ones who
didn't. Players dropped for reasons not in those features (a bad first half of a season, an injury)
remain a limit - and it bites for bowlers: the ones still picked in their mid-30s are the ones
selectors trust, so their curve RISES past 32, more so after the weighting (which up-weights exactly
those unlikely survivors). Within-player studies find no improvement with age once selection is
modelled (Thorley, Test bowlers), so when a role's curve rises past 32 it is refitted flat there
(the constraint hinge = -linear; `age_curve_flat_after_32` in the output). The opposite bound,
Lichtman's phantom seasons (every player who didn't come back is given the value of a season that got
a player dropped: the mean of the 10-59-ball seasons), is fitted alongside and published as
`phantom_bound` in the age curves, not used for the forecast.

Noise. A 170-ball season's value has a sampling sd of ~23 runs per 100 balls against a spread of true
levels of ~5-9, so the variance of a row is modelled as

    Var = a_k + (dV * V_sd)^2 + c * 100 / n

(dV = the regression's slope on V: the rating's own uncertainty carried forward; a_k = the extra spread
of true levels at horizon k; c * 100 / n = one season's sampling noise at n balls), a_k and c fitted by
maximum likelihood on the residuals, and each row weighted by 1 / Var. The weights use the balls he
actually got, so the median is his value per ball of the balls he actually plays - what reaches the
scoreboard. (Playing time responds to form: a player dropped after a bad start has a short, poor season
that counts for little. Weighting by the balls he was expected to get instead estimates his level per
season regardless of how much he plays; it sits ~10 runs per 100 balls lower and misses the seasons
that matter by more - tried and rejected on the validation origins.)

Outputs per player, role and horizon: the median (the regression's mean), an 80% range for his LEVEL
(median +- 1.28 * sqrt(a_k + (dV * V_sd)^2)), a wider 80% range for ONE SEASON at his usual workload
(adds the sampling noise; this is the range the backtest checks) and P(regular): a logistic model per
horizon on the full feature set, the chance he faces / bowls >= 120 legal balls in that season.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl

# Bump when the method changes (written into forecast_ipl.json and the backtest output).
VERSION = "2026.10-1"
ROLES = ("batter", "bowler")
HORIZONS = (1, 2, 3)
REGULAR_BALLS = 120  # balls in a season that make a regular (20 overs bowled, ~6-8 innings batted)
SEEN_BALLS = 10  # balls in a season for his value that season to count as observed
SHOWN_BALLS = 60  # a role is forecast only if he usually gets this many balls in it a season
FORM_PSEUDO = 250.0  # a season's form is shrunk by n / (n + this)
AGE_KNOTS = (24.0, 28.0, 32.0, 35.0)  # the playing-time models' age spline
VALUE_KNOT = 32.0  # the value model's age hinge
AGE_CENTRE = 28.0
AGE_RANGE = (19.0, 40.0)  # ages are clamped to the range the data covers
DEBUT_AGE = 23.0  # imputed age at IPL debut when the birth date is unknown
IPW_CAP = 10.0
CALIBRATE_FROM = 2012  # first origin of the walk-forward range calibration
Z80 = 1.2815515655446004
HOLD_TOL = 2.0  # runs per 100 balls: a change smaller than this is "holding his level"
ALPHAS = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0)

# The playing-time (selection / regular) models' features.
FEATURES = (
    "v",
    "v_x_sd",
    "lvl",
    "form0",
    "form1",
    "absent0",
    "log_n0",
    "log_career",
    "age",
    *(f"age_gt{int(k)}" for k in AGE_KNOTS),
)
# The value model's features (one column layout for every horizon).
# The value model's columns: the blend (below) with a slope per horizon, a level per horizon and the
# residual age curve. Chosen on the validation origins (see the module docstring).
VALUE_FEATURES: dict[str, tuple[str, ...]] = {
    "batter": ("b_k1", "b_k2", "b_k3", "k2", "k3", "age", "age_gt32"),
    "bowler": ("b_k1", "b_k2", "b_k3", "k2", "k3", "age", "age_gt32"),
}
# Every candidate column `value_design` can build (the rating V, the current level L, ...).
VALUE_CANDIDATES = (
    "v_k1", "v_k2", "v_k3", "v_x_sd", "l_k1", "l_k2", "l_k3", "l_x_sd", "f_k1", "f_k2", "f_k3",
    "b_k1", "b_k2", "b_k3", "k2", "k3", "age", "age_gt32",
)  # fmt: skip
# The blend's weight on the career rating, per role (b = w * rating + (1 - w) * level forecast).
# Chosen on the validation origins 2014-18 by rank correlation (w in 0, 0.25, ..., 1): batters lean
# on their current level, bowlers on the career rating (the level adds nothing for them).
BLEND: dict[str, float] = {"batter": 0.25, "bowler": 1.0}


# ---- history ---------------------------------------------------------------------------------------


def season_history(db_path: Path | str, collection: str, first: int, last: int) -> pl.DataFrame:
    """One row per (player, role, season): `value_obs` (runs per 100 balls above that season's
    average ball, wickets priced at his wicket cost) and `balls` (legal balls)."""
    from cricdex.scout.ratings import runs_value

    rows = []
    for s in range(first, last + 1):
        tab = runs_value.league_tables(
            db_path, collection, since=f"{s}-01-01", before=f"{s + 1}-01-01"
        )
        for role in ROLES:
            ids = list(tab.totals.get(role, {}))
            if not ids:
                continue
            vals = runs_value.observed_value(tab, role, ids)
            for pid, v in zip(ids, vals, strict=True):
                rows.append((pid, role, s, float(v), float(tab.totals[role][pid][:, 3].sum())))
    return pl.DataFrame(
        rows,
        schema={
            "cricsheet_id": pl.String,
            "role": pl.String,
            "season": pl.Int64,
            "value_obs": pl.Float64,
            "balls": pl.Float64,
        },
        orient="row",
    ).filter(pl.col("balls") > 0)


def age_on(dob: str | None, season: int) -> float | None:
    """Age in years at the middle of an IPL season (15 April)."""
    if not dob:
        return None
    try:
        d = _dt.date.fromisoformat(dob[:10])
    except ValueError:
        return None
    return (_dt.date(season, 4, 15) - d).days / 365.25


def states(
    ratings: dict[int, pl.DataFrame],
    history: pl.DataFrame,
    dob: dict[str, str],
    level_params: dict[str, LevelParams] | None = None,
    min_career_balls: float = 30.0,
) -> pl.DataFrame:
    """Every (player, role, season-end t) with what was known at the end of t.

    `ratings[t]`: the ratings fitted on matches through season t (cricsheet_id, role, value,
    value_sd, balls). A player is in the risk set at t when he played (that role) in t or t - 1.
    `lvl` / `lvl_sd`: his current level at t (`levels`, seasons up to t only) under `level_params`
    (default: fitted on the seasons up to the last t; a backtest passes ones fitted before its
    origin). A player with no season of SEEN_BALLS+ yet gets the role's debut prior."""
    last = max(ratings)
    if level_params is None:
        level_params = fit_level_params(history, last, dob)
    lv = levels(history, level_params, last, dob)
    lvmap = {(r[0], r[1], r[2]): r[3:] for r in lv.iter_rows()}
    hist = {(r[0], r[1], r[2]): (r[3], r[4]) for r in history.iter_rows()}
    debut = dict(history.group_by("cricsheet_id").agg(pl.col("season").min()).iter_rows())
    rows = []
    for t, r in sorted(ratings.items()):
        for cid, role, v, vsd, cb in r.select(
            "cricsheet_id", "role", "value", "value_sd", "balls"
        ).iter_rows():
            if role not in ROLES or v is None or (cb or 0) < min_career_balls:
                continue
            y0, n0 = hist.get((cid, role, t), (None, 0.0))
            y1, n1 = hist.get((cid, role, t - 1), (None, 0.0))
            if n0 <= 0 and n1 <= 0:
                continue
            age = age_on(dob.get(cid), t)
            known = age is not None
            if not known:
                age = DEBUT_AGE + t - debut.get(cid, t)
            lp = level_params.get(role)
            sd0 = math.sqrt(lp.tau2) if lp else 30.0
            mu0 = lp.mu0 if lp else float(v)
            prior = (mu0, sd0, mu0, mu0, mu0, sd0, sd0, sd0)
            lvl, lsd, f1, f2, f3, fs1, fs2, fs3 = lvmap.get((cid, role, t), prior)
            rows.append(
                (cid, role, t, float(v), float(vsd or 0.0), float(cb or 0.0),
                 y0 if n0 > 0 else None, float(n0), y1 if n1 > 0 else None, float(n1),
                 float(age), known, float(lvl), float(lsd), f1, f2, f3, fs1, fs2, fs3)
            )  # fmt: skip
    return pl.DataFrame(
        rows,
        schema={
            "cricsheet_id": pl.String,
            "role": pl.String,
            "t": pl.Int64,
            "v": pl.Float64,
            "v_sd": pl.Float64,
            "career_balls": pl.Float64,
            "y0": pl.Float64,
            "n0": pl.Float64,
            "y1": pl.Float64,
            "n1": pl.Float64,
            "age_t": pl.Float64,
            "age_known": pl.Boolean,
            "lvl": pl.Float64,
            "lvl_sd": pl.Float64,
            **{f"f{k}": pl.Float64 for k in HORIZONS},
            **{f"f_sd{k}": pl.Float64 for k in HORIZONS},
        },
        orient="row",
    )


def with_targets(st: pl.DataFrame, history: pl.DataFrame, k: int) -> pl.DataFrame:
    """Add `y` / `n` = what he did in season t + k (n = 0 when he didn't play it)."""
    h = history.select(
        "cricsheet_id",
        "role",
        (pl.col("season") - k).alias("t"),
        pl.col("value_obs").alias("y"),
        pl.col("balls").alias("n"),
    )
    return st.join(h, on=["cricsheet_id", "role", "t"], how="left").with_columns(
        pl.col("n").fill_null(0.0)
    )


# ---- current level (a local-level Kalman filter over his seasons) ------------------------------------


@dataclass
class LevelParams:
    """A player's true level as a random walk with an age drift: each year
    level += d0 + d1 * (age - 28) + d2 * max(age - 32, 0) + N(0, q); his debut level ~ N(mu0, tau2);
    a season's value ~ N(level, c * 100 / balls)."""

    mu0: float
    tau2: float
    q: float
    c: float
    d0: float = 0.0
    d1: float = 0.0
    d2: float = 0.0
    flat_after_32: bool = False  # the drift was held constant past 32 (it wanted to rise)

    def drift(self, age: np.ndarray) -> np.ndarray:
        a = np.clip(age, *AGE_RANGE)
        return self.d0 + self.d1 * (a - AGE_CENTRE) + self.d2 * np.maximum(a - VALUE_KNOT, 0.0)

    def to_json(self) -> dict:
        return {
            k: (v if isinstance(v, bool) else round(float(v), 4)) for k, v in self.__dict__.items()
        }


def _seasons_matrix(
    history: pl.DataFrame, role: str, upto: int, dob: dict[str, str]
) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray, int]:
    """(ids, values [P, S], balls [P, S], ages [P, S], first season) for one role's seasons <= upto
    with at least SEEN_BALLS balls (missing = nan / 0). Unknown ages: DEBUT_AGE at IPL debut."""
    h = history.filter(
        (pl.col("role") == role) & (pl.col("season") <= upto) & (pl.col("balls") >= SEEN_BALLS)
    )
    first = int(history["season"].min())
    debut = dict(history.group_by("cricsheet_id").agg(pl.col("season").min()).iter_rows())
    ids = sorted(set(h["cricsheet_id"].to_list()))
    idx = {c: i for i, c in enumerate(ids)}
    n_s = upto - first + 1
    y = np.full((len(ids), n_s), np.nan)
    n = np.zeros_like(y)
    for cid, s, v, b in h.select("cricsheet_id", "season", "value_obs", "balls").iter_rows():
        y[idx[cid], s - first] = v
        n[idx[cid], s - first] = b
    ages = np.zeros_like(y)
    for i, cid in enumerate(ids):
        a0 = age_on(dob.get(cid), first)
        if a0 is None:
            a0 = DEBUT_AGE + first - debut.get(cid, first)
        ages[i] = a0 + np.arange(n_s)
    return ids, y, n, ages, first


def _filter(
    y: np.ndarray, n: np.ndarray, ages: np.ndarray, p: LevelParams
) -> tuple[np.ndarray, np.ndarray, float]:
    """Kalman filter for every player at once. Returns the filtered mean and variance after each
    season ([P, S], nan before his debut) and the negative log-likelihood of the seasons seen."""
    n_p, n_s = y.shape
    m = np.full(n_p, np.nan)
    v = np.full(n_p, np.nan)
    mean, var = np.full((n_p, n_s), np.nan), np.full((n_p, n_s), np.nan)
    nll = 0.0
    for s in range(n_s):
        started = ~np.isnan(m)
        m[started] += p.drift(ages[started, s])  # a year passes
        v[started] += p.q
        o = ~np.isnan(y[:, s])
        new = o & ~started
        m[new], v[new] = p.mu0, p.tau2
        r = p.c * 100.0 / np.maximum(n[o, s], 1.0)
        sv = v[o] + r
        innov = y[o, s] - m[o]
        nll += float(np.sum(np.log(sv) + innov**2 / sv))
        gain = v[o] / sv
        m[o] = m[o] + gain * innov
        v[o] = (1 - gain) * v[o]
        mean[:, s], var[:, s] = m, v
    return mean, var, nll


def fit_level_params(
    history: pl.DataFrame, upto: int, dob: dict[str, str] | None = None
) -> dict[str, LevelParams]:
    """Maximum-likelihood level-model parameters per role, from the seasons <= upto."""
    from scipy.optimize import minimize

    def mk(x: np.ndarray) -> LevelParams:
        return LevelParams(
            float(x[0]), float(np.exp(x[1])), float(np.exp(x[2])), float(np.exp(x[3])),
            float(x[4]), float(x[5]), float(x[6]),
        )  # fmt: skip

    out = {}
    for role in ROLES:
        _, y, n, ages, _ = _seasons_matrix(history, role, upto, dob or {})
        if y.size == 0:
            continue

        def nll(x: np.ndarray, y=y, n=n, ages=ages) -> float:
            return _filter(y, n, ages, mk(x))[2]

        def solve(f, x0s):
            best = None
            for x0 in x0s:
                res = minimize(
                    f,
                    np.array(x0),
                    method="Nelder-Mead",
                    options={"maxiter": 8000, "maxfev": 8000, "xatol": 1e-5, "fatol": 1e-6},
                )
                if best is None or res.fun < best.fun:
                    best = res
            return best.x

        starts = [
            [-5.0, math.log(60.0), math.log(q0), math.log(1000.0), 0.0, 0.0, 0.0]
            for q0 in (3.0, 15.0)
        ]
        x = solve(nll, starts)
        flat = False
        if x[5] + x[6] > 0:
            # the drift may not rise with age past 32 (survivors; see the module docstring):
            # refit with the drift constant past 32 (d2 = -d1)
            def nll_flat(z: np.ndarray) -> float:
                return nll(np.concatenate([z, [-z[5]]]))

            z = solve(nll_flat, [s0[:6] for s0 in starts])
            x = np.concatenate([z, [-z[5]]])
            flat = True
        out[role] = mk(x)
        out[role].flat_after_32 = flat
    return out


def levels(
    history: pl.DataFrame,
    params: dict[str, LevelParams],
    upto: int,
    dob: dict[str, str] | None = None,
) -> pl.DataFrame:
    """Each player's filtered level (and sd) at the end of every season t <= upto, from his seasons
    up to t only (a missed season adds a year's drift), and the level model's own forecast 1-3 years
    on (`f1..f3`: the level plus the age drift; `f_sd1..3`: its sd)."""
    rows = []
    for role, p in params.items():
        ids, y, n, ages, first = _seasons_matrix(history, role, upto, dob or {})
        mean, var, _ = _filter(y, n, ages, p)
        for i in range(mean.shape[0]):
            for s in range(mean.shape[1]):
                if np.isnan(mean[i, s]):
                    continue
                f, fs = [], []
                m = mean[i, s]
                for k in HORIZONS:
                    m = m + float(p.drift(np.array([ages[i, s] + k]))[0])
                    f.append(m)
                    fs.append(math.sqrt(var[i, s] + k * p.q))
                rows.append(
                    (ids[i], role, first + s, float(mean[i, s]), float(math.sqrt(var[i, s])),
                     *f, *fs)
                )  # fmt: skip
    return pl.DataFrame(
        rows,
        schema={
            "cricsheet_id": pl.String,
            "role": pl.String,
            "t": pl.Int64,
            "lvl": pl.Float64,
            "lvl_sd": pl.Float64,
            **{f"f{k}": pl.Float64 for k in HORIZONS},
            **{f"f_sd{k}": pl.Float64 for k in HORIZONS},
        },
        orient="row",
    )


# ---- design ----------------------------------------------------------------------------------------


def _form(y: np.ndarray, n: np.ndarray, v: np.ndarray) -> np.ndarray:
    w = n / (n + FORM_PSEUDO)
    return np.where(n > 0, w * (np.nan_to_num(y) - v), 0.0)


def _age(st: pl.DataFrame, k: int) -> np.ndarray:
    return np.clip(st["age_t"].to_numpy().astype(float) + k, *AGE_RANGE)


def design(st: pl.DataFrame, k: int) -> np.ndarray:
    """The playing-time models' feature matrix (rows of `st`, columns FEATURES) for horizon k."""
    v = st["v"].to_numpy()
    vsd = st["v_sd"].to_numpy()
    n0 = st["n0"].to_numpy()
    n1 = st["n1"].to_numpy()
    age = _age(st, k)
    cols = [
        v,
        v * vsd / 10.0,
        st["lvl"].to_numpy(),
        _form(st["y0"].to_numpy().astype(float), n0, v),
        _form(st["y1"].to_numpy().astype(float), n1, v),
        (n0 <= 0).astype(float),
        np.log1p(n0),
        np.log1p(st["career_balls"].to_numpy()),
        age - AGE_CENTRE,
        *(np.maximum(age - kn, 0.0) for kn in AGE_KNOTS),
    ]
    return np.column_stack(cols)


def value_design(st: pl.DataFrame, k: int, feats: tuple[str, ...]) -> np.ndarray:
    """The value model's feature matrix (columns `feats`, from VALUE_CANDIDATES) for horizon k."""
    v, vsd = st["v"].to_numpy(), st["v_sd"].to_numpy()
    lv, lsd = st["lvl"].to_numpy(), st["lvl_sd"].to_numpy()
    age = _age(st, k)
    one = np.ones_like(v)
    cols = {
        **{f"v_k{h}": v * (k == h) for h in HORIZONS},
        "v_x_sd": v * vsd / 10.0,
        **{f"l_k{h}": lv * (k == h) for h in HORIZONS},
        **{f"f_k{h}": st[f"f{k}"].to_numpy() * (k == h) for h in HORIZONS},
        **{f"b_k{h}": _blend(st, k) * (k == h) for h in HORIZONS},
        "l_x_sd": lv * lsd / 10.0,
        "k2": one * (k == 2),
        "k3": one * (k == 3),
        "age": age - AGE_CENTRE,
        "age_gt32": np.maximum(age - VALUE_KNOT, 0.0),
    }
    return np.column_stack([cols[f] for f in feats]).astype(float)


def _blend_weight(st: pl.DataFrame) -> np.ndarray:
    """Per row, the weight on the career rating in the blend (BLEND, by role)."""
    return np.array([BLEND.get(r, 0.0) for r in st["role"].to_list()])


def _blend(st: pl.DataFrame, k: int) -> np.ndarray:
    """w x career rating + (1 - w) x the level model's forecast k seasons on."""
    w = _blend_weight(st)
    return w * st["v"].to_numpy() + (1 - w) * st[f"f{k}"].to_numpy()


def _sds(st: pl.DataFrame, k: int) -> np.ndarray:
    """[N, 4]: the sd of the rating, of the current level, of the level model's forecast k seasons
    on, and of the blend, per row."""
    w = _blend_weight(st)
    vsd, fsd = st["v_sd"].to_numpy(), st[f"f_sd{k}"].to_numpy()
    return np.column_stack(
        [vsd, st["lvl_sd"].to_numpy(), fsd, np.sqrt((w * vsd) ** 2 + ((1 - w) * fsd) ** 2)]
    )


# ---- estimators ------------------------------------------------------------------------------------


def ridge(X: np.ndarray, y: np.ndarray, w: np.ndarray, alpha: float) -> np.ndarray:
    """Weighted ridge with an unpenalised intercept; features standardised inside. Returns
    [intercept, *coefs] on the original feature scale."""
    w = w / w.mean()
    mu = (X * w[:, None]).sum(0) / w.sum()
    sd = np.sqrt(((X - mu) ** 2 * w[:, None]).sum(0) / w.sum())
    sd = np.where(sd > 1e-9, sd, 1.0)
    Z = (X - mu) / sd
    ym = float((y * w).sum() / w.sum())
    A = Z.T @ (Z * w[:, None]) + alpha * np.eye(Z.shape[1])
    b = np.linalg.solve(A, Z.T @ (w * (y - ym)))
    coef = b / sd
    return np.concatenate([[ym - float(mu @ coef)], coef])


def predict(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return beta[0] + X @ beta[1:]


def logistic(X: np.ndarray, y: np.ndarray, alpha: float = 1.0, iters: int = 50) -> np.ndarray:
    """L2-penalised logistic regression by Newton-Raphson (standardised features, intercept free)."""
    mu = X.mean(0)
    sd = X.std(0)
    sd = np.where(sd > 1e-9, sd, 1.0)
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    b = np.zeros(Z.shape[1])
    pen = np.full(Z.shape[1], alpha)
    pen[0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(Z @ b, -30, 30)))
        g = Z.T @ (y - p) - pen * b
        H = (Z * (p * (1 - p))[:, None]).T @ Z + np.diag(pen) + 1e-9 * np.eye(len(b))
        step = np.linalg.solve(H, g)
        b += step
        if np.max(np.abs(step)) < 1e-8:
            break
    coef = b[1:] / sd
    return np.concatenate([[b[0] - float(mu @ coef)], coef])


def prob(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(predict(beta, X), -30, 30)))


def variance_params(
    r: np.ndarray, known: np.ndarray, n: np.ndarray, group: np.ndarray, w: np.ndarray
) -> tuple[dict[int, float], float]:
    """MLE of a_g (one per group) and c in Var(residual) = a_g + known + c * 100 / n, weighted by w."""
    from scipy.optimize import minimize

    w = w / w.mean()
    x = 100.0 / np.maximum(n, 1.0)
    groups = sorted({int(g) for g in group})
    gi = np.searchsorted(groups, group)

    def nll(p: np.ndarray) -> float:
        var = np.exp(p[:-1])[gi] + known + np.exp(p[-1]) * x
        return float((w * (np.log(var) + r**2 / var)).sum())

    best = None
    for a0, c0 in ((30.0, 800.0), (3.0, 500.0)):
        start = np.array([math.log(a0)] * len(groups) + [math.log(c0)])
        res = minimize(
            nll,
            start,
            method="Nelder-Mead",
            options={"maxiter": 8000, "xatol": 1e-7, "fatol": 1e-9},
        )
        if best is None or res.fun < best.fun:
            best = res
    a = {g: float(np.exp(best.x[i])) for i, g in enumerate(groups)}
    return a, float(np.exp(best.x[-1]))


def _slope(
    beta: np.ndarray, feats: tuple[str, ...], k: int, sd: np.ndarray, src: str = "l"
) -> np.ndarray:
    """d(median)/d(source) at horizon k: source "v" = the rating, "l" = the current level."""
    if f"{src}_k{k}" not in feats:
        return np.zeros_like(sd)
    out = beta[1 + feats.index(f"{src}_k{k}")] + np.zeros_like(sd)
    if f"{src}_x_sd" in feats:
        out = out + beta[1 + feats.index(f"{src}_x_sd")] * sd / 10.0
    return out


def _known(beta: np.ndarray, feats: tuple[str, ...], k: np.ndarray, sds: np.ndarray) -> np.ndarray:
    """The inputs' own uncertainty carried into the forecast: sum of (slope x sd)^2 over the
    rating and the current level (whichever the model uses)."""
    out = np.zeros(len(k))
    for j, src in enumerate(("v", "l", "f", "b")):
        for h in np.unique(k):
            m = k == h
            out[m] += (_slope(beta, feats, int(h), sds[m, j], src) * sds[m, j]) ** 2
    return out


@dataclass
class RoleModel:
    role: str
    beta: np.ndarray  # value regression: intercept + VALUE_FEATURES
    seen: dict[int, np.ndarray]  # per k, logistic on FEATURES: P(plays >= SEEN_BALLS in t + k)
    regular: dict[int, np.ndarray]  # per k, logistic on FEATURES: P(plays >= REGULAR_BALLS)
    a: dict[int, float]  # per k, extra variance of his level
    c: float  # one season's sampling noise x 100 / balls
    alpha: float
    n_rows: dict[int, int]
    n_seen: dict[int, int]
    naive_beta: np.ndarray = field(default_factory=lambda: np.zeros(0))  # same, no IPW
    shift: float = 0.0  # variance of a whole season's shift (added to every range)
    features: tuple[str, ...] = ()  # the value regression's columns (VALUE_FEATURES[role])
    scale: dict[int, float] = field(default_factory=lambda: dict.fromkeys(HORIZONS, 1.0))
    # The pessimistic bound on survivorship (Lichtman's phantom seasons; `fit_role(bound=True)`).
    flat_after_knot: bool = False  # the age curve was held flat past 32 (it wanted to rise)
    phantom_beta: np.ndarray | None = None
    replacement: float | None = None  # the phantom seasons' value

    def median(self, st: pl.DataFrame, k: int) -> np.ndarray:
        return predict(self.beta, value_design(st, k, self.features))

    def level_var(self, st: pl.DataFrame, k: int) -> np.ndarray:
        return (
            self.a[k]
            + self.shift
            + _known(self.beta, self.features, np.full(st.height, k), _sds(st, k))
        )

    def p_regular(self, st: pl.DataFrame, k: int) -> np.ndarray:
        return prob(self.regular[k], design(st, k))

    def p_plays(self, st: pl.DataFrame, k: int) -> np.ndarray:
        return prob(self.seen[k], design(st, k))

    def to_json(self) -> dict:
        def r(x: Iterable[float]) -> list[float]:
            return [round(float(v), 5) for v in x]

        return {
            "role": self.role,
            "features": ["intercept", *self.features],
            "beta": r(self.beta),
            "beta_no_survivor_correction": r(self.naive_beta),
            "playing_time_features": ["intercept", *FEATURES],
            "p_plays": {str(k): r(b) for k, b in self.seen.items()},
            "p_regular": {str(k): r(b) for k, b in self.regular.items()},
            "var_level": {str(k): round(v, 3) for k, v in self.a.items()},
            "var_noise_per_100_balls": round(self.c, 2),
            "var_season_shift": round(self.shift, 3),
            "range_scale": {str(k): round(v, 3) for k, v in self.scale.items()},
            "age_curve_flat_after_32": self.flat_after_knot,
            "alpha": self.alpha,
            "n_rows": {str(k): v for k, v in self.n_rows.items()},
            "n_seen": {str(k): v for k, v in self.n_seen.items()},
        }


def _wls(
    feats: tuple[str, ...],
    X: np.ndarray,
    y: np.ndarray,
    sds: np.ndarray,
    n: np.ndarray,
    k: np.ndarray,
    ipw: np.ndarray,
    alpha: float,
) -> tuple[np.ndarray, dict[int, float], float]:
    """Ridge -> variance MLE -> re-weighted ridge (two passes)."""
    a = {int(h): 30.0 for h in np.unique(k)}
    c = 800.0
    ak = np.array([a[int(h)] for h in k])
    beta = ridge(X, y, ipw / (ak + c * 100 / n), alpha)
    for _ in range(2):
        known = _known(beta, feats, k, sds)
        a, c = variance_params(y - predict(beta, X), known, n, k, np.ones_like(ipw))
        ak = np.array([a[int(h)] for h in k])
        beta = ridge(X, y, ipw / (ak + known + c * 100 / n), alpha)
    return beta, a, c


def _choose_alpha(
    X: np.ndarray, y: np.ndarray, n: np.ndarray, ipw: np.ndarray, groups: np.ndarray
) -> float:
    """Ridge penalty by leave-one-target-season-out, scored by the weighted squared error."""
    w = ipw / (30.0 + 800.0 * 100 / n)
    best, best_err = ALPHAS[0], math.inf
    for alpha in ALPHAS:
        err = 0.0
        for g in np.unique(groups):
            tr, te = groups != g, groups == g
            if tr.sum() < 50 or te.sum() == 0:
                continue
            b = ridge(X[tr], y[tr], w[tr], alpha)
            err += float((w[te] * (y[te] - predict(b, X[te])) ** 2).sum())
        if err < best_err:
            best, best_err = alpha, err
    return best


def fit_role(
    st: pl.DataFrame, history: pl.DataFrame, role: str, last_target: int, bound: bool = False
) -> RoleModel:
    """Fit one role on every (t, t + k) pair with t + k <= last_target, k = 1, 2, 3. With `bound`,
    also the phantom-season fit (see `RoleModel.phantom_beta`)."""
    feats = VALUE_FEATURES[role]
    blocks, unseen = [], []
    seen_b, reg_b, n_rows, n_seen = {}, {}, {}, {}
    for k in HORIZONS:
        d = with_targets(
            st.filter((pl.col("role") == role) & (pl.col("t") + k <= last_target)), history, k
        )
        if d.height == 0:
            continue
        X = design(d, k)
        n = d["n"].to_numpy()
        seen = n >= SEEN_BALLS
        seen_b[k] = logistic(X, seen.astype(float))
        reg_b[k] = logistic(X, (n >= REGULAR_BALLS).astype(float))
        p = np.clip(prob(seen_b[k], X), 1e-3, 1.0)
        ipw = np.minimum(seen.mean() / p, IPW_CAP)
        ds = d.filter(pl.Series(seen))
        du = d.filter(~pl.Series(seen))
        unseen.append((value_design(du, k, feats), _sds(du, k), np.full(du.height, k)))
        blocks.append(
            (
                value_design(ds, k, feats),
                ds["y"].to_numpy(),
                _sds(ds, k),
                ds["n"].to_numpy(),
                np.full(ds.height, k),
                ipw[seen],
                (ds["t"].to_numpy() + k),
            )
        )
        n_rows[k], n_seen[k] = d.height, int(seen.sum())
    if not blocks:
        raise ValueError(f"no {role} seasons to fit before {last_target}")
    X, y, sds, n, kk, ipw, groups = (np.concatenate(z) for z in zip(*blocks, strict=True))
    alpha = _choose_alpha(X, y, n, ipw, groups)
    beta, a, c = _wls(feats, X, y, sds, n, kk, ipw, alpha)
    flat = False
    has_age = "age" in feats and "age_gt32" in feats
    ia = 1 + feats.index("age") if has_age else 0
    ih = 1 + feats.index("age_gt32") if has_age else 0
    if has_age and beta[ia] + beta[ih] > 0:
        # no improvement with age past 32 (see the module docstring): refit with the curve flat
        # there, i.e. the constraint beta_hinge = -beta_age
        X2 = X.copy()
        X2[:, ia - 1] = X[:, ia - 1] - X[:, ih - 1]
        X2[:, ih - 1] = 0.0
        beta, a, c = _wls(feats, X2, y, sds, n, kk, ipw, alpha)
        beta[ih] = -beta[ia]
        flat = True
    naive, _, _ = _wls(feats, X, y, sds, n, kk, np.ones_like(ipw), alpha)
    shift = season_shift_var(y - predict(beta, X), n, groups, c)
    model = RoleModel(role, beta, seen_b, reg_b, a, c, alpha, n_rows, n_seen, naive, shift)
    model.features = feats
    model.flat_after_knot = flat
    if bound:
        # Lichtman's phantom seasons: every player who didn't come back is given the season of a
        # player who gets dropped (the mean value of the 10-59-ball seasons), at 60 balls' noise
        short = n < 60
        repl = float(y[short].mean()) if short.any() else float(np.percentile(y, 20))
        Xu, vu, ku = (np.concatenate(z) for z in zip(*unseen, strict=True))
        model.replacement = repl
        model.phantom_beta, _, _ = _wls(
            feats,
            np.vstack([X, Xu]),
            np.concatenate([y, np.full(len(Xu), repl)]),
            np.concatenate([sds, vu]),
            np.concatenate([n, np.full(len(Xu), 60.0)]),
            np.concatenate([kk, ku]),
            np.ones(len(X) + len(Xu)),
            alpha,
        )
    return model


def season_shift_var(r: np.ndarray, n: np.ndarray, season: np.ndarray, c: float) -> float:
    """How much a whole season's players move together: the variance of the per-season mean residual
    (balls-weighted) beyond what its sampling noise explains. A forecast can't know next season's
    shift, so it is added to the ranges."""
    means, noise = [], []
    for g in np.unique(season):
        s = season == g
        w = n[s] / n[s].sum()
        means.append(float(w @ r[s]))
        noise.append(float((w**2 * (c * 100.0 / n[s])).sum()))
    if len(means) < 3:
        return 0.0
    return max(float(np.var(means, ddof=1)) - float(np.mean(noise)), 0.0)


def fit_all(
    st: pl.DataFrame,
    history: pl.DataFrame,
    last_target: int,
    calibrate: bool = True,
    bound: bool = False,
) -> dict[str, RoleModel]:
    """Both roles' models on every pair up to `last_target`; with `calibrate`, the 80% ranges are
    rescaled by `interval_scales` (walk-forward, from seasons up to `last_target` only)."""
    have = set(st["role"].unique().to_list())
    models = {r: fit_role(st, history, r, last_target, bound) for r in ROLES if r in have}
    if calibrate:
        for (role, k), sc in interval_scales(st, history, last_target).items():
            models[role].scale[k] = sc
    return models


def interval_scales(
    st: pl.DataFrame, history: pl.DataFrame, last_target: int, first_origin: int = CALIBRATE_FROM
) -> dict[tuple[str, int], float]:
    """Walk-forward calibration of the one-season 80% range (split-conformal over time): for every
    earlier origin T' (models fitted on seasons <= T' only), how far the seasons T' + k <= last_target
    actually fell from the median in units of the predicted sd, among seasons of 60+ balls. The scale
    is the 80th percentile of |z| over 1.28 (clipped to 0.8-1.6; 1 with too few rows): > 1 means the
    model's own ranges were too narrow out of sample."""
    zs: dict[tuple[str, int], list[float]] = {}
    for T in range(first_origin, last_target):
        models = fit_all(st, history, T, calibrate=False)
        for role, m in models.items():
            now = st.filter((pl.col("t") == T) & (pl.col("role") == role))
            for k in HORIZONS:
                if T + k > last_target:
                    continue
                d = with_targets(now, history, k).filter(pl.col("n") >= 60)
                if d.height == 0:
                    continue
                sd = np.sqrt(m.level_var(d, k) + m.c * 100.0 / d["n"].to_numpy())
                zs.setdefault((role, k), []).extend(np.abs(d["y"].to_numpy() - m.median(d, k)) / sd)
    out = {}
    for role in sorted({r for r, _ in zs}):
        for k in HORIZONS:
            z = np.array(zs.get((role, k), []))
            out[(role, k)] = (
                float(np.clip(np.quantile(z, 0.8) / Z80, 0.8, 1.6)) if len(z) >= 100 else 1.0
            )
    return out


# ---- projection ------------------------------------------------------------------------------------


def typical_balls(history: pl.DataFrame, cid: str, role: str, upto: int) -> float:
    """His usual balls in a season he plays: the mean of his last three seasons with balls."""
    h = history.filter(
        (pl.col("cricsheet_id") == cid) & (pl.col("role") == role) & (pl.col("season") <= upto)
    ).sort("season")
    b = h["balls"].to_numpy()[-3:]
    return float(b.mean()) if len(b) else 0.0


def project(
    models: dict[str, RoleModel], st: pl.DataFrame, usual_balls: np.ndarray | None = None
) -> pl.DataFrame:
    """Median, level and one-season 80% ranges, P(regular) for every row of `st` (one origin t)
    and horizon. `usual_balls` (per row) sets the one-season noise (clipped to 60-400; default 150)."""
    out = []
    ub = np.clip(usual_balls if usual_balls is not None else np.full(st.height, 150.0), 60, 400)
    for role in ROLES:
        mask = (st["role"] == role).to_numpy()
        if not mask.any() or role not in models:
            continue
        m = models[role]
        sub = st.filter(pl.Series(mask))
        for k in HORIZONS:
            mu = m.median(sub, k)
            var = m.level_var(sub, k)
            lvl = m.scale[k] * np.sqrt(var)
            ssn = m.scale[k] * np.sqrt(var + m.c * 100.0 / ub[mask])
            out.append(
                sub.select("cricsheet_id", "role", "t", "v", "v_sd", "age_t").with_columns(
                    pl.lit(k).alias("k"),
                    pl.Series("median", mu),
                    pl.Series("lo", mu - Z80 * lvl),
                    pl.Series("hi", mu + Z80 * lvl),
                    pl.Series("season_lo", mu - Z80 * ssn),
                    pl.Series("season_hi", mu + Z80 * ssn),
                    pl.Series("p_regular", m.p_regular(sub, k)),
                    pl.Series("p_plays", m.p_plays(sub, k)),
                )
            )
    return pl.concat(out) if out else pl.DataFrame()


def _num(x: float) -> str:
    r = math.floor(x + 0.5)  # half up, as the site's Math.round
    return "0" if r == 0 else f"{r:+d}".replace("-", "−")


def outlook(
    medians: Iterable[float],
    now: float,
    p_regular: Iterable[float] | None = None,
    regular_now: bool = False,
    seasons: Iterable[int] | None = None,
) -> dict:
    """A plain-English line, a one-word flag and the three-season average from the medians
    (t+1, t+2, t+3) and his current level (`now`).

    The line states next season against his current level; the shape compares the later seasons
    with next season: a change within HOLD_TOL runs per 100 balls is holding."""
    m = [float(x) for x in medians]
    yrs = list(seasons) if seasons is not None else [None, None, None]
    d2, d3 = m[1] - m[0], m[2] - m[0]
    if d2 <= -HOLD_TOL:
        flag, shape = "decline", "then likely to decline"
    elif d3 <= -HOLD_TOL:
        flag, shape = "hold_then_decline", "likely to hold that for two seasons, then decline"
    elif d3 >= HOLD_TOL:
        flag, shape = "improve", "then likely to improve"
    else:
        flag, shape = "hold", "then likely to hold that level"
    by = f" by {yrs[2]}" if yrs[2] else " in three seasons"
    tail = f" ({_num(m[2])}{by})" if flag != "hold" else (f" through {yrs[2]}" if yrs[2] else "")
    text = f"About {_num(m[0])} next season (current level {_num(now)}), {shape}{tail}"
    if p_regular is not None and regular_now:
        for i, p in enumerate(float(x) for x in p_regular):
            if p < 0.5:
                when = f"in {yrs[i]}" if yrs[i] else f"{i + 1} season{'s' if i else ''} on"
                text += f"; only a {math.floor(p * 100 + 0.5)}% chance he is still a regular {when}"
                break
    return {"flag": flag, "text": text + ".", "avg3": round(sum(m) / len(m), 1)}


# ---- backtest helpers --------------------------------------------------------------------------------


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return float("nan")
    ra = pl.Series(a).rank("average").to_numpy()
    rb = pl.Series(b).rank("average").to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def naive_age_curve(
    st: pl.DataFrame, history: pl.DataFrame, role: str, last_target: int, min_balls: float = 60.0
) -> dict[int, float]:
    """The classic survivor-biased curve: the mean change in season value from age a to a + 1 among
    players with >= min_balls in both seasons (ages pooled +-1 year, >= 20 pairs else 0)."""
    d = with_targets(
        st.filter((pl.col("role") == role) & (pl.col("t") + 1 <= last_target)), history, 1
    )
    d = d.filter((pl.col("n") >= min_balls) & (pl.col("n0") >= min_balls) & pl.col("age_known"))
    a = np.floor(d["age_t"].to_numpy()).astype(int)
    delta = d["y"].to_numpy() - d["y0"].to_numpy()
    out = {}
    for age in range(17, 46):
        sel = np.abs(a - age) <= 1
        out[age] = float(delta[sel].mean()) if sel.sum() >= 20 else 0.0
    return out


# ---- the shipped forecast ---------------------------------------------------------------------------


def age_curves(models: dict[str, RoleModel], ages: Iterable[int] = range(20, 41)) -> dict:
    """The value model's age curve per role (value at age a minus value at 28, same rating), with
    and without the survivorship correction."""
    ages = list(ages)

    def curve(beta: np.ndarray, i: int, j: int) -> list[float]:
        def f(a: float) -> float:
            a = min(max(a, AGE_RANGE[0]), AGE_RANGE[1])
            return beta[i] * (a - AGE_CENTRE) + beta[j] * max(a - VALUE_KNOT, 0.0)

        return [round(float(f(a) - f(AGE_CENTRE)), 2) for a in ages]

    out: dict = {"ages": ages}
    for role, m in models.items():
        if "age" not in m.features or "age_gt32" not in m.features:
            continue
        i, j = 1 + m.features.index("age"), 1 + m.features.index("age_gt32")
        out[role] = {
            "corrected": curve(m.beta, i, j),
            "survivors_only": curve(m.naive_beta, i, j),
        }
        if m.phantom_beta is not None:
            out[role]["phantom_bound"] = curve(m.phantom_beta, i, j)
            out[role]["phantom_value"] = round(float(m.replacement), 1)
    return out


def build_forecast(
    ratings: dict[int, pl.DataFrame],
    history: pl.DataFrame,
    dob: dict[str, str],
    last: int,
    exclude: Iterable[str] = (),
) -> dict:
    """Train on every season pair up to `last` and project everyone in the risk set at `last`
    (played that role in `last` or the season before, usually SHOWN_BALLS+ balls a season in it),
    with `ratings[last]` as his rating now. `exclude`: ids not to project (retired players)."""
    lp = fit_level_params(history, last, dob)
    st = states(ratings, history, dob, lp)
    models = fit_all(st, history, last, bound=True)
    now = st.filter(pl.col("t") == last)
    usual = np.array([
        typical_balls(history, cid, role, last)
        for cid, role in now.select("cricsheet_id", "role").iter_rows()
    ])  # fmt: skip
    gone = set(exclude)
    keep = (usual >= SHOWN_BALLS) & ~now["cricsheet_id"].is_in(list(gone)).to_numpy()
    now, usual = now.filter(pl.Series(keep)), usual[keep]
    proj = project(models, now, usual)
    keys = list(now.select("cricsheet_id", "role").iter_rows())
    usual_by = dict(zip(keys, usual, strict=True))
    rows = {(r["cricsheet_id"], r["role"]): r for r in now.iter_rows(named=True)}
    players: dict[str, dict] = {}
    for (cid, role), g in proj.sort("k").group_by(["cricsheet_id", "role"], maintain_order=True):
        row = rows[(cid, role)]
        regular_now = row["n0"] >= REGULAR_BALLS
        seasons = [last + int(k) for k in g["k"]]
        p = players.setdefault(cid, {"roles": {}})
        p["roles"][role] = {
            "now": round(row["v"], 1),
            "now_sd": round(row["v_sd"], 1),
            "level": round(row["lvl"], 1),
            "level_sd": round(row["lvl_sd"], 1),
            "recent": [
                [int(s), round(float(y), 1), int(b)]
                for s, y, b in history.filter(
                    (pl.col("cricsheet_id") == cid)
                    & (pl.col("role") == role)
                    & (pl.col("season") > last - 3)
                )
                .sort("season")
                .select("season", "value_obs", "balls")
                .iter_rows()
            ],
            "age": round(row["age_t"], 1) if row["age_known"] else None,
            "balls_last": int(row["n0"]),
            "usual_balls": int(round(usual_by[(cid, role)])),
            "regular_now": bool(regular_now),
            "seasons": [
                {
                    "season": last + int(r["k"]),
                    "median": round(r["median"], 1),
                    "lo": round(r["lo"], 1),
                    "hi": round(r["hi"], 1),
                    "season_lo": round(r["season_lo"], 1),
                    "season_hi": round(r["season_hi"], 1),
                    "p_regular": round(r["p_regular"], 2),
                }
                for r in g.iter_rows(named=True)
            ],
            # the line is written from the same rounded numbers the file (and the page) show
            **outlook(
                [round(x, 1) for x in g["median"]],
                round(row["lvl"], 1),
                [round(x, 2) for x in g["p_regular"]],
                regular_now,
                seasons,
            ),
        }
    return {
        "collection": "ipl",
        "as_of_season": last,
        "forecast_version": VERSION,
        "unit": "runs per 100 balls above the average ball",
        "regular_balls": REGULAR_BALLS,
        "level_params": {r: p.to_json() for r, p in lp.items()},
        "level_drift_by_age": {
            "ages": list(range(20, 41)),
            **{
                r: [round(float(p.drift(np.array([a]))[0]), 2) for a in range(20, 41)]
                for r, p in lp.items()
            },
        },
        "models": [m.to_json() for m in models.values()],
        "age_curves": age_curves(models),
        "players": players,
    }


SITE_COLUMNS = ("season", "median", "lo", "hi", "season_lo", "season_hi", "p_regular")


def export_site(src: Path, dest: Path) -> Path:
    """The site's `forecast.json`: per player and role his rating now, the outlook and the three
    seasons as rows of SITE_COLUMNS."""
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    players = {
        cid: {
            role: {
                "now": r["now"],
                "now_sd": r["now_sd"],
                "level": r["level"],
                "level_sd": r["level_sd"],
                "recent": r["recent"],
                "age": r["age"],
                "flag": r["flag"],
                "text": r["text"],
                "avg3": r["avg3"],
                "regular_now": r["regular_now"],
                "s": [[s[c] for c in SITE_COLUMNS] for s in r["seasons"]],
            }
            for role, r in p["roles"].items()
        }
        for cid, p in data["players"].items()
    }
    out = {
        "as_of_season": data["as_of_season"],
        "version": data["forecast_version"],
        "unit": data["unit"],
        "regular_balls": data["regular_balls"],
        "columns": list(SITE_COLUMNS),
        "age_curves": data.get("age_curves"),
        "players": players,
    }
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    return dest


KEEP_ROLE = {"batter": ("batter",), "keeper": ("batter",), "bowler": ("bowler",)}


def keep_outlook(data: dict | None, cid: str | None, role: str) -> dict | None:
    """Keep or release's "3-season outlook" for a squad player, from forecast_ipl.json: his
    batting forecast for batters and keepers, bowling for bowlers, and for an all-rounder the role
    with the higher three-season average. None when he has no forecast."""
    if not data or not cid:
        return None
    roles = (data.get("players") or {}).get(cid, {}).get("roles") or {}
    options = [r for r in KEEP_ROLE.get(role, ("batter", "bowler")) if r in roles]
    if not options:
        return None
    pick = max(options, key=lambda r: roles[r]["avg3"])
    r = roles[pick]
    return {
        "role": pick,
        "seasons": [s["season"] for s in r["seasons"]],
        "median": [s["median"] for s in r["seasons"]],
        "avg3": r["avg3"],
        "flag": r["flag"],
        "p_regular_last": r["seasons"][-1]["p_regular"],
        "level": r.get("level"),
        "text": r["text"],
    }
