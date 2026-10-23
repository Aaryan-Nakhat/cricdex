"""Ratings fit inputs, scout standing, style-twin imputation."""

from __future__ import annotations

import importlib.util
import json
import statistics
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pytest

from cricdex.scout.ratings import bayesian, runs_value
from cricdex.scout.search import style_twin
from cricdex.web_parity import gem_threshold

ROOT = Path(__file__).resolve().parents[1]


def _balls_db(path: Path) -> None:
    """Tiny collection: A faces X for 10 balls and Y for 2 (a sub-6-ball
    matchup), plus a stumping off a wide by Y on A's second visit."""
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE people (identifier VARCHAR, unique_name VARCHAR);"
        "INSERT INTO people VALUES ('a','A'),('x','X'),('y','Y'),('z','Z');"
        "CREATE TABLE balls_t (batter VARCHAR, bowler VARCHAR, runs_batter INT,"
        " extras_type VARCHAR, wicket_kind VARCHAR, player_out VARCHAR, match_date DATE,"
        " innings_idx INT DEFAULT 0, match_type VARCHAR DEFAULT 'T20')"
    )
    rows = [("A", "X", 1, None, None, None)] * 10
    rows += [("A", "Y", 4, None, None, None), ("A", "Y", 0, None, "bowled", "A")]
    rows += [("Z", "Y", 0, "wides", "stumped", "Z")]  # out on a wide: 0 legal balls
    for r in rows:
        con.execute(
            "INSERT INTO balls_t (batter, bowler, runs_batter, extras_type, wicket_kind, player_out,"
            " match_date) VALUES (?, ?, ?, ?, ?, ?, DATE '2024-01-01')",
            list(r),
        )
    con.close()


def test_edges_keep_short_matchups_and_count_true_balls(tmp_path):
    db = tmp_path / "c.duckdb"
    _balls_db(db)
    edges = bayesian._load_edges(db, "t")
    ay = edges.filter((pl.col("batter_id") == "a") & (pl.col("bowler_id") == "y")).row(
        0, named=True
    )
    assert (ay["balls"], ay["runs"], ay["outs"], ay["trials"]) == (2, 4, 1, 2)
    zy = edges.filter(pl.col("batter_id") == "z").row(0, named=True)
    # a stumping off a wide: no legal ball, but a dismissal trial, so outs <= trials
    assert (zy["balls"], zy["outs"], zy["trials"]) == (0, 1, 1)
    fitted, bidx, kidx = bayesian._index_edges(edges, 0)
    assert fitted.height == 3 and set(bidx) == {"a", "z"} and set(kidx) == {"x", "y"}
    # min_balls is a speed knob only: it drops edges from the fit
    fitted6, _, _ = bayesian._index_edges(edges, 6)
    assert fitted6.height == 1


def test_fit_reports_career_balls_and_value(tmp_path):
    db = tmp_path / "c.duckdb"
    _balls_db(db)
    df = bayesian.fit("t", db_path=db, advi_steps=50)
    a = df.filter((pl.col("cricsheet_id") == "a") & (pl.col("role") == "batter")).row(0, named=True)
    assert a["balls"] == 12 and a["runs"] == 14  # all 12 legal balls, not just the 10-ball edge
    # the only batter with legal balls IS the league's average ball: value 0 in every draw
    assert a["value"] == pytest.approx(0.0, abs=1e-9) and np.isfinite(a["value_sd"])
    bowlers = df.filter(pl.col("role") == "bowler")
    assert (bowlers["value_sd"] > 0).all() and bowlers["value"].is_finite().all()
    assert {"value", "value_sd", "survival_skill", "strike_skill"} <= set(df.columns)


def _tables(lam_by_phase=(12.0, 8.0, 3.0)) -> runs_value.LeagueTables:
    """League tables by hand: IPL-like baselines and a flat wicket cost per phase."""
    lam = np.zeros((runs_value.N_BALLS, runs_value.MAX_W))
    lam[:36], lam[36:90], lam[90:] = lam_by_phase
    r = np.array([[1.25, 1.25], [1.28, 1.28], [1.6, 1.6]])
    q = np.array([[0.037, 0.037], [0.041, 0.041], [0.078, 0.078]])
    return runs_value.LeagueTables(
        lam=lam, pout=np.full((20, 10), 0.05), par=168.0, r=r, rtot=r + 0.05, q=q, n_innings=1
    )


def _mix(t: runs_value.LeagueTables, role: str, players: dict[str, tuple[int, int, int]]) -> None:
    """players: id -> balls in (powerplay, middle, death), first innings; λ = the phase's cost."""
    t.mix[role] = {}
    for pid, (pp, mid, death) in players.items():
        balls = np.array([pp, 0, mid, 0, death, 0], dtype=float)
        lam = np.array([t.lam[0, 0]] * 2 + [t.lam[40, 0]] * 2 + [t.lam[100, 0]] * 2)
        t.mix[role][pid] = (balls, lam)


