"""Streamlit page: cricket records + On-This-Day."""

from __future__ import annotations

import datetime as dt

import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.dashboard._widgets import provenance_banner
from cricdex.records import queries

st.set_page_config(page_title="CricDex Records", page_icon="📜", layout="wide")
st.title("📜 CricDex — records")
st.caption(
    "Records derived directly from Cricsheet ball-by-ball — every row is "
    "computed live from the DuckDB table for whichever collection you pick. "
    "Pick a record key from the sidebar; switch to On-This-Day for the "
    "calendar-anniversary digest."
)
provenance_banner(source="cricsheet", path=DATA_DIR / "cricsheet" / "cricsheet.duckdb")

RECORD_LABELS: dict[str, str] = {
    "highest_individual_innings": "Highest individual innings",
    "fastest_fifty": "Fastest fifty (balls)",
    "fastest_hundred": "Fastest hundred (balls)",
    "most_sixes_innings": "Most sixes in an innings",
    "career_run_leaders": "Career run leaders",
    "best_bowling_innings": "Best bowling figures",
    "career_wicket_leaders": "Career wicket leaders",
    "highest_team_totals": "Highest team totals",
    "highest_runs_in_over": "Highest runs conceded in an over",
}

with st.sidebar:
    collection = st.text_input("Cricsheet collection", value="ipl")
    top_n = st.slider("Top N", min_value=5, max_value=100, value=25)

records_tab, otd_tab = st.tabs(["📊 Records", "🗓️ On This Day"])

with records_tab:
    cols = st.columns(2)
    items = list(RECORD_LABELS.items())
    half = (len(items) + 1) // 2
    for col, group in zip(cols, [items[:half], items[half:]], strict=True):
        with col:
            for slug, label in group:
                with st.expander(label):
                    try:
                        df = queries.RECORDS[slug](collection, top_n=top_n)
                        st.dataframe(df.to_pandas(), use_container_width=True, hide_index=True)
                    except Exception as e:
                        st.error(f"query failed: {e}")

with otd_tab:
    today = dt.date.today()
    col1, col2 = st.columns(2)
    with col1:
        month = st.number_input("Month", 1, 12, today.month)
    with col2:
        day = st.number_input("Day", 1, 31, today.day)
    df = queries.on_this_day(int(month), int(day), collection, top_n=top_n)
    if df.is_empty():
        st.info("No notable performances logged on this calendar date in the corpus.")
    else:
        st.dataframe(df.to_pandas(), use_container_width=True, hide_index=True)
