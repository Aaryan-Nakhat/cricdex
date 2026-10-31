"""The time-aware rating (scout/ratings/drift.py): the Kalman shift and likelihood against a
brute-force Gaussian conditioning of the same model, and the selection model's update against a
numerical integration."""

from __future__ import annotations

import math

import numpy as np
import pytest

from cricdesk.scout.ratings import drift

P = drift.GroupParams(mu0=3.0, tau2=80.0, q=6.0, c=900.0, e=15.0,
                      curve=(4.0, 2.5, 1.0, 0.0, -1.0, -4.0, -8.0, -12.0))  # fmt: skip
# (year, value on the IPL scale, balls, league)
OBS = [(2018, 10.0, 300, "ipl"), (2019, -5.0, 120, "ipl"), (2019, 20.0, 200, "bbl"),
       (2021, -12.0, 250, "ipl")]  # fmt: skip


def _seqs(obs, age0: float, first: int, last: int, risk=None, play=None) -> drift.Seqs:
    k = np.zeros(len(obs), dtype=int)
    y = np.array([o[0] - first for o in obs])
    return drift.Seqs(
        [("p1", "batter")], np.array(["bat"], dtype=object), np.array([y.min()]), np.array([age0]),
        np.array([True]), k, y, np.array([o[1] for o in obs], dtype=float),
        np.array([o[2] for o in obs], dtype=float),
        np.array([0.0 if o[3] == "ipl" else 1.0 for o in obs]), np.ones(len(obs)),
        np.array([o[3] for o in obs], dtype=object), first, last, {("p1", "batter"): 0}, risk, play,
    )  # fmt: skip


def _joint(obs, p, age0, first, last, target):
    y0 = min(o[0] for o in obs)
    years = list(range(y0, last + 1)) + ([target] if target else [])
    ages = np.array([age0 + (yr - first) for yr in years])
    A = drift.curve_at(p.curve, ages)
    mean = p.mu0 + A - A[0]
    steps = [yr - y0 for yr in years]
    cov = np.array([[p.tau2 + p.q * min(a, b) for b in steps] for a in steps])
    H = np.zeros((len(obs), len(years)))
    R = np.zeros(len(obs))
    yv = np.zeros(len(obs))
    for j, (yr, v, balls, lg) in enumerate(obs):
        H[j, years.index(yr)] = 1.0
        R[j] = p.c * 100.0 / balls + (p.e if lg != "ipl" else 0.0)
        yv[j] = v
    return years, mean, cov, H, R, yv


def test_shift_matches_brute_force_conditioning():
    first, last, target, age0 = 2010, 2022, 2023, 27.0
    s = _seqs(OBS, age0, first, last)
    shares = {"ipl": 0.7, "bbl": 0.3}
    got = drift.shifts(
        s, drift.DriftModel({"bat": P}, 23.0), {("p1", "batter"): shares}, target, {}
    )
    years, mean, cov, H, R, yv = _joint(OBS, P, age0, first, last, target)
    S = H @ cov @ H.T + np.diag(R)
    K = cov @ H.T @ np.linalg.inv(S)
    m = mean + K @ (yv - H @ mean)
    C = cov - K @ H @ cov
    nl: dict[str, float] = {}
    for _yr, _v, b, lg in OBS:
        nl[lg] = nl.get(lg, 0.0) + b
    a = np.zeros(len(mean))
    a[years.index(target)] = 1.0
    for yr, _v, b, lg in OBS:
        a[years.index(yr)] -= shares[lg] * b / nl[lg]
    sh, var = got[("p1", "batter")]
    assert sh == pytest.approx(float(a @ m), abs=1e-8)
    assert var == pytest.approx(float(a @ C @ a), abs=1e-8)


def test_one_season_shift_is_the_aging_curve():
    p = drift.GroupParams(mu0=0.0, tau2=100.0, q=5.0, c=900.0, e=10.0,
                          curve=(0.0, 0.0, 0.0, 0.0, -2.0, -6.0, -12.0, -20.0))  # fmt: skip
    s = _seqs([(2020, 15.0, 300, "ipl")], 34.0, 2020, 2020)
    sh, _ = drift.shifts(s, drift.DriftModel({"bat": p}, 23.0), {("p1", "batter"): {"ipl": 1.0}},
                         2023, {})[("p1", "batter")]  # fmt: skip
    assert sh == pytest.approx(float(drift.curve_at(p.curve, 37.0) - drift.curve_at(p.curve, 34.0)))


def test_likelihood_matches_brute_force():
    pytest.importorskip("jax")
    first, last, age0 = 2016, 2021, 27.0
    s = _seqs(OBS, age0, first, last)
    f = drift.nll_fn(s, use_sel=False)
    ref = drift.KNOTS.index(drift.AGE_REF)
    z = np.array([P.mu0, math.log(P.tau2), math.log(P.q), math.log(P.c), math.log(P.e)]
                 + [x for i, x in enumerate(P.curve) if i != ref])  # fmt: skip
    _years, mean, cov, H, R, yv = _joint(OBS, P, age0, first, last, None)
    S = H @ cov @ H.T + np.diag(R)
    r = yv - H @ mean
    want = float(np.linalg.slogdet(S)[1] + r @ np.linalg.solve(S, r))
    assert float(f(z)) == pytest.approx(want, rel=1e-9)


def test_a_season_not_played_lowers_the_level_as_the_integral_says():
    """One season played (2018), then a season he was at risk of playing and didn't (2019): the
    shift E[L_2019 − L_2018 | value 2018, not played 2019] from the filter (a moment-matched probit
    update, exact for one update) against a two-dimensional numerical integral."""
    from scipy.stats import norm

    sel = {"bL": 0.05, "bA": [0.0] * len(drift.KNOTS), "b0": {"2018": 1.0, "2019": 0.8}}
    p = drift.GroupParams(mu0=0.0, tau2=100.0, q=20.0, c=900.0, e=10.0, sel=sel)
    risk = np.array([[False, True]])
    play = np.array([[True, False]])
    s = _seqs([(2018, 12.0, 200, "ipl")], 30.0, 2018, 2019, risk, play)
    sh, var = drift.shifts(s, drift.DriftModel({"bat": p}, 23.0), {("p1", "batter"): {"ipl": 1.0}},
                           2019, {})[("p1", "batter")]  # fmt: skip
    # L18 | value: Gaussian; L19 = L18 + N(0, q); weight × P(not played | L19)
    r = p.c * 100.0 / 200
    v18 = 1.0 / (1.0 / p.tau2 + 1.0 / r)
    m18 = v18 * (p.mu0 / p.tau2 + 12.0 / r)
    g18 = np.linspace(m18 - 8 * math.sqrt(v18), m18 + 8 * math.sqrt(v18), 801)
    d = np.linspace(-8 * math.sqrt(p.q), 8 * math.sqrt(p.q), 801)
    L18, D = np.meshgrid(g18, d, indexing="ij")
    w = norm.pdf(L18, m18, math.sqrt(v18)) * norm.pdf(D, 0.0, math.sqrt(p.q))
    w = w * norm.cdf(-(0.8 + 0.05 * (L18 + D)))
    w = w / w.sum()
    mean = float((w * D).sum())
    assert sh == pytest.approx(mean, abs=1e-3)
    assert var == pytest.approx(float((w * D * D).sum()) - mean**2, rel=1e-3)
