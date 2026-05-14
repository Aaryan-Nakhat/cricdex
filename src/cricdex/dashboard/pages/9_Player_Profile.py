"""Streamlit page: per-player profile.

Pulls everything CricDex knows about a player into one card."""

from __future__ import annotations

import duckdb
import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.profiles import builder

DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

st.set_page_config(page_title="CricDex Profile", page_icon="🪪", layout="wide")
st.title("🪪 CricDex — player profile")
st.caption(
    "Everything CricDex knows about one player — cross-source IDs, "
    "Wikidata enrichment, career totals, novel metrics, Bayesian "
    "scout-rating skills, top style twins."
)


@st.cache_data
def list_players(collection: str) -> list[str]:
    safe = collection.replace("-", "_")
    if not DUCKDB_PATH.exists():
        return []
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if f"balls_{safe}" not in tables:
            return []
        rows = con.execute(
            f"""
            SELECT batter, COUNT(*) AS n
            FROM balls_{safe}
            WHERE batter IS NOT NULL
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 2000
            """
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


with st.sidebar:
    collection = st.text_input("Collection", value="ipl")
    pool = list_players(collection)
    if not pool:
        st.warning(f"no balls_{collection} — run cricsheet ingest first")
        st.stop()
    name = st.selectbox("Player", pool)

profile = builder.build(name, collection)

st.header(profile["name"])
ids = profile.get("ids") or {}
if ids:
    chips: list[str] = []
    for k, v in ids.items():
        if v and k != "unique_name":
            chips.append(f"`{k}={v}`")
    st.caption(" · ".join(chips))

wikidata = profile.get("wikidata") or {}
if wikidata:
    cols = st.columns(3)
    cols[0].metric("DOB", str(wikidata.get("dob") or "—"))
    cols[1].metric("Country", str(wikidata.get("country") or "—"))
    cols[2].metric("Gender", str(wikidata.get("gender") or "—"))

st.subheader("Career totals")
career = profile.get("career") or {}
c1, c2, c3, c4 = st.columns(4)
c1.metric("Runs", career.get("career_runs", 0))
c2.metric("Balls faced", career.get("career_balls_faced", 0))
c3.metric("Sixes", career.get("career_sixes", 0))
c4.metric("Wickets", career.get("career_wickets", 0))

st.subheader("Novel metrics")
metrics = profile.get("metrics") or {}
left, right = st.columns(2)
with left:
    st.markdown("**Pressure Runs**")
    st.json(metrics.get("pressure_runs") or {"_": "no row"})
    st.markdown("**Recoverability**")
    st.json(metrics.get("recoverability") or {"_": "no row"})
    st.markdown("**Counter-Attack**")
    st.json(metrics.get("counter_attack") or {"_": "no row"})
with right:
    st.markdown("**Boundary Dependency**")
    st.json(metrics.get("boundary_dependency") or {"_": "no row"})
    st.markdown("**Sticky Dot Pressure**")
    st.json(metrics.get("sticky_dot_pressure") or {"_": "no row"})
    st.markdown("**Bayesian scout-rating**")
    st.json(profile.get("bayes") or {"_": "no row"})

st.subheader("Style twins")
left, right = st.columns(2)
with left:
    st.markdown("**As batter**")
    twins = profile.get("style_twins_batter") or []
    if twins:
        st.dataframe(twins, use_container_width=True, hide_index=True)
    else:
        st.info("no batter style-twins available for this player + collection")
with right:
    st.markdown("**As bowler**")
    twins = profile.get("style_twins_bowler") or []
    if twins:
        st.dataframe(twins, use_container_width=True, hide_index=True)
    else:
        st.info("no bowler style-twins available for this player + collection")

st.subheader("🔗 Graph cohort (Neo4j)")
st.caption(
    "Players in the same competitive neighbourhood — derived from the scout "
    "graph's FACED and TEAMMATE_OF edges. Complements the cosine style-twins "
    "above with a relational signal."
)
try:
    from cricdex.scout.graph import similar

    g_col1, g_col2 = st.columns(2)
    with g_col1:
        st.markdown("**Co-faced bowlers cohort**")
        rows = similar.co_faced_bowlers(name, top_k=8)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("no graph cohort — populate scout graph for this collection")
    with g_col2:
        st.markdown("**Teammate overlap cohort**")
        rows = similar.teammate_overlap(name, top_k=8)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("no teammate overlap — populate scout graph")

    st.markdown(
        "**Suggested substitutes** (graph similarity × Bayes value, role-matched, on a 10 cr budget)"
    )
    try:
        from cricdex.auction import advisor

        rec = advisor.recommend_substitutes(name, budget=10.0, n=8)
        if rec.is_empty():
            st.info(
                "no affordable substitutes — try a higher budget via "
                "`scripts/auction_advisor.py` or the Auction page."
            )
        else:
            st.dataframe(rec.to_pandas(), use_container_width=True, hide_index=True)
    except ImportError:
        pass
except ImportError:
    st.info("`neo4j` extra not installed — run `uv sync --extra graph`.")

with st.expander("Raw profile JSON"):
    st.json(profile)