def test_runs_value_prices_a_wicket_where_the_batter_plays():
    t = _tables()
    # an opener and a finisher with the same survival edge and no scoring edge, plus a big average
    # population so the league's average ball stays put
    _mix(t, "batter", {"opener": (60, 40, 0), "finisher": (0, 10, 90), "avg": (5000, 9000, 4000)})
    ids = ["opener", "finisher", "avg"]
    scoring = np.zeros((1, 3))
    survival = np.array([[0.4, 0.4, 0.0]])
    out = runs_value.batting_value(t, ids, scoring, survival)
    opener, finisher, avg = out["value"][0]
    assert opener > finisher > avg  # staying in is worth more at the top, where a wicket costs more
    # the finisher's survival is priced at the death-overs wicket cost (3 runs), not the top's (~10)
    q = 0.078
    saved = q - 1 / (1 + np.exp(-(np.log(q / (1 - q)) - 0.4)))
    assert finisher - avg == pytest.approx(
        100 * 0.9 * 3.0 * saved + 100 * 0.1 * 8.0 * 0.0108, rel=0.1
    )
    # value = its scoring part + its wicket part
    np.testing.assert_allclose(out["value"], out["rate"] + out["wkt"])


def test_runs_value_scoring_rate_dominates_for_a_finisher():
    t = _tables()
    _mix(t, "batter", {"hitter": (0, 10, 90), "blocker": (0, 10, 90), "avg": (5000, 9000, 4000)})
    ids = ["hitter", "blocker", "avg"]
    # hitter: +0.2 scoring, average survival; blocker: average scoring, +0.6 survival
    out = runs_value.batting_value(t, ids, np.array([[0.2, 0.0, 0.0]]), np.array([[0.0, 0.6, 0.0]]))
    hitter, blocker, _ = out["value"][0]
    assert hitter > blocker > 0


def test_runs_value_is_centred_on_the_average_ball_and_keeps_draws():
    t = _tables()
    _mix(t, "bowler", {"a": (100, 200, 0), "b": (0, 100, 200), "c": (50, 50, 50)})
    rng = np.random.default_rng(0)
    econ = rng.normal(0, 0.1, (200, 3))
    strike = rng.normal(0, 0.1, (200, 3))
    out = runs_value.bowling_value(t, ["a", "b", "c"], econ, strike)
    balls = np.array([300.0, 300.0, 150.0])
    # every draw: the league's balls average 0 runs above average
    np.testing.assert_allclose(out["value"] @ balls, 0.0, atol=1e-9)
    assert out["value"].shape == (200, 3) and out["value"].std(axis=0).min() > 0
    # a cheaper bowler saves runs; a better striker earns his wickets' cost
    one = runs_value.bowling_value(
        t, ["a", "b", "c"], np.array([[0.2, 0.0, 0.0]]), np.zeros((1, 3))
    )
    assert one["value"][0, 0] > 0 > one["value"][0, 1]


def test_wicket_cost_falls_through_the_innings_and_with_depth_left(tmp_path):
    """The value function on a synthetic league: a wicket early costs more than one late."""
    rate = np.full((runs_value.N_BUCKETS, runs_value.MAX_W), 1.3)
    rate[15:] = 1.7
    rate *= np.linspace(1.0, 0.5, runs_value.MAX_W)[None, :]  # deeper in = slower scoring
    pout = np.full((runs_value.N_BUCKETS, runs_value.MAX_W), 0.04)
    v, lam = runs_value._value_function(rate, pout)
    assert 140 < v[0, 0] < 200
    assert lam[0, 0] > lam[60, 0] > lam[110, 0] > 0
    assert lam[119, 0] < 1.0  # the last ball: almost nothing left to lose
    # The Hundred: 100 balls, so the same per-ball rates give a smaller total
    v100, _ = runs_value._value_function(rate, pout, 100)
    assert v100[0, 0] == pytest.approx(v[0, 0] * 100 / 120, rel=0.05)


def test_fit_writes_runs_value_parts(tmp_path):
    db = tmp_path / "c.duckdb"
    _balls_db(db)
    df = bayesian.fit("t", db_path=db, advi_steps=30)
    assert {"value_rate", "value_wkts", "wicket_cost"} <= set(df.columns)
    a = df.filter(pl.col("role") == "batter")
    np.testing.assert_allclose(a["value"], a["value_rate"] + a["value_wkts"], atol=1e-6)


def test_gem_threshold_takes_upper_middle_for_even_counts():
    smat = [{"balls": b} for b in (100, 300, 200, 400, 0)]
    assert gem_threshold(smat) == 300.0


