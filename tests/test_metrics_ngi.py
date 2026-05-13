"""Smoke + integration tests for NGI."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from cricdex.metrics import ngi

DB = Path("data/cricsheet/cricsheet.duckdb")
needs_data = pytest.mark.skipif(not DB.exists(), reason="needs data/cricsheet/cricsheet.duckdb")


def test_features_list_keys():
    expected = {
        "innings_idx",
        "balls_remaining",
        "wickets_left",
        "score_before",
        "target",
        "runs_needed",
        "required_rr",
        "current_rr",
    }
    assert set(ngi.FEATURES) == expected


def test_train_wp_returns_calibrated_model():
    # Tiny synthetic batting-leads-to-win classifier: high score_before
    # in innings 2 with runs_needed=0 should predict 1.
    rng = np.random.default_rng(0)
    n = 2000
    X = rng.random((n, len(ngi.FEATURES))).astype(np.float32)
    y = (X[:, 3] > 0.5).astype(np.int8)  # score_before > 0.5 → batting wins
    model, val_acc = ngi._train_wp(X, y, seed=0)
    assert val_acc >= 0.8, f"toy task should be easy, got {val_acc:.3f}"
    # Predictions are probabilities in [0, 1].
    p = model.predict_proba(X[:50])[:, 1]
    assert (p >= 0).all() and (p <= 1).all()


@needs_data
def test_compute_ipl_returns_sane_table():
    res = ngi.compute(collection="ipl")
    assert res["val_acc"] >= 0.55, f"WP model val_acc too low: {res['val_acc']}"
    assert res["n_balls"] > 50_000, "expected >50k IPL balls"
    df = res["career"]
    assert df.height > 100
    for col in (
        "name",
        "matches",
        "ngi_total",
        "ngi_per_match",
        "ngi_batting",
        "ngi_bowling",
        "cricsheet_id",
    ):
        assert col in df.columns
    # ngi_total should approximately equal ngi_batting + ngi_bowling.
    sub = df.with_columns(
        (pl.col("ngi_batting") + pl.col("ngi_bowling") - pl.col("ngi_total")).abs().alias("diff")
    )
    assert sub["diff"].max() < 1e-4
    # Top player by ngi_per_match (≥ 30 matches floor to filter noise)
    # is a recognisable IPL match-winner.
    top = df.filter(pl.col("matches") >= 30).head(20)["name"].to_list()
    # At least one of these should appear in the top-20.
    expected = {
        "AB de Villiers",
        "KA Pollard",
        "RG Sharma",
        "DA Warner",
        "SR Watson",
        "MS Dhoni",
        "V Kohli",
        "KL Rahul",
    }
    assert expected & set(top), f"none of {expected} in top-20: {top}"
