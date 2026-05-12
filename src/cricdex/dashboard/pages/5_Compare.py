"""Streamlit page: side-by-side player comparator."""

from __future__ import annotations

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cricdex.comparator import compare as cmp
from cricdex.config import DATA_DIR

DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

st.set_page_config(page_title="CricDex Compare", page_icon="🆚", layout="wide")
st.title("🆚 CricDex — compare players")
st.caption("Pick 2-5 players and see their novel metrics + career totals side by side.")


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
    collection = st.text_input("Collection", value="ipl")
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
st.dataframe(pdf.T, use_container_width=True)

st.subheader("Radar — normalised z-scores across the picked players")
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
