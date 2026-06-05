"""Streamlit page: Head-to-head — P(A is better than B).

Mirrors the React app's Head-to-head page: closed-form P(A > B) from the
dismissal-aware Bayesian skill posteriors, role by role (batting / bowling /
complete all-round value), with an honest "too close to call" band.
"""

from __future__ import annotations

import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.dashboard._widgets import collection_picker, player_select, provenance_banner
from cricdex.scout.ratings.head_to_head import head_to_head

st.set_page_config(page_title="CricDex Head-to-head", page_icon="⚔️", layout="wide")
st.title("⚔️ CricDex — head-to-head")
st.caption(
    "P(A is better than B) from the dismissal-aware Bayesian skill model — comparing the "
    "full posteriors (mean + uncertainty), role by role. Near-50/50 reads as 'too close to call'."
)
provenance_banner(source="cricsheet", path=DATA_DIR / "cricsheet" / "cricsheet.duckdb")

with st.expander("How the probability is computed (plain English)"):
    st.markdown(
        "The model doesn't give each player one fixed number — it gives a **bell curve**: a best "
        "estimate of their skill (the centre) plus how **unsure** it is (the width). Few matches → "
        "wide curve; lots of matches → narrow.\n\n"
        "For a role we add the two relevant skill axes into one **complete value** "
        "(batting = scoring + survival; bowling = economy + strike), with the uncertainties "
        "combined.\n\n"
        "**P(A better than B)** = how much of A's bell curve sits above B's. Big gap between two "
        "confident estimates → near 100%. Small gap, or fuzzy estimates → near 50% (too close to "
        "call)."
    )
    st.code(
        "A: value +0.30, uncertainty 0.05\n"
        "B: value +0.10, uncertainty 0.05\n"
        "gap = 0.20, combined spread = √(0.05² + 0.05²) = 0.071\n"
        "P(A better) ≈ 100%  (gap is ~2.8× the spread → A clearly ahead)\n\n"
        "If both uncertainties were 0.20 instead:\n"
        "combined spread = 0.28 → gap is only 0.7× spread → P ≈ 76%",
        language="text",
    )
    st.caption("Technically: P = Φ(gap ÷ combined spread), the normal CDF.")

collection = collection_picker(key="h2h-coll")
c1, c2 = st.columns(2)
with c1:
    pa = player_select(collection, "Player A", key="h2h-a", default_name="V Kohli")
with c2:
    pb = player_select(collection, "Player B", key="h2h-b", default_name="RG Sharma")

if not (pa and pb):
    st.info("Pick two players to compare.")
    st.stop()
a, b = pa["name"], pb["name"]
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


def _gauge(name_a: str, name_b: str, pa: float) -> str:
    """Gradient probability gauge with a 50% divider — mirrors the web gauge.
    Fill is the true P(A>B) (0–100%) so a decisive verdict reads as decisive."""
    fill = max(0.0, min(100.0, pa * 100))
    return f"""<div style="margin:4px 0 2px">
      <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:#cbd5e1">
        <span>{name_a} · {pa * 100:.0f}%</span><span>{(1 - pa) * 100:.0f}% · {name_b}</span>
      </div>
      <div style="position:relative;height:16px;border-radius:8px;background:#1f2937;margin-top:3px">
        <div style="position:absolute;left:0;top:0;bottom:0;width:{fill}%;border-radius:8px;
          background:linear-gradient(90deg,#34d399,#6ee7b7)"></div>
        <div style="position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:#64748b"></div>
      </div>
    </div>"""


def _verdict_color(pa: float) -> str:
    if pa >= 0.6:
        return "#34d399"
    if pa <= 0.4:
        return "#f43f5e"
    return "#94a3b8"


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
        st.markdown(_gauge(res["name_a"], res["name_b"], pa), unsafe_allow_html=True)
        st.markdown(
            f"<span style='color:{_verdict_color(pa)};font-size:0.85rem'>{cmp['verdict']}</span>",
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.metric("balls", f"{cmp.get('balls_a', 0)} v {cmp.get('balls_b', 0)}")

if not shown:
    st.info(f"No overlapping role with enough data to compare {a} and {b} in {collection}.")
