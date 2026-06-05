"""Streamlit page: venue conditions archive.

Reads the SAME pre-cooked JSON the React web app (`site/src/pages/Venues.tsx`)
fetches — `site/public/data/<collection>/venues.json` — so the desktop
dashboard matches the live site instead of recomputing from DuckDB.
"""

from __future__ import annotations

import json

import plotly.graph_objects as go
import streamlit as st

from cricdex.dashboard._widgets import provenance_banner
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Venues", page_icon="🏟️", layout="wide")
st.title("🏟️ CricDex — venue conditions")
st.caption(
    "What a ground actually plays like — typical first- vs second-innings "
    "totals, how scoring breaks down by phase, and whether batting first or "
    "chasing wins more often here. Reads the exact same exported JSON the "
    "website does."
)

PHASE_ORDER = ["powerplay", "middle", "death"]


def _has_venues(collection: str) -> bool:
    return (SITE_DATA / collection / "venues.json").exists()


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    cols_file = SITE_DATA / "collections.json"
    names: list[str] = []
    if cols_file.exists():
        try:
            names = [c["collection"] for c in json.loads(cols_file.read_text())]
        except Exception:
            names = []
    if not names:
        names = sorted(p.name for p in SITE_DATA.iterdir() if p.is_dir())
    return [c for c in names if _has_venues(c)]


@st.cache_data(ttl=300)
def load_venues(collection: str) -> dict[str, dict]:
    path = SITE_DATA / collection / "venues.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _num(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


collections = list_collections()
if not collections:
    st.warning(
        "No exported `venues.json` found under site/public/data/. "
        "Run `uv run python scripts/export_site.py` first."
    )
    st.stop()

with st.sidebar:
    collection = st.selectbox(
        "Collection",
        options=collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="venues-collection",
        help="Only collections with an exported venues.json are listed.",
    )

provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

data = load_venues(collection)
if not data:
    st.info(f"No venue data for {collection}.")
    st.stop()

with st.sidebar:
    venue = st.selectbox("Venue", options=sorted(data.keys()), key="venues-venue")

selected = data.get(venue) or {}
st.subheader(venue)

# --- mirror Venues.tsx derived rows -------------------------------------
# innings_totals filtered to innings_idx <= 1 AND innings_count >= 3
totals = [
    r
    for r in (selected.get("innings_totals") or [])
    if (_num(r.get("innings_idx")) or 0) <= 1 and (_num(r.get("innings_count")) or 0) >= 3
]
totals.sort(key=lambda r: _num(r.get("innings_idx")) or 0)

chase = (selected.get("chase_vs_set") or [{}])[0]
decided = _num(chase.get("decided_matches"))
first_wins = _num(chase.get("first_innings_team_wins"))
first_win_pct = (first_wins / decided * 100) if (decided and first_wins is not None) else None

# headline tiles (1st innings avg, 2nd innings avg, bat-first %, chase %)
t = st.columns(4)
if len(totals) >= 1:
    t[0].metric(
        "1st innings avg",
        f"{_num(totals[0].get('avg_runs')):.0f}" if _num(totals[0].get("avg_runs")) else "—",
        help=f"{totals[0].get('innings_count')} innings",
    )
if len(totals) >= 2:
    t[1].metric(
        "2nd innings avg",
        f"{_num(totals[1].get('avg_runs')):.0f}" if _num(totals[1].get("avg_runs")) else "—",
        help=f"{totals[1].get('innings_count')} innings",
    )
if first_win_pct is not None:
    t[2].metric(
        "Bat-first win %",
        f"{first_win_pct:.0f}%",
        help=f"{int(decided)} decided" if decided else None,
    )
    t[3].metric("Chase win %", f"{100 - first_win_pct:.0f}%", help="2nd-innings team")

# --- scoring by phase (bar chart) ---------------------------------------
phase_rows = [
    r for r in (selected.get("phase_run_rates") or []) if str(r.get("phase")) in PHASE_ORDER
]
phase_rows.sort(key=lambda r: PHASE_ORDER.index(str(r.get("phase"))))

if phase_rows:
    st.markdown("### Scoring by phase")
    st.caption("Run rate, dot-ball % and boundary % across powerplay / middle / death")
    phases = [str(r["phase"]).title() for r in phase_rows]
    fig = go.Figure()
    fig.add_bar(name="Runs / over", x=phases, y=[_num(r.get("rpo")) for r in phase_rows])
    fig.add_bar(name="Dot %", x=phases, y=[_num(r.get("dot_pct")) for r in phase_rows])
    fig.add_bar(name="Boundary %", x=phases, y=[_num(r.get("boundary_pct")) for r in phase_rows])
    fig.update_layout(barmode="group", height=380, legend={"orientation": "h"})
    st.plotly_chart(fig, width="stretch")

# --- innings totals table -----------------------------------------------
if totals:
    st.markdown("### Innings totals")
    st.caption("Average and median by batting position")
    table = [
        {
            "Innings": "Batting first" if (_num(r.get("innings_idx")) or 0) == 0 else "Chasing",
            "Sample": int(_num(r.get("innings_count")) or 0),
            "Avg runs": round(_num(r.get("avg_runs")) or 0, 1),
            "Median": round(_num(r.get("median_runs")) or 0),
            "Avg wkts": round(_num(r.get("avg_wickets")) or 0, 1),
        }
        for r in totals
    ]
    st.dataframe(table, width="stretch", hide_index=True)
