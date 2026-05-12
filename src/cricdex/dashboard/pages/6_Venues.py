"""Streamlit page: pitch + conditions archive per venue."""

from __future__ import annotations

import streamlit as st

from cricdex.venues import profile

st.set_page_config(page_title="CricDex Venues", page_icon="🏟️", layout="wide")
st.title("🏟️ CricDex — pitch + conditions archive")
st.caption(
    "Every number aggregated live from the Cricsheet ball-by-ball table. "
    "Useful for pre-match prep, chase vs set decisions, and phase-by-phase "
    "scoring expectations."
)


with st.sidebar:
    collection = st.text_input("Collection", value="ipl")
    min_matches = st.slider("Min matches to list a venue", 1, 30, 5)

venues_df = profile.list_venues(collection, min_matches=min_matches)
if venues_df.is_empty():
    st.warning(f"no venues_{collection} table yet — run docker-ingest-cricsheet first")
    st.stop()

with st.sidebar:
    venue = st.selectbox(
        "Venue",
        options=venues_df["venue"].to_list(),
        format_func=lambda v: (
            f"{v}  ({venues_df.filter(__import__('polars').col('venue') == v)['matches'][0]})"
        ),
    )

st.subheader(venue)
st.write(
    f"Sample size: **{venues_df.filter(__import__('polars').col('venue') == venue)['matches'][0]}** "
    f"matches in `{collection}`."
)

col1, col2 = st.columns(2)
with col1:
    st.markdown("### Innings totals")
    df = profile.innings_totals(venue, collection)
    st.dataframe(df.to_pandas(), use_container_width=True, hide_index=True)

    st.markdown("### Chase vs set")
    df = profile.chase_vs_set_winrate(venue, collection)
    st.dataframe(df.to_pandas(), use_container_width=True, hide_index=True)

with col2:
    st.markdown("### Phase-by-phase run rate")
    df = profile.phase_run_rates(venue, collection)
    st.dataframe(df.to_pandas(), use_container_width=True, hide_index=True)

    st.markdown("### Dismissal mix")
    df = profile.dismissal_mix(venue, collection)
    st.dataframe(df.to_pandas(), use_container_width=True, hide_index=True)
