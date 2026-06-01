"""Unit tests for the Bayesian skill head-to-head."""

from __future__ import annotations

import math

from cricdex.scout.ratings import head_to_head as h2h


def test_phi_known_values():
    # Φ(0) = 0.5, Φ(1.96) ≈ 0.975, symmetric.
    assert abs(h2h._phi(0.0) - 0.5) < 1e-9
    assert abs(h2h._phi(1.96) - 0.975) < 1e-3
    assert abs(h2h._phi(-1.96) - 0.025) < 1e-3


def test_compare_normal_symmetry():
    # A clearly ahead of B → p_a_better > 0.5; probabilities sum to 1.
    c = h2h._compare_normal(0.5, 0.1, 0.0, 0.1)
    assert c["p_a_better"] > 0.5
    assert abs(c["p_a_better"] + c["p_b_better"] - 1.0) < 1e-9
    # Identical posteriors → exactly 50/50.
    c2 = h2h._compare_normal(0.2, 0.3, 0.2, 0.3)
    assert abs(c2["p_a_better"] - 0.5) < 1e-9


def test_compare_normal_pooled_sd():
    c = h2h._compare_normal(1.0, 0.3, 0.0, 0.4)
    assert abs(c["pooled_sd"] - math.sqrt(0.3**2 + 0.4**2)) < 1e-9


def test_verdict_thresholds():
    # Near 50/50 → too close to call.
    assert "too close" in h2h._verdict("A", "B", 0.52)
    # Lopsided → names the dominant player.
    v = h2h._verdict("A", "B", 0.95)
    assert "A" in v and "dominant" in v
    # Below 0.5 leans to B.
    assert "B" in h2h._verdict("A", "B", 0.20)


def test_head_to_head_missing_ratings(tmp_path, monkeypatch):
    # Point METRIC_DIR at an empty dir → graceful error, no crash.
    monkeypatch.setattr(h2h, "METRIC_DIR", tmp_path)
    out = h2h.head_to_head("V Kohli", "RG Sharma", collection="nonexistent")
    assert out["comparisons"] == {}
    assert "error" in out


def test_head_to_head_all_rounder_combines(tmp_path, monkeypatch):
    import json

    rows = [
        {"unique_name": "A", "role": "batter", "skill": 0.2, "skill_sd": 0.1, "balls": 500},
        {"unique_name": "A", "role": "bowler", "skill": 0.1, "skill_sd": 0.1, "balls": 400},
        {"unique_name": "B", "role": "batter", "skill": 0.0, "skill_sd": 0.1, "balls": 600},
        {"unique_name": "B", "role": "bowler", "skill": 0.0, "skill_sd": 0.1, "balls": 300},
    ]
    (tmp_path / "scout_ratings_test.json").write_text(json.dumps(rows))
    monkeypatch.setattr(h2h, "METRIC_DIR", tmp_path)
    out = h2h.head_to_head("A", "B", collection="test")
    ar = out["comparisons"]["all_rounder"]
    assert ar is not None
    # A's combined mean (0.3) > B's (0.0) → A favoured.
    assert ar["p_a_better"] > 0.5
    assert ar["balls_a"] == 900
