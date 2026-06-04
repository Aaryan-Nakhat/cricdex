"""Streamlit page: Head-to-head — P(A is better than B).

Mirrors the React app's Head-to-head page: closed-form P(A > B) from the
dismissal-aware Bayesian skill posteriors, role by role (batting / bowling /
complete all-round value), with an honest "too close to call" band.
"""

from __future__ import annotations

import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.dashboard._widgets import collection_picker, fuzzy_player_input, provenance_banner
from cricdex.scout.ratings.head_to_head import head_to_head

st.set_page_config(page_title="CricDex Head-to-head", page_icon="⚔️", layout="wide")
st.title("⚔️ CricDex — head-to-head")
st.caption(
    "P(A is better than B) from the dismissal-aware Bayesian skill model — comparing the "
    "full posteriors (mean + uncertainty), role by role. Near-50/50 reads as 'too close to call'."
)
provenance_banner(source="cricsheet", path=DATA_DIR / "cricsheet" / "cricsheet.duckdb")

collection = collection_picker(key="h2h-coll")
c1, c2 = st.columns(2)
with c1:
    a = fuzzy_player_input("Player A", "V Kohli", collection, key="h2h-a")
with c2:
    b = fuzzy_player_input("Player B", "RG Sharma", collection, key="h2h-b")

if not (a and b):
    st.info("Pick two players to compare.")
    st.stop()
if a == b:
    st.warning("Pick two *different* players.")
    st.stop()

res = head_to_head(a, b, collection)
if res.get("error"):
    st.error(res["error"])
    st.stop()

ROLE_LABEL = {
    "batter": "Batting",
    "bowler": "Bowling",
    "all_rounder": "All-round (complete value)",
}
shown = 0
for role, label in ROLE_LABEL.items():
    cmp = res["comparisons"].get(role)
    if not cmp:
        continue
    shown += 1
    pa = cmp["p_a_better"]
    st.subheader(label)
    cols = st.columns([3, 1])
    with cols[0]:
        st.progress(
            pa, text=f"{res['name_a']} {pa * 100:.0f}%  ·  {res['name_b']} {(1 - pa) * 100:.0f}%"
        )
        st.caption(cmp["verdict"])
    with cols[1]:
        st.metric("balls", f"{cmp.get('balls_a', 0)} v {cmp.get('balls_b', 0)}")

if not shown:
    st.info(f"No overlapping role with enough data to compare {a} and {b} in {collection}.")
