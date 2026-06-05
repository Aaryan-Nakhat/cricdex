"""Streamlit page: Auction room — real-rules IPL auction Monte-Carlo.

Identical to the web Auction room (and locked to it by
`test_scripts/test_web_parity.py`): same exported pool
(`site/public/data/ipl/{auction_pool,retentions}.json`), same logic
(`cricdex.web_parity`), same seeded RNG — so a run here reproduces the
browser trial-for-trial. Pick Mega/Mini, edit retentions per team, run; see
who lands each star and how each squad shapes up.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cricdex.dashboard._widgets import load_players, provenance_banner
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

with st.expander("How the auction math works (plain English)"):
    st.markdown(
        "The data only knows how **good** a player is (a skill rating) — never what he **costs**. "
        "So step zero is inventing a fair price from skill, then everything builds on that.\n\n"
        "**Part 1 · Skill → crore price**\n"
        "1. *Amplify skill exponentially* — exponentiate + scale so the spread matches real money "
        "(top players ~27 cr, median ~3–4 cr); all-rounders/keepers get a small scarcity premium.\n"
        "2. *Decay for staleness* — value decays with time since the last match, so has-beens drop "
        "out of the top buys.\n"
        "3. *Base price* — the opening tag, snapped to IPL bands (0.3 / 0.5 / 0.75 / 1 / 1.5 / 2 cr); "
        "bidding pushes the final price up from there.\n\n"
        "**Part 2 · Who's in the pool** — the whole active T20 world: IPL players (retainable) + "
        "free agents (overseas via BBL / SA20 / CPL / T20 Blast, uncapped Indians via SMAT). Active "
        "only (last ~3 yrs), ≥150 balls. Lower tiers are penalised before pricing (BBL/SA20 −0.07, "
        "CPL/Blast −0.10, SMAT −0.20).\n\n"
        "**Part 3 · Retentions + auction** — each franchise retains its core (Mega/Mini), then the "
        "ten teams bid for everyone else by personality (value × aggression × need × overseas-bias "
        "× luck), hundreds of times. Same seeded RNG as the web app."
    )

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
    # Which franchise keeps the drafted prospect(s) — you choose, not hardcoded.
    draft_team = st.selectbox(
        f"{len(drafted)} prospect(s) drafted from Scout — assign to team",
        [t["team"] for t in teams],
        key="draft_team",
    )
    base_ret[draft_team] = list(dict.fromkeys(base_ret[draft_team] + drafted))
    st.info(
        f"{', '.join(by_id[c]['name'] for c in drafted)} → locked as retention(s) for "
        f"{draft_team} (editable below)."
    )

with st.expander("Retentions (editable per team)", expanded=True):
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
st.dataframe(teams_df, hide_index=True, width="stretch")

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
st.dataframe(marq_df, hide_index=True, width="stretch")

st.subheader("Find a player")
# Searchable dropdown over the run's players (type-ahead on full + short name),
# mirroring the web Combobox instead of a bare text field.
_full_by_name = {p["name"]: p.get("full_name") for p in load_players("ipl")}


def _auction_label(n: str) -> str:
    full = _full_by_name.get(n)
    return f"{full} ({n})" if full and full != n else n


_PICK = "— pick a player —"
_names = sorted({o["name"] for o in res["outcomes"]})
pick = st.selectbox(
    "Where did anyone land, for how much, or did they go unsold?",
    [_PICK, *_names],
    format_func=lambda n: n if n == _PICK else _auction_label(n),
    key="auction_search",
)
if pick != _PICK:
    hits = [o for o in res["outcomes"] if o["name"] == pick]
    if not hits:
        st.info(f"No outcome for '{pick}'.")
    else:
        srows = []
        for o in hits[:50]:
            if o["status"] == "retained":
                where = f"{o['team']} · retained"
            elif o["status"] == "unsold":
                where = "went unsold"
            else:
                where = ", ".join(f"{w['team']} {w['pct']:.0f}%" for w in o["winners"])
            srows.append(
                {
                    "Player": o["name"],
                    "Role": o["role"].replace("_", "-"),
                    "Status": o["status"],
                    "Avg price (cr)": None if o["status"] == "unsold" else round(o["avgPrice"], 1),
                    "Sold %": round(o["soldPct"]) if o["status"] == "sold" else None,
                    "Where": where,
                }
            )
        st.dataframe(pd.DataFrame(srows), hide_index=True, width="stretch")
else:
    st.caption("Pick a player to see where they landed, for how much, or if they went unsold.")

st.subheader("A representative squad")
squad_team = st.selectbox("Team", [s["team"] for s in res["sample_draft"]], key="squad_team")
st_state = next(s for s in res["sample_draft"] if s["team"] == squad_team)


def _squad_chip(p: dict) -> str:
    plane = " ✈" if p.get("is_overseas") else ""
    return f"- **{p['name']}** · {p['role'].replace('_', '-')}{plane}"


rc, bc = st.columns(2)
with rc:
    st.markdown(f"**Retained ({len(st_state['retained'])})**")
    st.markdown("\n".join(_squad_chip(p) for p in st_state["retained"]) or "_none_")
with bc:
    st.markdown(f"**Bought ({len(st_state['bought'])})**")
    st.markdown("\n".join(_squad_chip(p) for p in st_state["bought"]) or "_no buys in this sample_")
st.caption(
    f"{len(st_state['retained']) + len(st_state['bought'])} total · "
    f"{st_state['overseas']} overseas · auction spend {st_state['spent']:.1f} cr"
)
