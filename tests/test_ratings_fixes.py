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

from cricdex.scout.ratings import bayesian
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
        " extras_type VARCHAR, wicket_kind VARCHAR, player_out VARCHAR, match_date DATE)"
    )
    rows = [("A", "X", 1, None, None, None)] * 10
    rows += [("A", "Y", 4, None, None, None), ("A", "Y", 0, None, "bowled", "A")]
    rows += [("Z", "Y", 0, "wides", "stumped", "Z")]  # out on a wide: 0 legal balls
    for r in rows:
        con.execute("INSERT INTO balls_t VALUES (?, ?, ?, ?, ?, ?, DATE '2024-01-01')", list(r))
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
    assert a["value_sd"] > 0 and np.isfinite(a["value"])
    assert {"value", "value_sd", "survival_skill", "strike_skill"} <= set(df.columns)


def test_value_draws_put_axes_in_population_sd_units():
    rate = np.array([[0.2], [0.4]])
    odds = np.array([[1.0], [3.0]])
    samples = {"sigma_r": np.array([0.1, 0.1]), "sigma_o": np.array([1.0, 1.0])}
    v = bayesian._value_draws(rate, odds, samples, "sigma_r", "sigma_o")
    # 0.3 / 0.1 + 2.0 / 1.0 on average: both axes count in their own spread
    assert v.mean() == pytest.approx(5.0)


def test_gem_threshold_takes_upper_middle_for_even_counts():
    smat = [{"balls": b} for b in (100, 300, 200, 400, 0)]
    assert gem_threshold(smat) == 300.0


def test_style_twin_imputes_missing_with_column_mean():
    df = pl.DataFrame(
        {
            "name": ["a", "b", "c"],
            "sr": [100.0, None, 200.0],
            "dens": [1.0, float("inf"), 3.0],  # x/0 is missing, not a value
            "empty": [None, None, None],
            "role": ["batter"] * 3,
        },
        schema_overrides={"empty": pl.Float64},
    )
    X, names, cols = style_twin._vectorise(df)
    assert cols == ["sr", "dens"]  # an axis nobody has is dropped
    assert X[1].tolist() == [150.0, 2.0]


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
