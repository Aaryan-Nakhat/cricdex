"""Streamlit page: Partnerships — batter-pair stands.

Reads the SAME exported JSON the web app (`site/src/pages/Partnerships.tsx`)
fetches — `site/public/data/<collection>/partnerships.json` — so the desktop
dashboard matches the live site.
"""

from __future__ import annotations

import streamlit as st

from cricdesk.common.display import display_name, league_label
from cricdesk.dashboard._widgets import player_select, provenance_banner, read_json
from cricdesk.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDesk Partnerships", page_icon="🤝", layout="wide")
st.title("🤝 CricDesk — partnerships")
st.caption(
    "Batter-pair stands — who builds runs together. Pick a player for their most "
    "productive partners, or browse the all-time best partnerships. Same exported "
    "data as the website. Runs include extras added while both were at the crease."
)


def _has_partnerships(collection: str) -> bool:
    return (SITE_DATA / collection / "partnerships.json").exists()


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    names = sorted(p.name for p in SITE_DATA.iterdir() if p.is_dir())
    return [c for c in names if _has_partnerships(c)]


@st.cache_data(ttl=300)
def load_partnerships(collection: str) -> list[dict]:
    return read_json(SITE_DATA / collection / "partnerships.json", {}).get("pairs", [])


collections = list_collections()
if not collections:
    st.warning(
        "No exported `partnerships.json` found under site/public/data/. "
        "Run `uv run python scripts/export_site.py` first."
    )
    st.stop()

with st.sidebar:
    collection = st.selectbox(
        "Collection",
        options=collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="partnerships-collection",
        format_func=league_label,
    )
    min_runs = st.slider("Min runs", 0, 500, 50, step=10, help="Aggregate runs for the pair.")

provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

pairs = [p for p in load_partnerships(collection) if p["runs"] >= min_runs]

sel = player_select(collection, key="partnerships-player", default_name=None)
if sel:
    cid = sel["cricsheet_id"]
    mine = [p for p in pairs if cid in (p.get("a_cid"), p.get("b_cid"))]
    mine.sort(key=lambda p: p["runs"], reverse=True)
    st.subheader(f"Most productive partners — {display_name(sel)}")
    if mine:
        st.dataframe(
            [
                {
                    "Partner": display_name(p, "b")
                    if p.get("a_cid") == cid
                    else display_name(p, "a"),
                    "Runs": p["runs"],
                    "Inns": p["innings"],
                    "Best": p["best"],
                    "Avg": p["avg"],
                    "SR": p["sr"],
                    "50+": p["fifties"],
                    "100+": p["hundreds"],
                }
                for p in mine
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info(f"No partnerships at ≥ {min_runs} runs for {display_name(sel)}.")

st.subheader("Best partnerships (all-time)")
st.dataframe(
    [
        {
            "Partnership": f"{display_name(p, 'a')} & {display_name(p, 'b')}",
            "Runs": p["runs"],
            "Inns": p["innings"],
            "Best": p["best"],
            "Avg": p["avg"],
            "SR": p["sr"],
            "100+": p["hundreds"],
        }
        for p in pairs[:60]
    ],
    hide_index=True,
    width="stretch",
)
