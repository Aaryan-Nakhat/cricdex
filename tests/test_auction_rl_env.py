"""Smoke tests for the auction RL env + GRPO policy round-trip."""

from __future__ import annotations

import numpy as np
import polars as pl

from cricdex.auction import grpo, solver
from cricdex.auction.rl_env import N_BUCKETS, STATE_DIM, AuctionEnv


def _tiny_pool() -> pl.DataFrame:
    return solver.sample_pool(n=10, seed=0)


def test_reset_returns_correct_state_dim():
    env = AuctionEnv(_tiny_pool(), n_franchises=3, seed=0)
    obs = env.reset()
    assert obs.shape == (STATE_DIM,)
    assert obs.dtype == np.float32


def test_step_progresses_state_idx_and_returns_done_at_end():
    env = AuctionEnv(_tiny_pool(), n_franchises=3, seed=0)
    env.reset()
    n_players = len(env.players)
    done = False
    steps = 0
    while not done:
        _obs, _r, done, info = env.step(action=0)  # always pass
        steps += 1
    assert steps == n_players
    assert info.get("terminal_bonus_applied") is True


def test_pass_action_costs_nothing_and_terminal_bonus_negative_when_role_mins_unmet():
    env = AuctionEnv(_tiny_pool(), n_franchises=3, seed=0)
    env.reset()
    total = 0.0
    done = False
    while not done:
        _, r, done, _ = env.step(action=0)
        total += r
    me = env.franchises[env.learner_slot]
    assert me.purse == env.purse, "passing should not spend any purse"
    assert me.acquired_value == 0.0
    # 12 unfilled role-min slots (5+5+3+2 default) → terminal bonus is
    # 0.5 * 0 - 5.0 * sum(unfilled) ≪ 0.
    assert total < 0


def test_policy_save_load_roundtrip(tmp_path):
    policy = grpo.PolicyMLP()
    out = tmp_path / "policy.zip"
    grpo.save_policy(policy, history=[], path=out)
    loaded = grpo.load_policy(out)
    obs = np.zeros(STATE_DIM, dtype=np.float32)
    # Same action distribution before / after round-trip.
    a1 = policy.act(obs, greedy=True)
    a2 = loaded.act(obs, greedy=True)
    assert 0 <= a1 < N_BUCKETS
    assert a1 == a2


def test_grpo_train_converges_one_epoch(tmp_path):
    """Smoke — 1 epoch, 2 rollouts. Verifies the gradient step runs
    without NaN and produces a history entry."""
    pool = _tiny_pool()
    out = tmp_path / "policy.zip"
    res = grpo.train(
        pool,
        epochs=1,
        group_size=2,
        n_franchises=3,
        purse=90.0,
        seed=0,
        out_path=out,
        verbose=False,
    )
    assert out.exists()
    assert len(res["history"]) == 1
    h = res["history"][0]
    assert np.isfinite(h["mean_return"])
    assert np.isfinite(h["policy_loss"])
    assert np.isfinite(h["entropy"])
