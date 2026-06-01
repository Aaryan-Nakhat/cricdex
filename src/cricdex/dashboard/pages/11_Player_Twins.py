"""Streamlit page: graph-traversal Player Twins / replacement finder.

Three views over the scout Neo4j graph:

- **Co-faced bowlers** — players who FACED the most distinct bowlers
  in common with the target. Best for batter affinity.
- **Teammate overlap** — players sharing the most distinct teammates,
  weighted by `matches_together`. Best for "same competitive cohort".
- **Find replacement** — auto-flips the FACED traversal direction
  based on the target's `role`, applies recency + balls + role
  filters, returns the candidate cohort. Best for "next Bumrah" /
  "next Kohli" workflows.

Requires a populated Neo4j (`make docker-scout-up && make
docker-scout-populate COLLECTION=ipl`) and the `scout` extras
installed (`uv sync --extra graph`).
"""

from __future__ import annotations

import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.dashboard._widgets import collection_picker, fuzzy_player_input, provenance_banner

st.set_page_config(page_title="CricDex Player Twins", page_icon="🔗", layout="wide")
st.title("🔗 CricDex — player twins & replacement finder")
st.caption(
    "Graph-traversal similarity over the scout Neo4j (FACED + TEAMMATE_OF + "
    "PLAYED_IN edges built from Cricsheet ball-by-ball). Use this when you "
    "want a relational signal — 'same competitive neighbourhood as X' — "
    "instead of a feature-vector cosine."
)
provenance_banner(source="cricsheet", path=DATA_DIR / "cricsheet" / "cricsheet.duckdb")


try:
    from cricdex.scout.graph import similar
except ImportError as e:
    st.error(f"`neo4j` extra not installed ({e}). Run `uv sync --extra graph` and retry.")
    st.stop()


@st.cache_data(ttl=600, show_spinner=False)
def _co_faced(name: str, k: int, collection: str):
    return similar.co_faced_bowlers(name, top_k=k, collection=collection)


@st.cache_data(ttl=600, show_spinner=False)
def _teammates(name: str, k: int, collection: str):
    return similar.teammate_overlap(name, top_k=k, collection=collection)


@st.cache_data(ttl=600, show_spinner=False)
def _replacement(name, k, role, style, max_bw, max_bt, min_last, collection):
    return similar.find_replacement(
        name,
        top_k=k,
        role=role or None,
        bowling_style=style or None,
        max_balls_bowled=max_bw,
        max_balls_faced=max_bt,
        min_last_match_date=min_last or None,
        collection=collection,
    )


with st.sidebar:
    collection = collection_picker(default="ipl", key="twins-collection")
    mode = st.radio(
        "Query",
        ["Find replacement", "Co-faced bowlers", "Teammate overlap"],
        index=0,
    )
    name = fuzzy_player_input(
        label="Target player",
        default="JJ Bumrah",
        collection=collection,
        key="twins-target",
    )
    top_k = st.slider(
        "Top-K",
        5,
        25,
        10,
        help="Number of suggested cohort rows to show. Sorted by shared-count descending.",
    )
    if not name:
        st.info("Confirm a player above to query the graph.")
        st.stop()
    role = ""
    style = ""
    max_balls_bowled: int | None = None
    max_balls_faced: int | None = None
    min_last_match: str = ""
    if mode == "Find replacement":
        # Auto-detect the target's role so the default is sensible —
        # a Bumrah replacement should return bowlers, not batters.
        from cricdex.scout.graph.schema import driver as _drv

        _target_role = "bowler"
        try:
            _d = _drv()
            with _d.session() as _s:
                _row = _s.run(
                    "MATCH (p:Player {unique_name:$n}) RETURN p.role AS role",
                    n=name,
                ).single()
                if _row and _row["role"]:
                    _target_role = _row["role"]
            _d.close()
        except Exception:
            pass
        _role_options = ["bowler", "batter", "all_rounder", ""]
        _default_idx = _role_options.index(_target_role) if _target_role in _role_options else 0
        role = st.selectbox(
            "Role filter",
            _role_options,
            index=_default_idx,
            help=(f"Default = the target's own role (here: {_target_role}). Empty = no filter."),
        )
        style = st.selectbox(
            "Bowling style (bowler replacements only)",
            ["", "pace", "spin"],
            index=0,
            help=(
                "Filter bowler candidates by pace vs spin. Source mix: "
                "curated overrides for known edge cases + middle-overs "
                "heuristic for the rest. Empty = no filter."
            ),
        )
        max_balls_bowled = st.number_input(
            "Max balls bowled (career)", value=2000, step=100, min_value=0
        )
        max_balls_faced = st.number_input(
            "Max balls faced (career)", value=10000, step=500, min_value=0
        )
        min_last_match = st.text_input("Min last-match date (YYYY-MM-DD)", value="2023-01-01")


with st.spinner(f"querying graph for {name!r} …"):
    if mode == "Co-faced bowlers":
        rows = _co_faced(name, top_k, collection)
        st.subheader(f"Top-{top_k} players sharing FACED bowlers with {name}")
    elif mode == "Teammate overlap":
        rows = _teammates(name, top_k, collection)
        st.subheader(f"Top-{top_k} players sharing teammates with {name}")
    else:
        rows = _replacement(
            name,
            top_k,
            role,
            style,
            int(max_balls_bowled) if max_balls_bowled is not None else None,
            int(max_balls_faced) if max_balls_faced is not None else None,
            min_last_match,
            collection,
        )
        st.subheader(f"Replacement candidates for {name}")


if not rows:
    st.warning(
        "No candidates returned. Common causes: name typo (case sensitive), "
        "filters too tight, or scout graph not populated for this collection."
    )
    st.stop()


import pandas as pd  # noqa: E402

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)
st.caption(
    "Tip: re-run `make docker-scout-populate COLLECTION=ipl` after each "
    "Cricsheet ingest so the graph reflects the latest balls."
)
