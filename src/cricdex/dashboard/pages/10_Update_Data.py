"""Streamlit Update — refresh a collection, then re-export the JSON.

The "best of both worlds" refresh: re-ingest from Cricsheet → recompute
Bayesian ratings + the 12 leaderboards → re-export `site/public/data/` (the
same JSON the React web app and the other dashboard pages read). So an update
flows DuckDB → exported JSON → all pages, like the manual `refresh-data` Action.
"""

from __future__ import annotations

import streamlit as st

from cricdex import leagues
from cricdex.cli.data_cmd import run_export, run_ingest

st.set_page_config(page_title="CricDex Update", page_icon="🔄", layout="wide")
st.title("🔄 CricDex — refresh data")
st.caption(
    "Re-ingest → recompute ratings + metrics → re-export the JSON every page reads "
    "(the same pipeline the refresh workflow runs). Updates DuckDB, then the "
    "exported JSON; all other pages read that JSON, so they reflect the refresh."
)

_keys = leagues.keys()  # every league in config/leagues.toml; exported ones first (registry order)
collection = st.selectbox(
    "Collection",
    _keys,
    index=_keys.index("ipl") if "ipl" in _keys else 0,
    format_func=lambda k: (
        f"{leagues.label(k)} ({k})" + ("" if leagues.get(k).export else " · not exported")
    ),
    help="Every league in config/leagues.toml — add one there to see it here.",
)
force = st.checkbox("Force regenerate (ignore cached)", value=True)
st.divider()


def _run_slice(slice_: str) -> bool:
    with st.spinner(f"ingest {slice_} ({collection}) …"):
        try:
            msg = run_ingest(slice_, collection=collection, force=force)
        except Exception as e:  # noqa: BLE001
            st.error(f"**{slice_}** failed: {e}")
            return False
    st.success(f"**{slice_}** → {msg}")
    st.cache_data.clear()
    return True


def _run_export() -> bool:
    with st.spinner(f"export_site.py -c {collection} …"):
        try:
            run_export(collection)
        except Exception as e:  # noqa: BLE001
            st.error(f"export failed:\n\n```\n{e}\n```")
            return False
    st.success("re-exported JSON ✅ — other pages now read the new data.")
    st.cache_data.clear()
    return True


st.markdown("**Individual steps** (run in order: cricsheet → ratings → metrics → export):")
c = st.columns(5)
if c[0].button("1· Cricsheet", width="stretch"):
    _run_slice("cricsheet")
if c[1].button("2· Ratings", width="stretch"):
    _run_slice("ratings")
if c[2].button("3· Metrics", width="stretch"):
    _run_slice("metrics")
if c[3].button("Wikidata", width="stretch"):
    _run_slice("wikidata")
if c[4].button("4· Re-export JSON", width="stretch"):
    _run_export()

st.divider()
if st.button("⚡ Full refresh — ingest → ratings → metrics → export", type="primary"):
    # metrics also rebuilds the site JSON; stop at the first failed step instead of claiming success
    if all(_run_slice(s) for s in ("cricsheet", "ratings", "metrics")):
        st.success("Full refresh complete. Switch to any page — it reads the fresh JSON.")
    else:
        st.warning("Full refresh stopped at the failed step above — fix it and run again.")
