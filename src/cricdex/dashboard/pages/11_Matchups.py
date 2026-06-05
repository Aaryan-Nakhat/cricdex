"""Streamlit page: Matchups — batter vs bowler head-to-heads + pace/spin splits.

Reads the SAME exported JSON the web app (`site/src/pages/Matchups.tsx`) fetches
— `site/public/data/<collection>/matchups/<cricsheet_id>.json` — so the desktop
dashboard matches the live site.
"""

from __future__ import annotations

import json

import streamlit as st

from cricdex.dashboard._widgets import player_select, provenance_banner
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Matchups", page_icon="🎯", layout="wide")
st.title("🎯 CricDex — Matchups")
st.caption(
    "A player's toughest and favourite head-to-heads — ball-by-ball as a batter "
    "and as a bowler — plus how a batter fares against pace versus spin. Same "
    "exported data as the website."
)


def _has_matchups(collection: str) -> bool:
    return (SITE_DATA / collection / "matchups").is_dir()


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    names = sorted(p.name for p in SITE_DATA.iterdir() if p.is_dir())
    return [c for c in names if _has_matchups(c)]


@st.cache_data(ttl=300)
def load_matchups(collection: str, cid: str) -> dict | None:
    path = SITE_DATA / collection / "matchups" / f"{cid}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        return None


collections = list_collections()
if not collections:
    st.warning(
        "No exported `matchups/` found under site/public/data/. "
        "Run `uv run python scripts/export_site.py` first."
    )
    st.stop()

with st.sidebar:
    collection = st.selectbox(
        "Collection",
        options=collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="matchups-collection",
    )
    min_balls = st.slider(
        "Min balls", 1, 120, 6, step=1, help="Drops thin head-to-heads below this many balls."
    )

provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

sel = player_select(collection, key="matchups-player")
if not sel:
    st.info(f"No players for {collection}.")
    st.stop()

data = load_matchups(collection, sel["cricsheet_id"])
if not data:
    st.info(f"No matchup data for {sel['name']} (needs enough balls faced/bowled).")
    st.stop()

# --- pace vs spin splits -------------------------------------------------
splits = data.get("splits") or {}
seam = splits.get("vs_seam")
spin = splits.get("vs_spin")
if seam or spin:
    st.subheader("Pace vs spin")
    if seam and spin:
        weaker = "pace" if seam["sr"] < spin["sr"] else "spin" if spin["sr"] < seam["sr"] else None
        if weaker:
            st.caption(f"Weaker against **{weaker}** (lower strike rate).")
    cols = st.columns(4)
    if seam:
        cols[0].metric("vs Pace — SR", f"{seam['sr']:.1f}", help=f"{seam['balls']} balls")
        cols[1].metric(
            "vs Pace — out rate", f"{seam['out_rate']:.2f}%", help=f"{seam['outs']} dismissals"
        )
    if spin:
        cols[2].metric("vs Spin — SR", f"{spin['sr']:.1f}", help=f"{spin['balls']} balls")
        cols[3].metric(
            "vs Spin — out rate", f"{spin['out_rate']:.2f}%", help=f"{spin['outs']} dismissals"
        )

# --- as a batter ---------------------------------------------------------
as_bat = [r for r in (data.get("as_batter") or []) if r["balls"] >= min_balls]
if as_bat:
    st.subheader("As a batter — opponents faced")
    st.dataframe(
        [
            {
                "Bowler": r["bowler"],
                "Balls": r["balls"],
                "Runs": r["runs"],
                "SR": r["sr"],
                "Dot %": r["dot_pct"],
                "Outs": r["outs"],
            }
            for r in as_bat
        ],
        hide_index=True,
        width="stretch",
    )

# --- as a bowler ---------------------------------------------------------
as_bowl = [r for r in (data.get("as_bowler") or []) if r["balls"] >= min_balls]
if as_bowl:
    st.subheader("As a bowler — batters faced")
    st.dataframe(
        [
            {
                "Batter": r["batter"],
                "Balls": r["balls"],
                "Runs": r["runs"],
                "SR conceded": r["sr"],
                "Dot %": r["dot_pct"],
                "Wkts": r["outs"],
            }
            for r in as_bowl
        ],
        hide_index=True,
        width="stretch",
    )

if not as_bat and not as_bowl:
    st.info("No qualifying head-to-heads for this player.")
