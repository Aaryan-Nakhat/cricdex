"""CricDex Leaderboards — the same 10 metrics as the web app.

Reads the exported leaderboard JSON the React site uses
(`site/public/data/<collection>/leaderboards/<slug>.json`) so the
rankings are identical to the live site. Each metric is one tab.
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from cricdex.dashboard._widgets import provenance_banner
from cricdex.web_parity.loader import SITE_DATA

# Mirrors site/src/lib/metrics.ts — name, sort column, name column, direction.
METRICS: list[dict] = [
    {
        "slug": "ngi",
        "name": "NGI (Net Game Impact)",
        "col": "ngi_per_match",
        "who": "name",
        "higher": True,
        "desc": "WPA-style flagship — runs added vs a replacement player, batting + bowling, per match.",
    },
    {
        "slug": "pressure_runs",
        "name": "Pressure Runs",
        "col": "pressure_sr_per_100_balls",
        "who": "batter",
        "higher": True,
        "desc": "Strike rate when the required rate is climbing in a chase.",
    },
    {
        "slug": "intent_curve",
        "name": "Intent Curve",
        "col": "early_sr",
        "who": "batter",
        "higher": True,
        "desc": "Early SR (balls 1–10) — who comes out firing; the full innings curve is the sparkline column.",
        "extra": ["peak_sr", "balls", "curve"],
    },
    {
        "slug": "dot_ball_recovery",
        "name": "Dot-Ball Recovery",
        "col": "runs_per_6_after_dot",
        "who": "batter",
        "higher": True,
        "desc": "Runs in the six balls after a dot — quick re-engagement vs letting dots compound.",
    },
    {
        "slug": "counter_attack",
        "name": "Counter-Attack",
        "col": "counter_attack_sr",
        "who": "batter",
        "higher": True,
        "desc": "Strike rate immediately after a partner is dismissed.",
    },
    {
        "slug": "boundary_dependency",
        "name": "Boundary Dependency",
        "col": "bdr_pct",
        "who": "batter",
        "higher": False,
        "desc": "Share of runs from 4s + 6s. Lower = rotates strike; higher = relies on the rope.",
    },
    {
        "slug": "pressure_conversion",
        "name": "Pressure Conversion",
        "col": "wicket_rate_pct",
        "who": "bowler",
        "higher": True,
        "desc": "How often a bowler turns built-up pressure (a dot streak) into a wicket.",
    },
    {
        "slug": "wicket_quality",
        "name": "Wicket Quality",
        "col": "wicket_quality",
        "who": "bowler",
        "higher": True,
        "desc": "Wickets weighted by the Bayesian batting skill of the batter dismissed.",
    },
    {
        "slug": "crease_longevity",
        "name": "Crease Longevity",
        "col": "longevity_index",
        "who": "batter",
        "higher": True,
        "desc": "Balls survived per dismissal vs the cohort. 1.3 = lasts 30% longer than peers.",
    },
    {
        "slug": "slow_start_cost",
        "name": "Slow-Start Cost",
        "col": "slow_start_cost",
        "who": "batter",
        "higher": False,
        "desc": "Career SR minus setting (1st-innings) SR. Lower (or negative) is better.",
    },
]


@st.cache_data(ttl=300)
def discover_collections() -> list[str]:
    cols = [d.name for d in SITE_DATA.iterdir() if d.is_dir() and (d / "leaderboards").is_dir()]
    return sorted(cols) or ["ipl"]


@st.cache_data(ttl=300)
def load_metric(slug: str, collection: str) -> pd.DataFrame:
    path = SITE_DATA / collection / "leaderboards" / f"{slug}.json"
    if not path.exists():
        return pd.DataFrame()
    return pd.DataFrame(json.loads(path.read_text()))


def render() -> None:
    st.set_page_config(page_title="CricDex Leaderboards", page_icon="🏏", layout="wide")
    st.title("🏏 CricDex — leaderboards")
    st.caption(
        "The 10 novel impact metrics — identical to the web app (reads the same exported "
        "data). Each isolates a skill that batting average / economy can't see. Pick a metric "
        "tab; filter by minimum matches in the sidebar."
    )
    provenance_banner(source="cricsheet", path=SITE_DATA / "ipl" / "meta.json")

    collections = discover_collections()
    with st.sidebar:
        collection = st.selectbox(
            "Collection", collections, index=collections.index("ipl") if "ipl" in collections else 0
        )
        min_matches = st.slider(
            "Min matches", 0, 100, 20, step=5, help="Keeps 1-match flukes off the top."
        )
        top_n = st.slider("Top N", 10, 200, 25, step=5)

    tabs = st.tabs([m["name"] for m in METRICS])
    for tab, m in zip(tabs, METRICS, strict=True):
        with tab:
            st.subheader(m["name"])
            st.caption(m["desc"])
            df = load_metric(m["slug"], collection)
            if df.empty or m["col"] not in df.columns:
                st.info(
                    f"No `{m['slug']}` data for `{collection}` — run `cricdex data ingest metrics -c {collection}` then re-export."
                )
                continue
            if "matches" in df.columns:
                df = df[df["matches"].fillna(0) >= min_matches]
            df = df.sort_values(m["col"], ascending=not m["higher"]).head(top_n)
            who = (
                m["who"]
                if m["who"] in df.columns
                else ("batter" if "batter" in df.columns else "name")
            )

            # Columns to show: name, primary, any extras, matches.
            cols = [who, m["col"], *[e for e in m.get("extra", []) if e in df.columns]]
            if "matches" in df.columns:
                cols.append("matches")
            left, right = st.columns([2, 3])
            with left:
                fig = px.bar(
                    df, x=m["col"], y=who, orientation="h", title=f"Top {len(df)} — {m['name']}"
                )
                fig.update_layout(
                    yaxis={
                        "categoryorder": "total ascending" if m["higher"] else "total descending"
                    }
                )
                st.plotly_chart(fig, use_container_width=True)
            with right:
                st.dataframe(df[cols], use_container_width=True, hide_index=True)


if __name__ == "__main__":
    render()
