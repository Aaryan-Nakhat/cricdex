"""Form forecast (cricdex.scout.forecast): the projection math on synthetic careers, the plain-English
outlook, and the schemas of the backtest output and the site's forecast.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from cricdex.scout import forecast as F

ROOT = Path(__file__).resolve().parents[1]


def _synthetic(seed: int = 0, n_players: int = 600, drop_old: bool = False):
    """Careers where next season's value = 2 + 0.7 * rating - 1.0 per year past 30 (+ noise), with
    sampling noise 900 * 100 / balls. With `drop_old`, players past 33 who are having a bad time are
    usually not picked again (survivorship)."""
    import datetime as dt

    rng = np.random.default_rng(seed)
    hist, ratings, dob = [], {}, {}
    for t in range(2008, 2027):
        ratings[t] = []
    for i in range(n_players):
        cid = f"p{i:04d}"
        talent = rng.normal(0, 8)
        start = int(rng.integers(2008, 2020))
        age0 = float(rng.uniform(19, 33))
        dob[cid] = (dt.date(start, 4, 15) - dt.timedelta(days=round(age0 * 365.25))).isoformat()
        for t in range(start, min(start + 10, 2027)):
            age = age0 + (t - start)
            level = talent - 1.0 * max(age - 30, 0)
            balls = float(rng.integers(60, 300))
            y = 2 + 0.7 * level + rng.normal(0, np.sqrt(900 * 100 / balls))
            if drop_old and age > 33 and y < -5 and rng.random() < 0.8:
                break
            hist.append((cid, "batter", t, y, balls))
            sd = float(rng.uniform(1, 4))
            ratings[t].append(
                (cid, "batter", level + rng.normal(0, sd), sd, balls * (t - start + 1))
            )
    history = pl.DataFrame(
        hist, schema=["cricsheet_id", "role", "season", "value_obs", "balls"], orient="row"
    )
    rat = {
        t: pl.DataFrame(
            r, schema=["cricsheet_id", "role", "value", "value_sd", "balls"], orient="row"
        )
        for t, r in ratings.items()
        if r
    }
    return history, rat, dob


def test_ridge_without_penalty_is_least_squares():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(200, 3))
    y = 1.5 + X @ np.array([2.0, -1.0, 0.5]) + rng.normal(0, 0.1, 200)
    beta = F.ridge(X, y, np.ones(200), alpha=1e-9)
    ols = np.linalg.lstsq(np.column_stack([np.ones(200), X]), y, rcond=None)[0]
    assert np.allclose(beta, ols, atol=1e-6)
    # a penalty shrinks the slopes, never the intercept's role of fitting the mean
    shrunk = F.ridge(X, y, np.ones(200), alpha=500.0)
    assert np.all(np.abs(shrunk[1:]) < np.abs(beta[1:]))


def test_logistic_recovers_coefficients():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(5000, 2))
    p = 1 / (1 + np.exp(-(0.5 + 1.2 * X[:, 0] - 0.8 * X[:, 1])))
    y = (rng.random(5000) < p).astype(float)
    b = F.logistic(X, y, alpha=1e-6)
    assert np.allclose(b, [0.5, 1.2, -0.8], atol=0.12)


def test_variance_params_recover_level_and_noise():
    rng = np.random.default_rng(3)
    n = rng.integers(20, 400, 6000).astype(float)
    k = rng.integers(1, 3, 6000)
    var = np.where(k == 1, 30.0, 60.0) + 900.0 * 100 / n
    r = rng.normal(0, np.sqrt(var))
    a, c = F.variance_params(r, np.zeros_like(r), n, k, np.ones_like(r))
    assert abs(a[1] - 30) < 15 and abs(a[2] - 60) < 20
    assert abs(c - 900) < 90


def test_fit_recovers_noise_and_follows_the_current_level():
    history, rat, dob = _synthetic()
    st = F.states(rat, history, dob)
    m = F.fit_role(st, history, "batter", 2026)
    assert m.c == pytest.approx(900, rel=0.15)
    # batters are forecast from the blend of the level forecast and the rating: slope near 1
    slope = float(F._slope(m.beta, m.features, 1, np.array([5.0]), "b")[0])
    assert 0.6 < slope < 1.3


def test_level_model_is_causal_and_recovers_its_parameters():
    """A season can't move his level at an earlier season-end; q and c come back from data
    simulated from the model itself."""
    rng = np.random.default_rng(7)
    rows = []
    for i in range(800):
        lvl = rng.normal(-5, 12)
        start = int(rng.integers(2008, 2018))
        for s in range(start, min(start + 8, 2027)):
            if s > start:
                lvl += rng.normal(0, 3.0)  # q = 9
            balls = float(rng.integers(60, 400))
            rows.append(
                (f"q{i}", "batter", s, lvl + rng.normal(0, np.sqrt(800 * 100 / balls)), balls)
            )
    h = pl.DataFrame(
        rows, schema=["cricsheet_id", "role", "season", "value_obs", "balls"], orient="row"
    )
    p = F.fit_level_params(h, 2026)["batter"]
    assert p.c == pytest.approx(800, rel=0.15)
    assert 3 < p.q < 20
    full = F.levels(h, {"batter": p}, 2026)
    cut = F.levels(h.filter(pl.col("season") <= 2015), {"batter": p}, 2015)
    j = full.join(cut, on=["cricsheet_id", "role", "t"], suffix="_cut")
    assert j.height > 0
    assert np.allclose(j["lvl"].to_numpy(), j["lvl_cut"].to_numpy())


def test_survivorship_correction_moves_the_old_age_curve_down():
    history, rat, dob = _synthetic(seed=4, n_players=1500, drop_old=True)
    st = F.states(rat, history, dob)
    m = F.fit_role(st, history, "batter", 2026)
    curves = F.age_curves({"batter": m}, ages=[28, 36, 38])["batter"]
    # survivors-only looks kinder to age than the corrected curve
    assert curves["corrected"][2] <= curves["survivors_only"][2] + 0.5


def test_project_ranges_nest_and_horizons_are_coherent():
    history, rat, dob = _synthetic(seed=5)
    st = F.states(rat, history, dob)
    models = F.fit_all(st, history, 2025, calibrate=False)
    now = st.filter(pl.col("t") == 2025)
    out = F.project(models, now, np.full(now.height, 150.0))
    assert set(out["k"].unique().to_list()) == {1, 2, 3}
    assert (out["season_lo"] <= out["lo"]).all() and (out["lo"] <= out["median"]).all()
    assert (out["median"] <= out["hi"]).all() and (out["hi"] <= out["season_hi"]).all()
    assert ((out["p_regular"] >= 0) & (out["p_regular"] <= 1)).all()


def test_interval_scale_is_bounded():
    history, rat, dob = _synthetic(seed=6)
    st = F.states(rat, history, dob)
    sc = F.interval_scales(st, history, 2024, first_origin=2018)
    assert set(sc) == {("batter", k) for k in F.HORIZONS}
    assert all(0.8 <= v <= 1.6 for v in sc.values())


@pytest.mark.parametrize(
    ("medians", "flag"),
    [
        ([10, 10.5, 9.5], "hold"),
        ([10, 10, 6], "hold_then_decline"),
        ([10, 7, 4], "decline"),
        ([10, 12, 14], "improve"),
    ],
)
def test_outlook_flags(medians, flag):
    o = F.outlook(medians, now=12.0, seasons=[2027, 2028, 2029])
    assert o["flag"] == flag
    assert o["text"].startswith("About +10 next season (current level +12)")
    assert o["avg3"] == pytest.approx(sum(medians) / 3, abs=0.05)


def test_outlook_regular_warning_only_for_current_regulars():
    o = F.outlook([5, 5, 5], 6.0, [0.8, 0.45, 0.3], regular_now=True, seasons=[2027, 2028, 2029])
    assert "only a 45% chance he is still a regular in 2028" in o["text"]
    assert "chance" not in F.outlook([5, 5, 5], 6.0, [0.2, 0.2, 0.2], regular_now=False)["text"]


def test_export_site_schema(tmp_path):
    src = tmp_path / "forecast_ipl.json"
    season = {
        "median": 1.0,
        "lo": -2.0,
        "hi": 4.0,
        "season_lo": -20.0,
        "season_hi": 22.0,
        "p_regular": 0.7,
    }
    src.write_text(
        json.dumps(
            {
                "as_of_season": 2026,
                "forecast_version": F.VERSION,
                "unit": "runs per 100 balls above the average ball",
                "regular_balls": F.REGULAR_BALLS,
                "age_curves": {},
                "players": {
                    "abc": {
                        "roles": {
                            "batter": {
                                "now": 3.0,
                                "now_sd": 2.0,
                                "level": 4.0,
                                "level_sd": 3.0,
                                "recent": [[2025, 6.0, 200], [2026, 2.0, 180]],
                                "age": 30.1,
                                "flag": "hold",
                                "text": "x",
                                "avg3": 1.0,
                                "regular_now": True,
                                "seasons": [{"season": 2027 + i, **season} for i in range(3)],
                            }
                        }
                    }
                },
            }
        )
    )
    out = json.loads(F.export_site(src, tmp_path / "site" / "forecast.json").read_text())
    assert out["columns"] == list(F.SITE_COLUMNS)
    row = out["players"]["abc"]["batter"]
    assert row["s"][0] == [2027, 1.0, -2.0, 4.0, -20.0, 22.0, 0.7]
    assert {"now", "now_sd", "level", "level_sd", "recent", "flag", "text", "avg3"} <= set(row)


def _check_site_forecast(data: dict) -> None:
    assert data["columns"] == list(F.SITE_COLUMNS)
    for roles in data["players"].values():
        for role, r in roles.items():
            assert role in F.ROLES
            assert r["flag"] in {"hold", "improve", "hold_then_decline", "decline"}
            assert len(r["s"]) == 3
            for s in r["s"]:
                season, med, lo, hi, slo, shi, p = s
                assert slo <= lo <= med <= hi <= shi and 0 <= p <= 1


def test_published_site_forecast_schema():
    path = ROOT / "site" / "public" / "data" / "ipl" / "forecast.json"
    if not path.exists():
        pytest.skip("no exported forecast.json")
    _check_site_forecast(json.loads(path.read_text(encoding="utf-8")))


BACKTEST_NAMES = (
    "model", "same_as_now", "current_level", "career_average", "age_curve", "last_season",
)  # fmt: skip


def _check_backtest(data: dict) -> None:
    assert {"origins", "seeds", "summary", "by_seed", "baselines", "forecast_version"} <= set(data)
    assert set(data["baselines"]) == set(BACKTEST_NAMES) - {"model"}
    for key, cell in data["summary"].items():
        role, k = key.rsplit("_", 1)
        assert role in F.ROLES and int(k) in F.HORIZONS
        for name in BACKTEST_NAMES:
            assert {"mae", "bias", "spearman", "mae_seed_range", "spearman_seed_range"} <= set(
                cell[name]
            )
            assert cell[name]["mae"] >= 0 and -1 <= cell[name]["spearman"] <= 1
        assert 0 <= cell["coverage80_season"] <= 1
        assert {"brier_model", "brier_regular_now", "brier_base_rate"} <= set(cell["regular"])
    assert set(data["by_seed"]) == {str(s) for s in data["seeds"]}


def test_backtest_summary_schema():
    """`summarise` (scripts/form_forecast.py) on two fake seeds, then the published file if any."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import form_forecast

    def cell(x: float) -> dict:
        m = {"mae": 20 + x, "bias": x, "spearman": 0.2 + x / 10}
        return {
            "n": 100,
            "origins": [2021, 2022],
            **{n: dict(m) for n in BACKTEST_NAMES},
            "coverage80_season": 0.78,
            "coverage80_level": 0.3,
            "regular": {
                "n": 300,
                "rate": 0.3,
                "brier_model": 0.12,
                "brier_regular_now": 0.15,
                "brier_base_rate": 0.2,
            },  # fmt: skip
        }

    per_seed = {"42": {"batter_1": cell(0.0)}, "43": {"batter_1": cell(1.0)}}
    s = form_forecast.summarise(per_seed)
    assert s["batter_1"]["model"]["mae"] == pytest.approx(20.5)
    assert s["batter_1"]["model"]["mae_seed_range"] == [20.0, 21.0]
    payload = {
        "origins": [2021, 2022],
        "seeds": [42, 43],
        "summary": s,
        "by_seed": per_seed,
        "forecast_version": F.VERSION,
        "baselines": {n: "" for n in BACKTEST_NAMES if n != "model"},
    }
    _check_backtest(payload)
    published = ROOT / "data" / "metrics" / "forecast_backtest_ipl.json"
    if published.exists():
        _check_backtest(json.loads(published.read_text(encoding="utf-8")))


def test_keep_outlook_picks_the_role():
    def role(avg):
        return {
            "avg3": avg,
            "flag": "hold",
            "text": "t",
            "level": avg,
            "seasons": [{"season": 2027 + i, "median": avg, "p_regular": 0.5} for i in range(3)],
        }

    data = {"players": {"a": {"roles": {"batter": role(5.0), "bowler": role(9.0)}}}}
    assert F.keep_outlook(data, "a", "batter")["role"] == "batter"
    assert F.keep_outlook(data, "a", "all_rounder")["role"] == "bowler"  # his stronger suit
    assert F.keep_outlook(data, "a", "keeper")["avg3"] == 5.0
    assert F.keep_outlook(data, "b", "batter") is None
    assert F.keep_outlook(None, "a", "batter") is None
