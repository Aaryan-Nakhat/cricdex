"""Smoke + integration tests for NGI."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from cricdex.config import DATA_DIR
from cricdex.metrics import ngi

DB = (
    DATA_DIR / "cricsheet" / "cricsheet.duckdb"
)  # same lookup as the code (honours CRICDEX_DATA_DIR)
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
        "current_rr_minus_venue",
    }
    assert set(ngi.FEATURES) == expected


def test_train_wp_returns_calibrated_model():
    # Tiny synthetic batting-leads-to-win classifier: high score_before
    # in innings 2 with runs_needed=0 should predict 1.
    rng = np.random.default_rng(0)
    n = 2000
    X = rng.random((n, len(ngi.FEATURES))).astype(np.float32)
    y = (X[:, 3] > 0.5).astype(np.int8)  # score_before > 0.5 → batting wins
    # Synthetic match ids — half the rows in 50 fake matches.
    match_ids = (np.arange(n) // (n // 50)).astype(str)
    model, metrics = ngi._train_wp(X, y, match_ids=match_ids, seed=0)
    assert metrics["val_acc"] >= 0.7, f"toy task should be easy, got {metrics['val_acc']:.3f}"
    # Predictions are probabilities in [0, 1].
    p = model.predict_proba(X[:50])[:, 1]
    assert (p >= 0).all() and (p <= 1).all()
    # Calibration metrics present.
    assert 0 <= metrics["brier"] <= 1
    assert metrics["log_loss"] > 0
    assert len(metrics["reliability"]) > 0


@needs_data
def test_compute_ipl_returns_sane_table():
    res = ngi.compute(collection="ipl")
    assert res["val_acc"] >= 0.65, f"WP model val_acc too low: {res['val_acc']}"
    assert res["brier"] < 0.22, f"Brier score too high: {res['brier']}"
    assert res["log_loss"] < 0.7, f"log loss too high: {res['log_loss']}"
    assert len(res["reliability"]) >= 5, "expected at least 5 reliability buckets"
    # Calibration on matches the model never saw: count-weighted gap between predicted and actual ≤ 0.04.
    n = sum(b["count"] for b in res["reliability"])
    ece = (
        sum(b["count"] * abs(b["mean_predicted"] - b["mean_actual"]) for b in res["reliability"])
        / n
    )
    assert ece <= 0.04, f"poor calibration: expected calibration error {ece:.3f}"
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


@needs_data
def test_state_uses_only_pre_delivery_information():
    """Regression for the 0-based-innings and future-leak bugs."""
    import duckdb

    with duckdb.connect(str(DB), read_only=True) as con:
        s = ngi._build_state_table(con, "ipl")
    assert set(s["innings_idx"].unique().to_list()) == {0, 1}, "super overs must be excluded"
    chase = s.filter(pl.col("innings_idx") == 1)
    first = s.filter(pl.col("innings_idx") == 0)
    # The chase always has a target; the first innings never does.
    assert (chase["target"] > 0).all()
    assert (first["target"] == 0).all() and (first["runs_needed"] == 0).all()
    # Balls left come from the scheduled overs, not from how the innings ended.
    assert set(
        s.filter(pl.col("legal_before") == 0)["balls_remaining"].cast(pl.Int64).unique().to_list()
    ) == {120}
    # A ground's average run rate is a T20 run rate, not a sum over its history.
    rates = ngi._venue_rates(s, set(s["match_id"].unique().to_list()))["venue_avg_rr"]
    assert rates.min() > 4 and rates.max() < 14


@needs_data
def test_first_innings_last_ball_hands_over_to_the_chase():
    """The last ball of the first innings must not jump to the match result."""
    import duckdb

    with duckdb.connect(str(DB), read_only=True) as con:
        s = ngi._build_state_table(con, "ipl")
    split = ngi._split_matches(s["match_id"].to_numpy())
    X, y, s = ngi._features_and_label(s, ngi._venue_rates(s, split[0]))
    model, _ = ngi._train_wp(X, y, match_ids=s["match_id"].to_numpy(), split=split)
    scored = ngi._delta_wp(model, s)
    end_first = scored.filter(pl.col("is_last_ball") & (pl.col("innings_idx") == 0))
    # Strictly between 0 and 1 (a result would be exactly 0 or 1).
    assert ((end_first["wp_after"] > 0) & (end_first["wp_after"] < 1)).mean() > 0.95
    end_chase = scored.filter(pl.col("is_last_ball") & (pl.col("innings_idx") == 1))
    assert set(end_chase["wp_after"].unique().to_list()) <= {0.0, 1.0}
