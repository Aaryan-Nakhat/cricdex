"""Smoke + integration tests for NGI."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from cricdesk.config import DATA_DIR
from cricdesk.metrics import ngi

DB = (
    DATA_DIR / "cricsheet" / "cricsheet.duckdb"
)  # same lookup as the code (honours CRICDESK_DATA_DIR)
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
        "rr_vs_league",
        "target_vs_par",
        "rrr_vs_league",
    }
    assert set(ngi.FEATURES) == expected
    # every constrained direction names a real feature
    assert set(ngi.MONOTONE) <= expected


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
        "ngi_fielding",
        "cricsheet_id",
        "display_name",
    ):
        assert col in df.columns
    # ngi_total = batting + bowling + fielding.
    sub = df.with_columns(
        (
            pl.col("ngi_batting")
            + pl.col("ngi_bowling")
            + pl.col("ngi_fielding")
            - pl.col("ngi_total")
        )
        .abs()
        .alias("diff")
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
    # Balls left come from the scheduled overs (or a rain-revised target's overs), not from how the
    # innings ended: a full T20 starts at 120, a reduced one at fewer whole overs, never more.
    starts = s.filter(pl.col("legal_before") == 0)["balls_remaining"].cast(pl.Int64)
    assert starts.max() == 120 and starts.min() > 0
    assert (starts == 120).mean() > 0.95, "most innings are full 20-over innings"
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
    assert set(end_chase["wp_after"].unique().to_list()) <= {0.0, 0.5, 1.0}  # a tie is 0.5


def test_beta_calibration_is_smooth_and_monotone():
    rng = np.random.default_rng(1)
    p = rng.uniform(0.01, 0.99, 5000)
    y = (rng.uniform(size=5000) < p**1.3).astype(float)
    cal = ngi._BetaCalibrator().fit(p, y)
    grid = np.linspace(0.02, 0.98, 400)
    out = cal.transform(grid)
    assert (np.diff(out) > 0).all(), "calibration must be strictly increasing (no flat steps)"
    # ties (0.5 labels) are allowed
    ngi._BetaCalibrator().fit(p, np.where(y == 1, 1.0, 0.5))


def test_credit_rules_split_a_ball_between_players():
    """A caught wicket off a no-ball with a bye: striker gets the bat part, the batter out the
    wicket, the bowler the rest bar the team's byes, the catcher 20% of the wicket."""
    scored = pl.DataFrame(
        {
            "match_id": ["m"],
            "batter": ["s"],
            "bowler": ["b"],
            "player_out": ["s"],
            "fielders": [["f"]],
            "wicket_kind": ["caught"],
            "is_wicket": [1],
            "extras_bowler": [1],
            "extras_team": [1],
            "d_play": [0.02],
            "d_wicket": [-0.10],
            "d_extras": [0.04],
        }
    )
    c = ngi._credit(scored).group_by("player").agg(pl.col("bat", "bowl", "field").sum())
    got = {r["player"]: r for r in c.to_dicts()}
    assert got["s"]["bat"] == pytest.approx(0.02 - 0.10)
    # bowler: −play − half the extras (his no-ball run, not the bye) − 80% of the wicket
    assert got["b"]["bowl"] == pytest.approx(-0.02 - 0.5 * 0.04 + 0.8 * 0.10)
    assert got["f"]["field"] == pytest.approx(0.2 * 0.10)


def test_non_striker_run_out_debits_the_batter_out_and_credits_fielders():
    scored = pl.DataFrame(
        {
            "match_id": ["m"],
            "batter": ["s"],
            "bowler": ["b"],
            "player_out": ["ns"],
            "fielders": [["f1", "f2"]],
            "wicket_kind": ["run out"],
            "is_wicket": [1],
            "extras_bowler": [0],
            "extras_team": [0],
            "d_play": [0.01],
            "d_wicket": [-0.08],
            "d_extras": [0.0],
        }
    )
    c = ngi._credit(scored).group_by("player").agg(pl.col("bat", "bowl", "field").sum())
    got = {r["player"]: r for r in c.to_dicts()}
    assert got["s"]["bat"] == pytest.approx(0.01)
    assert got["ns"]["bat"] == pytest.approx(-0.08)
    assert got["b"]["bowl"] == pytest.approx(-0.01)  # a run out isn't the bowler's
    assert got["f1"]["field"] == pytest.approx(0.04) and got["f2"]["field"] == pytest.approx(0.04)
