"""Streamlit page: Aging curves — performance vs age.

Reads the SAME exported JSON the web app (`site/src/pages/Aging.tsx`) fetches —
`site/public/data/<collection>/aging.json` — so the desktop dashboard matches
the live site.
"""

from __future__ import annotations

import json

import plotly.graph_objects as go
import streamlit as st

from cricdex.dashboard._widgets import player_select, provenance_banner
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Aging", page_icon="📈", layout="wide")
st.title("📈 CricDex — aging curves")
st.caption(
    "How batting & bowling performance changes with age. Each player-season "
    "(≥60 balls) is a data point, averaged by age into a curve. Same exported "
    "data as the website."
)

METRICS = {
    "batting": [("sr", "Strike rate", "sr"), ("average", "Average", None)],
    "bowling": [("economy", "Economy", "economy"), ("strike_rate", "Strike rate", None)],
}


def _has_aging(collection: str) -> bool:
    return (SITE_DATA / collection / "aging.json").exists()


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    names = sorted(p.name for p in SITE_DATA.iterdir() if p.is_dir())
    return [c for c in names if _has_aging(c)]


@st.cache_data(ttl=300)
def load_aging(collection: str) -> dict:
    path = SITE_DATA / collection / "aging.json"
    return json.loads(path.read_text()) if path.exists() else {}


collections = list_collections()
if not collections:
    st.warning(
        "No exported `aging.json` found under site/public/data/. "
        "Run `uv run python scripts/export_site.py` first."
    )
    st.stop()

with st.sidebar:
    collection = st.selectbox(
        "Collection",
        options=collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="aging-collection",
    )
    role = st.radio("Discipline", ["batting", "bowling"], horizontal=True, key="aging-role")
    metric_label = st.selectbox("Metric", [m[1] for m in METRICS[role]], key="aging-metric")

provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

data = load_aging(collection)
curve = data.get(role) or []
if not curve:
    st.info(f"No aging data for {collection} (needs player dates of birth).")
    st.stop()

mkey, _, overlay_key = next(m for m in METRICS[role] if m[1] == metric_label)
st.caption(
    "Ages from Wikidata dob (~a third of players — elite-skewed). Survivorship not "
    "corrected; treat the curve as indicative."
)

fig = go.Figure()
fig.add_scatter(
    x=[r["age"] for r in curve],
    y=[r.get(mkey) for r in curve],
    mode="lines+markers",
    name=f"All players ({metric_label})",
    line={"color": "#34d399", "width": 3},
)

# optional per-player overlay (only for SR / economy — the trajectory keys)
if overlay_key:
    sel = player_select(collection, key="aging-player", default_name=None)
    if sel:
        pl = (data.get("players") or {}).get(sel["cricsheet_id"])
        want_role = "batter" if role == "batting" else "bowler"
        if pl and pl.get("role") == want_role:
            pts = [p for p in pl["points"] if p.get(overlay_key) is not None]
            if pts:
                fig.add_scatter(
                    x=[p["age"] for p in pts],
                    y=[p[overlay_key] for p in pts],
                    mode="lines+markers",
                    name=sel["name"],
                    line={"color": "#fbbf24", "width": 2},
                )
        else:
            st.info(f"{sel['name']} has no {want_role} trajectory with enough seasons.")

fig.update_layout(
    height=460,
    xaxis_title="Age",
    yaxis_title=metric_label,
    legend={"orientation": "h"},
)
st.plotly_chart(fig, width="stretch")
