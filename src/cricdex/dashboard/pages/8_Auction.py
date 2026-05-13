"""Streamlit page: auction squad optimiser (MILP)."""

from __future__ import annotations

import io

import pandas as pd
import polars as pl
import streamlit as st

from cricdex.auction import real_pool, solver

st.set_page_config(page_title="CricDex Auction", page_icon="💰", layout="wide")
st.title("💰 CricDex — auction squad optimiser")
st.caption(
    "Mixed-integer programming squad picker. Upload a CSV of candidate "
    "players + projected value, set the purse and constraints, and the "
    "MILP solver returns the optimal squad."
)

with st.sidebar:
    pool_source = st.radio(
        "Pool source",
        ["Real IPL (Bayes skill-driven)", "Synthetic 60-player sample", "Upload CSV"],
        index=0,
    )
    min_balls = st.slider("Min IPL career balls (real pool only)", 50, 1000, 200, step=50)
    purse = st.number_input("Purse (cr)", min_value=10.0, max_value=500.0, value=120.0, step=5.0)
    squad_size = st.slider("Squad size", 11, 30, 25)
    overseas_cap = st.slider("Overseas cap", 0, 12, 8)
    # Real pool has no keeper tag yet (deferred — needs Wikidata/Cricinfo
    # role metadata). Default keeper min to 0 there.
    is_real = pool_source == "Real IPL (Bayes skill-driven)"
    keeper_default = 0 if is_real else 2
    role_mins = {
        "batter": st.slider("Min batters", 0, 12, 5),
        "bowler": st.slider("Min bowlers", 0, 12, 5),
        "all_rounder": st.slider("Min all-rounders", 0, 8, 3),
        "keeper": st.slider("Min keepers", 0, 4, keeper_default),
    }
    uploaded = (
        st.file_uploader(
            "Upload pool CSV (name, role, country, is_overseas, price, projected_value)",
            type="csv",
        )
        if pool_source == "Upload CSV"
        else None
    )

if pool_source == "Upload CSV" and uploaded is not None:
    pool = pl.from_pandas(pd.read_csv(uploaded))
elif pool_source == "Synthetic 60-player sample":
    st.info(
        "Using the synthetic random sample pool. Switch to 'Real IPL' for the Bayes-driven cohort."
    )
    pool = solver.sample_pool()
else:
    try:
        pool = real_pool.build_pool(min_balls=min_balls)
        st.success(
            f"Real IPL pool — {pool.height} players, "
            f"median projected_value {pool['projected_value'].median():.2f} cr. "
            f"Note: MILP has no `keeper` role, so satisfying `Min keepers > 0` will require keeper-tagged data (deferred)."
        )
    except FileNotFoundError as e:
        st.warning(
            f"Real pool unavailable ({e}). Falling back to synthetic sample. "
            "Run `make docker-scout-rate COLLECTION=ipl` to generate "
            "`data/metrics/scout_ratings_ipl.json` first."
        )
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


st.divider()
st.subheader("🎯 War-room advisor — find a substitute")
st.caption(
    "Target player went above your budget? Plug their name + remaining purse "
    "below. The advisor ranks pool players by composite of graph similarity "
    "(co-faced cohort) and Bayes-driven projected value, filtered to your "
    "budget and role. Requires Neo4j up + populated."
)
adv_target = st.text_input("Unavailable target (unique_name)", "JJ Bumrah")
col1, col2, col3 = st.columns(3)
with col1:
    adv_budget = st.number_input("Remaining purse (cr)", value=8.0, step=0.5, min_value=0.0)
with col2:
    adv_role = st.selectbox("Role", ["", "bowler", "batter", "all_rounder"], index=1)
with col3:
    adv_n = st.slider("Top-N substitutes", 3, 15, 5)
if st.button("Recommend substitutes"):
    try:
        from cricdex.auction import advisor as _advisor

        rec = _advisor.recommend_substitutes(
            adv_target,
            budget=adv_budget,
            role=adv_role or None,
            n=adv_n,
            pool=pool,
        )
        if rec.is_empty():
            st.warning(
                "No affordable graph-similar candidates. Try a higher budget, "
                "wider role filter, or check the target's unique_name."
            )
        else:
            st.dataframe(rec.to_pandas(), use_container_width=True, hide_index=True)
    except ImportError as e:
        st.error(f"`neo4j` extra not installed ({e}). Run `uv sync --extra graph`.")
