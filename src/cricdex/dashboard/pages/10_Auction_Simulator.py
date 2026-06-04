"""Streamlit page: Monte-Carlo IPL auction simulator + optional RL agent.

The simulator now uses the 10 real IPL franchises, each with a bidding
personality picked from the 6 archetypes
(MarqueeChaser / ValueHunter / OverseasHeavy / IndianFocus /
AllRounderStack / Balanced). Defaults come from `IPL_TEAMS_DEFAULT`
(history-based) and can be overridden per team via the sidebar
selectboxes below. The same picks the user makes here flow into the
underlying `cricdex.auction.real_pool.build_franchises` call.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import polars as pl
import streamlit as st

from cricdex.auction import real_pool, simulator, solver
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
st.info(
    "ℹ️ This is the legacy DuckDB-driven price-band simulator (kept for the RL "
    "self-play research path). The **canonical, web-identical** auction — same "
    "pool, retentions, rules and seeded Monte-Carlo as the live site — is the "
    "**💰 Auction room** page.",
    icon="ℹ️",
)
provenance_banner(source="cricsheet", path=DATA_DIR / "cricsheet" / "cricsheet.duckdb")

# --- sidebar: sim knobs + per-team personality selectors ----------------

with st.sidebar:
    n_sims = st.slider("Simulations", 50, 1000, 200, step=50)
    purse = st.number_input("Per-franchise purse (cr)", 30.0, 200.0, 90.0, step=5.0)
    uploaded = st.file_uploader("Pool CSV (optional)", type="csv")

    st.markdown("### Franchise personalities")
    st.caption(
        "Defaults are hand-picked from broad IPL history (CSK disciplined "
        "→ Balanced, MI / RCB marquee-heavy, KKR all-rounder stack, "
        "SRH / LSG overseas-led, PBKS / RR value-hunters, GT balanced, "
        "DC Indian-focus). Override any team here — your picks are what "
        "the simulator actually bids with."
    )
    if st.button("Reset to history defaults"):
        for team, default in real_pool.IPL_TEAMS_DEFAULT:
            st.session_state[f"team-{team}"] = default

    yaml_override = real_pool.load_team_overrides()
    if yaml_override:
        st.info(f"`~/.cricdex/teams.yaml` override loaded ({len(yaml_override)} teams).")
        defaults_map = dict(yaml_override)
    else:
        defaults_map = dict(real_pool.IPL_TEAMS_DEFAULT)

    team_picks: list[tuple[str, str]] = []
    for team, _default in real_pool.IPL_TEAMS_DEFAULT:
        default_pers = defaults_map.get(team, "Balanced")
        choice = st.selectbox(
            team,
            options=list(real_pool.PERSONALITY_IDS),
            index=list(real_pool.PERSONALITY_IDS).index(default_pers),
            key=f"team-{team}",
        )
        team_picks.append((team, choice))

# --- pool + franchises --------------------------------------------------

if uploaded is not None:
    pool = pl.from_pandas(pd.read_csv(uploaded))
else:
    pool = solver.sample_pool()

franchises = real_pool.build_franchises(purse=purse, teams=team_picks)

# Show the current team → personality map so the user can sanity-check.
st.subheader("Bidding line-up")
map_df = pd.DataFrame([{"team": f["id"], "personality": f["personality"]} for f in franchises])
st.dataframe(map_df, use_container_width=True, hide_index=True)

# --- run the sim --------------------------------------------------------

if st.button("Run simulation", type="primary"):
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
        pool,
        target_player=target,
        your_bid=your_bid,
        franchises=franchises,
        n_sims=n_sims,
    )
    st.metric(f"P(win {target} at ≤ {your_bid} cr)", f"{p:.0%}")

# --- RL agent block (unchanged) -----------------------------------------

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
        env = AuctionEnv(pool, n_franchises=len(franchises), purse=purse, seed=0)
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