def test_style_twin_scaling_treats_missing_as_neutral():
    X = np.array([[100.0, 1.0], [np.nan, np.inf], [200.0, 3.0], [150.0, 2.0]])
    Z = style_twin.robust_z(X)
    assert Z[1].tolist() == [0.0, 0.0]  # missing and x/0 sit at the pool median, not an extreme
    assert Z[0, 0] < 0 < Z[2, 0]
    assert np.abs(Z).max() <= 3.0


def _load_export_site():
    spec = importlib.util.spec_from_file_location(
        "export_site", ROOT / "scripts" / "export_site.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scout_z_scores_the_matched_role_over_the_shown_players(tmp_path, monkeypatch):
    es = _load_export_site()
    ratings = []
    taxonomy = {}
    roles = {"b": "batter", "w": "bowler", "r": "allrounder"}
    for i in range(12):
        kind = "bwr"[i % 3]
        cid = f"{kind}{i}"
        taxonomy[cid] = {"primary_role": roles[kind]}
        ratings.append(
            {
                "cricsheet_id": cid,
                "unique_name": cid,
                "role": "batter",
                "value": 0.1 * i,
                "balls": 400,
            }
        )
        ratings.append(
            {
                "cricsheet_id": cid,
                "unique_name": cid,
                "role": "bowler",
                "value": 2.0 - 0.1 * i,
                "balls": 400,
            }
        )
    # rated but too thin to show: must not move anyone's z
    ratings.append(
        {"cricsheet_id": "thin", "unique_name": "thin", "role": "batter", "value": 9.0, "balls": 20}
    )
    (tmp_path / "scout_ratings_ipl.json").write_text(json.dumps(ratings))
    monkeypatch.setattr(es, "METRIC_DIR", tmp_path)
    monkeypatch.setattr(es, "_write", lambda path, obj: captured.update(obj))
    captured: dict = {}
    con = duckdb.connect()
    con.execute("CREATE TABLE balls_ipl (batter VARCHAR, bowler VARCHAR, match_date DATE)")
    for r in ratings:
        con.execute("INSERT INTO balls_ipl VALUES (?, 'q', DATE '2024-05-01')", [r["cricsheet_id"]])
    es._export_scout_index(con, tmp_path, taxonomy)
    rows = {r["cricsheet_id"]: r for r in captured["ipl"]}
    assert "thin" not in rows
    for role, score in (
        ("batter", lambda i: 0.1 * i),
        ("bowler", lambda i: 2.0 - 0.1 * i),
        ("all_rounder", lambda i: 2.0),
    ):
        shown = {cid: r for cid, r in rows.items() if r["role"] == role}
        vals = [score(int(cid[1:])) for cid in shown]
        mean, sd = statistics.mean(vals), statistics.pstdev(vals)
        for cid, r in shown.items():
            assert r["z"] == round((score(int(cid[1:])) - mean) / (sd or 1), 3)
    # a bowler is scored on his bowling: w10 has the best batting of the bowlers but the worst bowling
    assert rows["w10"]["value"] == pytest.approx(1.0) and rows["w10"]["z"] < 0


def test_price_uses_the_cautious_estimate():
    from cricdex.web_parity import build_pool
    from cricdex.web_parity.pricing import PRICE_CAUTION_SD, est_value, priced_value

    assert priced_value(20.0, 4.0) == pytest.approx(20.0 - PRICE_CAUTION_SD * 4.0)
    # a missing / non-finite sd counts as 0
    assert priced_value(20.0, None) == priced_value(20.0, float("nan")) == 20.0
    # same central value: the thin record is priced below the proven one
    assert est_value(20.0, "batter", 12.0) < est_value(20.0, "batter", 3.0)
    row = {"cricsheet_id": "x", "name": "X", "role": "batter", "is_overseas": False}
    proven, unproven = build_pool(
        [
            row | {"value": 20.0, "value_sd": 3.0},
            row | {"cricsheet_id": "y", "value": 20.0, "value_sd": 12.0},
        ]
    )
    assert proven["projected_value"] > unproven["projected_value"]
    assert proven["value"] == unproven["value"] == 20.0  # value itself stays central


def test_price_ceiling_rises_with_ipl_evidence():
    from cricdex.web_parity.pricing import PV_MAX, est_value, price_ceiling

    assert price_ceiling(0) == price_ceiling(None) == PV_MAX / 2  # no IPL record: 13.5 cr at most
    assert price_ceiling(300) == pytest.approx(PV_MAX * 0.75)
    assert price_ceiling(600) == price_ceiling(6000) == PV_MAX
    # a huge value on a thin IPL record is held to its ceiling
    assert est_value(60.0, "batter", 12.5, 449) == pytest.approx(price_ceiling(449))
    assert est_value(60.0, "batter", 12.5, 3000) == PV_MAX
