"""Streamlit page: Phase specialists — powerplay / middle / death boards.

Reads the SAME exported JSON the web app (`site/src/pages/Phase.tsx`) fetches —
`site/public/data/<collection>/phase.json` — so the desktop dashboard matches
the live site. Same player filter bar as Leaderboards (rows carry the taxonomy
+ activity + match count).
"""

from __future__ import annotations

import json

import streamlit as st

from cricdex.common.filters import (
    ACTIVITY_OPTS,
    BOWLING_OPTS,
    FILTER_HELP,
    POSITION_OPTS,
    ROLE_OPTS,
    Filters,
    apply_filters,
    countries_in,
)
from cricdex.dashboard._widgets import provenance_banner
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Phase", page_icon="⏱️", layout="wide")
st.title("⏱️ CricDex — phase specialists")
st.caption(
    "Who actually dominates each phase of the innings — best strike rates with "
    "the bat and tightest economies with the ball across the powerplay, middle "
    "overs and death. Same exported data + filter bar as the website."
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


def _select(label: str, opts: list[tuple[str, str]], key: str, help_: str | None = None) -> str:
    values = [v for v, _ in opts]
    labels = dict(opts)
    return st.selectbox(label, values, format_func=lambda v: labels[v], key=key, help=help_)


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
all_rows = [*(board.get("batters") or []), *(board.get("bowlers") or [])]

with st.sidebar:
    st.divider()
    min_matches = st.slider("Min matches", 0, 100, 0, step=5, help=FILTER_HELP["min_matches"])
    activity = _select("Activity", ACTIVITY_OPTS, "ph_activity", FILTER_HELP["activity"])
    role = _select("Role", ROLE_OPTS, "ph_role", FILTER_HELP["role"])
    bowling = _select("Bowling", BOWLING_OPTS, "ph_bowling", FILTER_HELP["bowling"])
    position = _select("Batting position", POSITION_OPTS, "ph_position", FILTER_HELP["position"])
    country = _select("Country", countries_in(all_rows), "ph_country", FILTER_HELP["country"])
    top_n = st.slider("Top N", 5, 50, 25, step=5)

filters = Filters(
    min_matches=min_matches,
    activity=activity,
    role=role,
    bowling=bowling,
    position=position,
    country=country,
)
batters = apply_filters(board.get("batters") or [], filters)[:top_n]
bowlers = apply_filters(board.get("bowlers") or [], filters)[:top_n]

left, right = st.columns(2)
with left:
    st.subheader("Best strike rates")
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
        st.info("No batters match these filters.")
with right:
    st.subheader("Tightest economies")
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
        st.info("No bowlers match these filters.")
