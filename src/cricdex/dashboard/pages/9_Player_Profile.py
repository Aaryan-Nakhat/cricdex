"""Streamlit page: per-player profile.

Pulls everything CricDex knows about a player into one card. Inputs
go through the fuzzy resolver so typos / partial names are caught
with a 'did you mean?' confirmation.
"""

from __future__ import annotations

import duckdb
import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.dashboard._widgets import fuzzy_player_input, provenance_banner
from cricdex.profiles import builder

DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

st.set_page_config(page_title="CricDex Profile", page_icon="🪪", layout="wide")
st.title("🪪 CricDex — player profile")
st.caption(
    "Everything CricDex knows about one player — cross-source IDs, "
    "career totals, novel metrics, Bayesian scout-rating skills, "
    "top style twins, and the graph cohort. All derived live from "
    "Cricsheet ball-by-ball + the People Register."
)
provenance_banner(source="cricsheet", path=DUCKDB_PATH)


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
        st.warning(
            f"no balls_{collection} — run `cricdex data ingest cricsheet -c {collection}` first"
        )
        st.stop()
    st.markdown("Type a player name — fuzzy-matched against the collection.")
    name = fuzzy_player_input(
        label="Player",
        default="V Kohli",
        collection=collection,
        key="profile-player",
    )
    if not name:
        st.info("Confirm a player above to load the profile.")
        st.stop()

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
METRIC_HINTS = {
    "pressure_runs": (
        "Strike rate on balls where the required run rate is ≥ 1.5× the venue "
        "median (chase only). Higher = better under pressure."
    ),
    "recoverability": (
        "How efficiently this batter recovers after a slow patch. Higher = "
        "doesn't let one dot ball spiral."
    ),
    "counter_attack": (
        "Strike rate inflation right after a wicket falls. Higher = aggressive "
        "after partnership-breaking dismissals."
    ),
    "boundary_dependency": (
        "Share of runs from 4s + 6s. Higher = boundary-reliant; lower = strong " "strike-rotator."
    ),
    "sticky_dot_pressure": (
        "Wicket rate on the next ball after a 4+ consecutive dot streak in the "
        "same over (bowler metric). Higher = turns pressure into dismissals."
    ),
}


def _metric_to_rows(slug: str, payload) -> list[dict]:
    if not payload:
        return [
            {
                "value": "—",
                "note": "no data — below min-balls threshold or not computed for this collection",
            }
        ]
    if isinstance(payload, dict):
        return [
            {"field": k, "value": v}
            for k, v in payload.items()
            if k not in {"batter", "bowler", "cricsheet_id"} and v is not None
        ] or [{"value": "—", "note": "all fields empty"}]
    return [{"value": str(payload)}]


for slug, hint in METRIC_HINTS.items():
    with st.expander(f"**{slug.replace('_', ' ').title()}** — {hint}"):
        st.table(_metric_to_rows(slug, metrics.get(slug)))


st.markdown("### Bayesian scout-rating")
bayes = profile.get("bayes") or {}


def _bayes_sentence(role_key: str, label: str) -> str:
    skill = bayes.get(f"bayes_skill_{role_key}")
    sd = bayes.get(f"bayes_skill_sd_{role_key}")
    balls = bayes.get(f"bayes_balls_{role_key}")
    if skill is None:
        return f"{label}: not enough data."
    confidence = "high" if (sd or 1) < 0.05 else ("medium" if (sd or 1) < 0.10 else "low")
    return (
        f"{label}: **{skill:+.3f}** ({confidence} confidence; "
        f"σ={sd:.3f} on {balls or '?'} balls)."
    )


st.markdown(_bayes_sentence("batter", "Batter skill"))
st.markdown(_bayes_sentence("bowler", "Bowler skill"))
st.caption(
    "Skill is on the natural-log scale of the NumPyro / JAX hierarchical "
    "Negative-Binomial fit. 0 = league average. +0.30 ≈ marquee; -0.30 ≈ "
    "replacement-level."
)

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
