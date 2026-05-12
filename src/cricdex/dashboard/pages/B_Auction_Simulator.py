"""Streamlit page: Monte-Carlo IPL auction simulator."""

from __future__ import annotations

import pandas as pd
import polars as pl
import streamlit as st

from cricdex.auction import simulator, solver

st.set_page_config(page_title="CricDex Auction Sim", page_icon="🎲", layout="wide")
st.title("🎲 CricDex — auction Monte-Carlo simulator")
st.caption(
    "Each franchise is a simple agent with its own purse, role needs, "
    "aggression and risk profile. We run N simulated auctions and report "
    "the realised price distribution per player. Lighter than full RL "
    "self-play; covers the practitioner-facing question — 'realistic "
    "price band for player X' — in seconds."
)

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
