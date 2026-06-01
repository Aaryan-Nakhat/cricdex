"""Streamlit page: side-by-side player comparator."""

from __future__ import annotations

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cricdex.comparator import compare as cmp
from cricdex.config import DATA_DIR
from cricdex.dashboard._widgets import collection_picker, provenance_banner

DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

st.set_page_config(page_title="CricDex Compare", page_icon="🆚", layout="wide")
st.title("🆚 CricDex — compare players")
st.caption(
    "Pick 2–5 players and see every CricDex signal side-by-side: career totals "
    "(from Cricsheet ball-by-ball), the six novel batter metrics + Sticky Dot "
    "Pressure (bowler), and Bayes scout-rating skills."
)
provenance_banner(source="cricsheet", path=DUCKDB_PATH)


FIELD_NOTES = {
    "career_runs": "Career runs scored (Cricsheet)",
    "career_balls": "Career balls faced",
    "career_sixes": "Career 6s",
    "career_fours": "Career 4s",
    "career_matches": "Career matches",
    "career_wickets": "Career wickets taken",
    "career_runs_conceded": "Career runs conceded",
    "career_legal_balls_bowled": "Career legal balls bowled",
    "pressure_runs": "Runs scored under high required-RR (chase only)",
    "pressure_runs_sr": "Strike rate under high required-RR",
    "pct_pressure_balls": "% of career balls played under high required-RR",
    "recoverability": "Recovery efficiency after slow patches",
    "counter_attack_sr": "Strike rate inflation right after a wicket",
    "bdr_pct": "Boundary dependency — share of runs from 4s + 6s",
    "sticky_wicket_rate_pct": "Wicket rate after 4+ consecutive dot streak in same over",
    "bayes_skill_batter": "NumPyro hierarchical batter skill (0 = avg, +0.3 ≈ marquee)",
    "bayes_skill_bowler": "NumPyro hierarchical bowler skill (0 = avg, +0.3 ≈ marquee)",
}


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
            SELECT batter AS name, COUNT(*) AS n
            FROM balls_{safe}
            WHERE batter IS NOT NULL
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 1500
            """
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


with st.sidebar:
    collection = collection_picker(default="ipl", key="compare-collection")
    pool = list_players(collection)
    if not pool:
        st.warning(f"no balls_{collection} table — run docker-ingest-cricsheet first")
        st.stop()
    picks = st.multiselect("Players (2-5)", options=pool, max_selections=5)

if len(picks) < 2:
    st.info("Pick at least 2 players in the sidebar.")
    st.stop()

df = cmp.compare(picks, collection=collection)
if df.is_empty():
    st.error("No data returned.")
    st.stop()

pdf = df.to_pandas().set_index("player")
st.subheader("Side-by-side metrics")
st.caption(
    "Empty cells (—) mean the player didn't clear the metric's min-balls / "
    "min-matches threshold, or wasn't in the saved top-N for this collection. "
    "Hover any row label to see what the metric measures."
)

# Pretty render: replace NaN with "—" and attach the FIELD_NOTES tooltip
# so non-developer viewers know what each row means.
display = pdf.T.copy()
display = display.where(display.notna(), "—")
display = display.replace({None: "—", "": "—"})
# Streamlit renders dict-of-columns; add a "what is this" column for hover.
display.insert(0, "what is this", [FIELD_NOTES.get(idx, "") for idx in display.index])
st.dataframe(display, use_container_width=True)

st.subheader("Radar — relative strength across the picked players")
st.caption(
    "Each axis is z-scored across the players you picked, so the chart reads "
    "as 'who is relatively strongest on which axis'. Larger area = stronger "
    "on more axes. Z-scores reset every time you change the player picks — "
    "this is a within-cohort comparison, not a cross-league absolute rank."
)
radar_axes = [
    "pressure_runs",
    "pressure_runs_sr",
    "pct_pressure_balls",
    "recoverability",
    "counter_attack_sr",
    "bdr_pct",
    "bayes_skill_batter",
]
radar = pdf[radar_axes].astype(float)


# z-score across the picked players so visual differences read as "X is
# the relative best for that axis." If the axis is all-NaN/zero for these
# picks we silently drop it from the chart.
def _z(col: pd.Series) -> pd.Series:
    col = col.fillna(col.mean())
    if col.std() == 0 or pd.isna(col.std()):
        return col * 0
    return (col - col.mean()) / col.std()


z_df = radar.apply(_z, axis=0).fillna(0)

fig = go.Figure()
for player, row in z_df.iterrows():
    fig.add_trace(
        go.Scatterpolar(
            r=row.tolist() + [row.iloc[0]],
            theta=radar_axes + [radar_axes[0]],
            fill="toself",
            name=player,
        )
    )
fig.update_layout(
    polar={"radialaxis": {"visible": True}},
    showlegend=True,
    height=500,
)
st.plotly_chart(fig, use_container_width=True)

# --- Bayesian skill head-to-head (pairwise) -----------------------------

st.subheader("🎯 Bayesian skill head-to-head")
st.caption(
    "How confident are we that one player is genuinely better than another? "
    "Each player's opponent-adjusted skill is a Bayesian posterior — a mean "
    "and an uncertainty. We take the difference of the two posteriors and "
    "report **P(A is better than B)**. A result near 50% means the two are "
    "statistically indistinguishable given the data (most 'X vs Y' debates "
    "land here). Skill measures scoring / run-suppression *rate*, not "
    "dismissal-adjusted value — that's a vNext model upgrade."
)

from cricdex.scout.ratings.head_to_head import head_to_head  # noqa: E402

hcol1, hcol2 = st.columns(2)
player_a = hcol1.selectbox("Player A", options=picks, index=0)
player_b = hcol2.selectbox("Player B", options=picks, index=1 if len(picks) > 1 else 0)

if player_a == player_b:
    st.info("Pick two different players for the head-to-head.")
else:
    h2h = head_to_head(player_a, player_b, collection=collection)
    if h2h.get("error"):
        st.warning(h2h["error"])
    else:
        any_role = False
        for role in ("batter", "bowler", "all_rounder"):
            c = h2h["comparisons"].get(role)
            if c is None:
                continue
            any_role = True
            label = role.replace("_", "-").title()
            st.markdown(f"**{label}**  ·  {c['verdict']}")
            m1, m2, m3 = st.columns(3)
            m1.metric(
                f"{player_a} skill",
                f"{c['mean_a']:+.3f}",
                help=f"± {c['sd_a']:.3f} on {c.get('balls_a', '?')} balls",
            )
            m2.metric(
                f"{player_b} skill",
                f"{c['mean_b']:+.3f}",
                help=f"± {c['sd_b']:.3f} on {c.get('balls_b', '?')} balls",
            )
            m3.metric(f"P({player_a} better)", f"{c['p_a_better']:.0%}")
            st.progress(c["p_a_better"])
        if not any_role:
            st.info(
                "These two players have no overlapping Bayesian ratings for "
                f"this collection — run `cricdex data ingest ratings -c {collection}`."
            )
