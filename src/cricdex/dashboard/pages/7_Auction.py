"""Streamlit page: Auction room — real-rules IPL auction Monte-Carlo.

Identical to the web Auction room (and locked to it by
`test_scripts/test_web_parity.py`): same exported pool
(`site/public/data/ipl/{auction_pool,retentions}.json`), same logic
(`cricdex.web_parity`), same seeded RNG — so a run here reproduces the
browser trial-for-trial. Pick Mega/Mini, edit retentions per team, run; see
who lands each star and how each squad shapes up.

The older MILP squad optimiser remains in the CLI (`cricdex auction solve`)
for the single-squad knapsack; this page is the canonical, web-identical sim.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cricdex.dashboard._widgets import provenance_banner
from cricdex.web_parity import (
    ARCHETYPES,
    IPL_TEAMS_DEFAULT,
    build_pool,
    default_retentions,
    load_auction_pool,
    load_retentions,
    simulate_auction,
)
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Auction", page_icon="💰", layout="wide")
st.title("💰 CricDex — Auction room")
st.caption(
    "Monte-Carlo of a real IPL auction. Each franchise retains its core (Mega = the "
    "real 2025 lists; Mini = keep most of the squad — editable below), then the ten "
    "teams bid for everyone else by their personality, hundreds of times. Same data + "
    "logic + seeded RNG as the web app."
)
provenance_banner(source="cricsheet", path=SITE_DATA / "ipl" / "auction_pool.json")

ARCH_IDS = [a["id"] for a in ARCHETYPES]


@st.cache_data(ttl=600, show_spinner=False)
def _load():
    return load_auction_pool("ipl"), load_retentions("ipl")


try:
    pool_rows, ret = _load()
except FileNotFoundError as e:
    st.error(f"{e}")
    st.stop()

pool = build_pool(pool_rows)
by_id = {p["cricsheet_id"]: p for p in pool}
mega_ids = {t: [r["cricsheet_id"] for r in rows] for t, rows in ret["mega"].items()}
real_prices = {r["cricsheet_id"]: r["price"] for rows in ret["mega"].values() for r in rows}

# ---- controls --------------------------------------------------------------
mode = st.radio(
    "Auction type",
    ["mega", "mini"],
    horizontal=True,
    format_func=lambda m: "Mega auction" if m == "mega" else "Mini auction",
)
c1, c2, c3, c4 = st.columns(4)
purse = c1.number_input(
    "Purse / team (cr)",
    10.0,
    500.0,
    value=120.0 if mode == "mega" else 30.0,
    step=5.0,
    key=f"purse_{mode}",
)
squad_size = c2.number_input("Squad cap", 20, 25, value=25, key="squad")
overseas_cap = c3.number_input("Overseas cap", 0, 11, value=8, key="overseas")
trials = c4.number_input("Trials", 50, 1000, value=300, step=50, key="trials")

with st.expander("Franchise personalities"):
    cols = st.columns(5)
    teams = []
    for i, t in enumerate(IPL_TEAMS_DEFAULT):
        p = cols[i % 5].selectbox(
            t["team"], ARCH_IDS, index=ARCH_IDS.index(t["personality"]), key=f"pers_{t['team']}"
        )
        teams.append({"team": t["team"], "personality": p})

# default retentions for the mode, plus any prospects drafted from Scout
base_ret = default_retentions(pool, teams, mode, mega_ids)
drafted = [c for c in st.session_state.get("drafted", []) if c in by_id]
if drafted:
    base_ret[teams[0]["team"]] = list(dict.fromkeys(base_ret[teams[0]["team"]] + drafted))
    st.info(
        f"{len(drafted)} prospect(s) drafted from Scout → pre-loaded into {teams[0]['team']} "
        "(move them in the editor below)."
    )

with st.expander("Retentions (editable per team)", expanded=bool(drafted)):
    retentions = {}
    cols = st.columns(2)
    for i, t in enumerate(teams):
        team = t["team"]
        # options = all pool ids on this team OR already retained (so drafted free
        # agents show up too); label with name + projected price.
        opt_ids = [p["cricsheet_id"] for p in pool if p["team"] == team] + [
            c for c in base_ret[team] if by_id.get(c) and by_id[c]["team"] != team
        ]
        opt_ids = list(dict.fromkeys(opt_ids))
        sel = cols[i % 2].multiselect(
            team,
            opt_ids,
            default=[c for c in base_ret[team] if c in opt_ids],
            format_func=lambda c: f"{by_id[c]['name']} ({by_id[c]['projected_value']:.0f}cr)",
            key=f"ret_{team}_{mode}",
        )
        retentions[team] = sel

run = st.button("🎲 Run simulation", type="primary")
if not run:
    st.info("Set the knobs and retentions, then **Run simulation**.")
    st.stop()

res = simulate_auction(
    pool,
    teams,
    {
        "purse": purse,
        "squad_size": int(squad_size),
        "overseas_cap": int(overseas_cap),
        "trials": int(trials),
        "mode": mode,
        "retentions": retentions,
        "real_prices": real_prices,
    },
)

st.subheader("How each squad shapes up")
st.caption(
    f"{'Mega' if mode == 'mega' else 'Mini'} auction · {res['pool_size']} players under the "
    f"hammer · averaged over {int(trials)} runs"
)
teams_df = pd.DataFrame(
    [
        {
            "Team": t["team"],
            "Personality": t["personality"],
            "Retained": t["retained"],
            "Bought": round(t["avg_bought"]),
            "Auction spend (cr)": round(t["avg_spend"], 1),
            "Squad value": round(t["avg_value"], 1),
            "Overseas": round(t["avg_overseas"]),
        }
        for t in sorted(res["teams"], key=lambda t: t["avg_value"], reverse=True)
    ]
)
st.dataframe(teams_df, hide_index=True, use_container_width=True)

st.subheader("Who lands the marquee names")
marq_df = pd.DataFrame(
    [
        {
            "Player": m["player"]["name"],
            "Role": m["player"]["role"].replace("_", "-"),
            "Value": round(m["player"]["projected_value"], 1),
            "Most likely": ", ".join(f"{w['team']} {w['pct']:.0f}%" for w in m["winners"])
            or "unsold",
        }
        for m in res["marquee"]
    ]
)
st.dataframe(marq_df, hide_index=True, use_container_width=True)

st.subheader("A representative squad")
draft_team = st.selectbox("Team", [s["team"] for s in res["sample_draft"]])
st_state = next(s for s in res["sample_draft"] if s["team"] == draft_team)
st.markdown(
    f"**Retained ({len(st_state['retained'])}):** "
    + (", ".join(p["name"] for p in st_state["retained"]) or "none")
)
st.markdown(
    f"**Bought ({len(st_state['bought'])}):** "
    + (", ".join(p["name"] for p in st_state["bought"]) or "no buys in this sample")
)
st.caption(
    f"{len(st_state['retained']) + len(st_state['bought'])} total · "
    f"{st_state['overseas']} overseas · auction spend {st_state['spent']:.1f} cr"
)
