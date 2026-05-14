"""Streamlit page: Monte-Carlo IPL auction simulator + optional RL agent."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import polars as pl
import streamlit as st

from cricdex.auction import simulator, solver
from cricdex.config import DATA_DIR
from cricdex.dashboard._widgets import provenance_banner

st.set_page_config(page_title="CricDex Auction Sim", page_icon="🎲", layout="wide")
st.title("🎲 CricDex — auction Monte-Carlo simulator")
st.caption(
    "Each franchise is a simple agent with its own purse, role needs, "
    "aggression and risk profile. We run N simulated auctions and report "
    "the realised price distribution per player. Lighter than full RL "
    "self-play; covers the practitioner-facing question — 'realistic "
    "price band for player X' — in seconds."
)
provenance_banner(source="cricsheet", path=DATA_DIR / "cricsheet" / "cricsheet.duckdb")

with st.sidebar:
    n_sims = st.slider("Simulations", 50, 1000, 200, step=50)
    purse = st.number_input("Per-franchise purse (cr)", 30.0, 200.0, 90.0, step=5.0)
    n_franchises = st.slider("Number of franchises", 4, 12, 10)
    aggression = st.slider("Default aggression", 0.6, 1.6, 1.0, step=0.05)
    risk = st.slider("Default risk (jitter sd)", 0.05, 0.4, 0.15, step=0.05)
    uploaded = st.file_uploader("Pool CSV (optional)", type="csv")

if uploaded is not None:
    pool = pl.from_pandas(pd.read_csv(uploaded))
else:
    pool = solver.sample_pool()

franchises = [
    {"id": f"F{i + 1}", "purse": purse, "aggression": aggression, "risk": risk}
    for i in range(n_franchises)
]

if st.button("Run simulation"):
    with st.spinner(f"running {n_sims} auctions …"):
        result = simulator.simulate(pool, franchises=franchises, n_sims=n_sims)
    st.subheader("Price distribution per player")
    st.dataframe(
        result["per_player"].to_pandas(),
        use_container_width=True,
        hide_index=True,
    )
    st.subheader("Bid-probability sweep")
    target = st.selectbox("Player", pool["name"].to_list())
    your_bid = st.slider("Your bid (cr)", 0.0, 25.0, 5.0, step=0.25)
    p = simulator.win_probability(
        pool, target_player=target, your_bid=your_bid, franchises=franchises, n_sims=n_sims
    )
    st.metric(f"P(win {target} at ≤ {your_bid} cr)", f"{p:.0%}")

st.divider()
st.subheader("🤖 GRPO RL agent (optional)")
st.caption(
    "Load a trained `policy.zip` (see `scripts/train_auction_grpo.py`) to "
    "watch the RL franchise bid against MC opponents on the same pool."
)
policy_path = Path(st.text_input("Policy path", str(DATA_DIR / "auction" / "policy.zip")))
if st.button("Run one RL auction"):
    if not policy_path.exists():
        st.error(f"policy not found at {policy_path}. Train one first.")
    else:
        from cricdex.auction import grpo
        from cricdex.auction.rl_env import AuctionEnv

        policy = grpo.load_policy(policy_path)
        env = AuctionEnv(pool, n_franchises=n_franchises, purse=purse, seed=0)
        obs = env.reset()
        done = False
        total_reward = 0.0
        while not done:
            a = policy.act(obs, greedy=True)
            obs, r, done, _ = env.step(a)
            total_reward += r
        learner = env.franchises[env.learner_slot]
        st.metric("Episode shaped reward", f"{total_reward:.2f}")
        st.metric("Purse left (cr)", f"{learner.purse:.2f}")
        st.metric("Roster size", len(learner.roster))
        st.write("Roster:", learner.roster)
