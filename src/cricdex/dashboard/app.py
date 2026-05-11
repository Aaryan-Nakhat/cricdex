"""CricDex public leaderboard — Streamlit front end over the metrics JSON.

Run inside Docker:
    docker compose --profile dashboard up -d
or locally:
    uv run streamlit run src/cricdex/dashboard/app.py
"""

from __future__ import annotations

import json

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

from cricdex.config import DATA_DIR

METRIC_DIR = DATA_DIR / "metrics"
DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

METRICS: dict[str, dict] = {
    "Pressure Runs": {
        "slug": "pressure_runs",
        "sort_col": "pressure_runs",
        "bar_col": "pressure_runs",
        "extras": ["pressure_sr_per_100_balls", "pct_balls_under_pressure"],
        "description": (
            "Runs scored on balls where the required RPB exceeds 1.5× the venue+phase median. "
            "Chase-only (T20/ODI 2nd innings). Surfaces finishers under genuine pressure."
        ),
    },
    "Recoverability": {
        "slug": "recoverability",
        "sort_col": "runs_per_6_after_dot",
        "bar_col": "runs_per_6_after_dot",
        "extras": ["dots_faced", "following_balls"],
        "description": (
            "Runs scored in the next six balls after a dot. Mental-reset proxy — "
            "high = quick re-engagement; low = batter who lets dots compound."
        ),
    },
    "Counter-Attack": {
        "slug": "counter_attack",
        "sort_col": "counter_attack_sr",
        "bar_col": "counter_attack_sr",
        "extras": ["balls_after_partner_wkt", "runs_after_partner_wkt"],
        "description": (
            "Strike rate in the 12 balls immediately after a *partner* wicket "
            "(excludes the dismissed striker). Measures the surviving batter's response."
        ),
    },
    "Boundary Dependency": {
        "slug": "boundary_dependency",
        "sort_col": "bdr_pct",
        "bar_col": "bdr_pct",
        "extras": ["total_runs", "fours", "sixes"],
        "description": (
            "Percentage of total runs scored in fours and sixes. High = boundary-or-bust "
            "volatility; low = strike-rotator profile."
        ),
    },
    "Intent Curve": {
        "slug": "intent_curve",
        "sort_col": "sr",
        "bar_col": "sr",
        "extras": ["ball_bucket", "balls", "runs"],
        "description": (
            "Strike rate per ball-faced bucket (0-5, 6-10, 11-20, 21-30, 31-50, 51+). "
            "Shows whether a batter is a slow starter who heats up or an immediate aggressor."
        ),
    },
    "Sticky Dot Pressure": {
        "slug": "sticky_dot_pressure",
        "sort_col": "wicket_rate_pct",
        "bar_col": "wicket_rate_pct",
        "extras": ["pressure_balls", "wickets_after_pressure"],
        "description": (
            "Bowler's wicket rate on the next ball after building a 4+ consecutive "
            "dot-streak in the same over. Rewards turning pressure into a dismissal, "
            "not just bowling tight."
        ),
        "primary_key": "bowler",
    },
}


@st.cache_data
def discover_collections() -> list[str]:
    seen: set[str] = set()
    for fp in METRIC_DIR.glob("*.json"):
        for slug in (m["slug"] for m in METRICS.values()):
            prefix = f"{slug}_"
            if fp.name.startswith(prefix):
                seen.add(fp.name[len(prefix) : -len(".json")])
    return sorted(seen) or ["recently_played_30_male"]


@st.cache_data
def load_metric(metric_slug: str, collection: str) -> pd.DataFrame:
    path = METRIC_DIR / f"{metric_slug}_{collection}.json"
    if not path.exists():
        return pd.DataFrame()
    with open(path) as f:
        rows = json.load(f)
    return pd.DataFrame(rows)


@st.cache_data
def load_people_index() -> pd.DataFrame:
    if not DUCKDB_PATH.exists():
        return pd.DataFrame()
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "people" not in tables:
            return pd.DataFrame()
        return con.execute(
            """
            SELECT unique_name, identifier AS cricsheet_id,
                   key_cricinfo, key_cricbuzz
            FROM people
            """
        ).df()
    finally:
        con.close()


def _attach_ids(df: pd.DataFrame, key: str, people: pd.DataFrame) -> pd.DataFrame:
    if df.empty or people.empty:
        return df
    return df.merge(
        people.rename(columns={"unique_name": key}),
        on=key,
        how="left",
    )


def render() -> None:
    st.set_page_config(page_title="CricDex", page_icon="🏏", layout="wide")
    st.title("🏏 CricDex — novel cricket metrics")
    st.caption(
        "Open cricket intelligence. All metrics derived from Cricsheet ball-by-ball "
        "(no scraping required). Identity bridges via Cricsheet's People Register."
    )

    collections = discover_collections()
    with st.sidebar:
        collection = st.selectbox("Collection", collections, index=0)
        st.markdown("---")
        st.markdown(
            "Run `make docker-metrics-all COLLECTION=<name>` to regenerate the JSON "
            "feeds, then refresh this page."
        )

    tabs = st.tabs(list(METRICS.keys()))
    people = load_people_index()

    for tab, (metric_name, cfg) in zip(tabs, METRICS.items(), strict=True):
        with tab:
            st.subheader(metric_name)
            st.markdown(cfg["description"])
            df = load_metric(cfg["slug"], collection)
            if df.empty:
                st.warning(
                    f"No `{cfg['slug']}_{collection}.json` found. Run the metrics pipeline first."
                )
                continue

            primary_key = cfg.get("primary_key", "batter")
            df = _attach_ids(df, primary_key, people)
            df = df.sort_values(cfg["sort_col"], ascending=False)

            top_n = st.slider(
                f"Top N for {metric_name}", min_value=10, max_value=200, value=25, step=5
            )
            head = df.head(top_n)

            left, right = st.columns([2, 3])
            with left:
                fig = px.bar(
                    head,
                    x=cfg["bar_col"],
                    y=primary_key,
                    orientation="h",
                    title=f"Top {top_n} — {metric_name}",
                )
                fig.update_layout(yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig, use_container_width=True)
            with right:
                st.dataframe(head, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    render()
