"""Streamlit page: auction squad optimiser (MILP)."""

from __future__ import annotations

import io

import pandas as pd
import polars as pl
import streamlit as st

from cricdex.auction import solver

st.set_page_config(page_title="CricDex Auction", page_icon="💰", layout="wide")
st.title("💰 CricDex — auction squad optimiser")
st.caption(
    "Mixed-integer programming squad picker. Upload a CSV of candidate "
    "players + projected value, set the purse and constraints, and the "
    "MILP solver returns the optimal squad."
)

with st.sidebar:
    purse = st.number_input("Purse (cr)", min_value=10.0, max_value=500.0, value=120.0, step=5.0)
    squad_size = st.slider("Squad size", 11, 30, 25)
    overseas_cap = st.slider("Overseas cap", 0, 12, 8)
    role_mins = {
        "batter": st.slider("Min batters", 0, 12, 5),
        "bowler": st.slider("Min bowlers", 0, 12, 5),
        "all_rounder": st.slider("Min all-rounders", 0, 8, 3),
        "keeper": st.slider("Min keepers", 0, 4, 2),
    }
    uploaded = st.file_uploader(
        "Upload pool CSV (name, role, country, is_overseas, price, projected_value)",
        type="csv",
    )

if uploaded is not None:
    pool = pl.from_pandas(pd.read_csv(uploaded))
else:
    st.info("No CSV uploaded — using the synthetic 60-player sample pool.")
    pool = solver.sample_pool()

st.subheader("Pool")
st.dataframe(pool.to_pandas(), use_container_width=True, hide_index=True)

if st.button("Solve"):
    result = solver.solve(
        pool,
        purse=purse,
        squad_size=squad_size,
        overseas_cap=overseas_cap,
        role_mins=role_mins,
    )
    if not result["feasible"]:
        st.error(f"Infeasible: {result.get('reason')}")
    else:
        st.success(
            f"Optimal squad — price {result['total_price']:.2f} cr · "
            f"value {result['total_value']:.2f}"
        )
        st.dataframe(
            result["selected"].to_pandas(),
            use_container_width=True,
            hide_index=True,
        )
        buf = io.StringIO()
        result["selected"].write_csv(buf)
        st.download_button(
            "Download squad CSV",
            data=buf.getvalue(),
            file_name="cricdex_squad.csv",
            mime="text/csv",
        )
