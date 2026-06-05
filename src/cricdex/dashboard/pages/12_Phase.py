"""Streamlit page: Phase specialists — powerplay / middle / death boards.

Reads the SAME exported JSON the web app (`site/src/pages/Phase.tsx`) fetches —
`site/public/data/<collection>/phase.json` — so the desktop dashboard matches
the live site.
"""

from __future__ import annotations

import json

import streamlit as st

from cricdex.dashboard._widgets import provenance_banner
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Phase", page_icon="⏱️", layout="wide")
st.title("⏱️ CricDex — phase specialists")
st.caption(
    "Who actually dominates each phase of the innings — best strike rates with "
    "the bat and tightest economies with the ball across the powerplay, middle "
    "overs and death. Same exported data as the website."
)

PHASES = {
    "powerplay": "Powerplay (overs 1–6)",
    "middle": "Middle (overs 7–15)",
    "death": "Death (overs 16–20)",
}


def _has_phase(collection: str) -> bool:
    return (SITE_DATA / collection / "phase.json").exists()


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    names = sorted(p.name for p in SITE_DATA.iterdir() if p.is_dir())
    return [c for c in names if _has_phase(c)]


@st.cache_data(ttl=300)
def load_phase(collection: str) -> dict:
    path = SITE_DATA / collection / "phase.json"
    return json.loads(path.read_text()) if path.exists() else {}


collections = list_collections()
if not collections:
    st.warning(
        "No exported `phase.json` found under site/public/data/. "
        "Run `uv run python scripts/export_site.py` first."
    )
    st.stop()

with st.sidebar:
    collection = st.selectbox(
        "Collection",
        options=collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="phase-collection",
    )

provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

data = load_phase(collection)
if not data:
    st.info(f"No phase data for {collection}.")
    st.stop()

phase = st.radio(
    "Phase", list(PHASES), format_func=lambda p: PHASES[p], horizontal=True, key="phase-pick"
)
board = data.get(phase) or {}

left, right = st.columns(2)
with left:
    st.subheader("Best strike rates")
    batters = board.get("batters") or []
    if batters:
        st.dataframe(
            [
                {"Batter": r["name"], "Runs": r["runs"], "Balls": r["balls"], "SR": r["sr"]}
                for r in batters
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No qualifying batters.")
with right:
    st.subheader("Tightest economies")
    bowlers = board.get("bowlers") or []
    if bowlers:
        st.dataframe(
            [
                {
                    "Bowler": r["name"],
                    "Wkts": r["wickets"],
                    "Balls": r["balls"],
                    "Runs": r["runs"],
                    "Economy": r["econ"],
                }
                for r in bowlers
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No qualifying bowlers.")
