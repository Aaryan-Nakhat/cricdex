"""Streamlit page: Scout — 3-tier cross-competition look-alikes.

Identical to the web Scout room (and locked to it by
`test_scripts/test_web_parity.py`): it reads the SAME exported JSON
(`site/public/data/ipl/scout_index.json`) and uses the SAME logic
(`cricdex.web_parity`). Pick an active IPL player → similar IPL peers,
uncapped SMAT prospects, and overseas BBL options, ranked by within-tier
skill standing — with est. crore price, saving-vs-pick, an uncapped-gem
flag, role/slot filters, and a draft-to-auction handoff.

The older Neo4j-graph twins / find-replacement live on in the CLI
(`cricdex scout graph-twins`) for relational queries; this page is the
canonical, web-identical scout.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cricdex.dashboard._widgets import provenance_banner
from cricdex.web_parity import est_value, gem_threshold, is_gem, load_scout_index, similar_to
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Scout", page_icon="🔭", layout="wide")
st.title("🔭 CricDex — Scout")
st.caption(
    "Pick an active IPL player and find others of the same mould at three levels — "
    "IPL peers, uncapped Indian prospects (SMAT), overseas options (BBL) — with an "
    "estimated price, the saving vs your pick, and a draft into the Auction room. "
    "Same data + logic as the web app."
)
provenance_banner(source="cricsheet", path=SITE_DATA / "ipl" / "scout_index.json")

ROLE_OPTS = ["batter", "all_rounder", "keeper", "bowler"]
POS = {
    "": "Any",
    "opener": "Opener",
    "no3": "No. 3",
    "middle": "Middle",
    "finisher": "Finisher",
    "lower": "Lower",
    "tailender": "Tailender",
}
TIER_TITLE = {"ipl": "IPL peers", "smat": "Uncapped · SMAT", "bbl": "Overseas · BBL"}


@st.cache_data(ttl=600, show_spinner=False)
def _index() -> dict:
    return load_scout_index("ipl")


try:
    idx = _index()
except FileNotFoundError as e:
    st.error(f"{e}")
    st.stop()

ipl = sorted(idx["ipl"], key=lambda p: p["name"])
by_name = {p["name"]: p for p in ipl}
gem_med = gem_threshold(idx["smat"])

pick = st.selectbox("Active IPL player", [p["name"] for p in ipl], index=0)
sel = by_name[pick]

c1, c2 = st.columns(2)
role = c1.selectbox(
    "Match role", ROLE_OPTS, index=ROLE_OPTS.index(sel["role"]) if sel["role"] in ROLE_OPTS else 0
)
pos_label = c2.selectbox("Batting slot", list(POS.values()), index=0, disabled=role == "bowler")
pos = "" if role == "bowler" else next(k for k, v in POS.items() if v == pos_label)

sel_price = est_value(sel["value"], sel["role"], "ipl")
st.markdown(
    f"**{sel['name']}** · {sel['role'].replace('_', '-')} · standing {sel['z']:.2f} · "
    f"≈ **{sel_price:.1f} cr**"
)


def _tier_df(tier: str) -> pd.DataFrame:
    out = []
    for r in similar_to(sel, idx[tier], role, pos):
        price = est_value(r["value"], r["role"], tier)
        saving = sel_price - price if price < sel_price else 0.0
        out.append(
            {
                "Player": r["name"],
                "Country": r.get("country") or "—",
                "Last": (r.get("last_match_date") or "")[:4],
                "Est cr": round(price, 1),
                "Save cr": round(saving, 1) if saving > 0 else None,
                "Sim %": round(r["sim"] * 100),
                "💎": "💎" if (tier == "smat" and is_gem(r, gem_med)) else "",
            }
        )
    return pd.DataFrame(out)


cols = st.columns(3)
for col, tier in zip(cols, ("ipl", "smat", "bbl"), strict=True):
    with col:
        st.subheader(TIER_TITLE[tier])
        df = _tier_df(tier)
        if df.empty:
            st.info("No close match of this archetype.")
        else:
            st.dataframe(df, hide_index=True, use_container_width=True)

# --- draft handoff: same effect as the web's ?draft= -----------------------
st.divider()
prospects: dict[str, str] = {}
for tier in ("smat", "bbl"):
    for r in similar_to(sel, idx[tier], role, pos):
        prospects[f"{r['name']} ({tier.upper()})"] = r["cricsheet_id"]
chosen = st.multiselect(
    "Draft prospects into the Auction room (locked as retentions there)",
    list(prospects),
    default=[k for k in prospects if prospects[k] in st.session_state.get("drafted", [])],
    help="SMAT/BBL look-alikes you pick here are pre-loaded as retentions on the Auction page.",
)
st.session_state["drafted"] = [prospects[k] for k in chosen]
if chosen:
    st.success(f"{len(chosen)} prospect(s) queued — open the **Auction** page to place them.")
