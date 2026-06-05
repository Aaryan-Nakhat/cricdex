"""Streamlit page: cricket record books.

Reads the SAME pre-cooked JSON the React web app (`site/src/pages/Records.tsx`)
fetches — `site/public/data/<collection>/records.json` — so the desktop
dashboard matches the live site instead of recomputing from DuckDB.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from cricdex.dashboard._widgets import provenance_banner
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Records", page_icon="📜", layout="wide")
st.title("📜 CricDex — record books")
st.caption(
    "The all-time tables for this collection — biggest innings, fastest "
    "milestones, career leaders, and team feats — straight from the "
    "ball-by-ball record. Reads the exact same exported JSON the website does."
)

# --- mirror Records.tsx LABELS / COL_LABELS -----------------------------
RECORD_LABELS: dict[str, str] = {
    "highest_individual_innings": "Highest individual innings",
    "fastest_fifty": "Fastest fifties",
    "fastest_hundred": "Fastest hundreds",
    "most_sixes_innings": "Most sixes in an innings",
    "career_run_leaders": "Career run leaders",
    "best_bowling_innings": "Best bowling figures",
    "career_wicket_leaders": "Career wicket leaders",
    "highest_team_totals": "Highest team totals",
    "highest_runs_in_over": "Most runs in an over",
}

COL_LABELS: dict[str, str] = {
    "batter": "Batter",
    "bowler": "Bowler",
    "team": "Team",
    "batting_team": "Team",
    "match_date": "Date",
    "venue": "Venue",
    "runs": "Runs",
    "balls": "Balls",
    "fours": "4s",
    "sixes": "6s",
    "wickets": "Wkts",
    "runs_conceded": "Runs",
    "match_id": "Match",
    "total": "Total",
    "total_runs": "Total",
    "over_runs": "Runs",
}


def _has_records(collection: str) -> bool:
    return (SITE_DATA / collection / "records.json").exists()


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    """Collections whose dir has a records.json (mirror the React picker)."""
    cols_file = SITE_DATA / "collections.json"
    names: list[str] = []
    if cols_file.exists():
        try:
            names = [c["collection"] for c in json.loads(cols_file.read_text())]
        except Exception:
            names = []
    if not names:
        names = sorted(p.name for p in SITE_DATA.iterdir() if p.is_dir())
    return [c for c in names if _has_records(c)]


@st.cache_data(ttl=300)
def load_records(collection: str) -> dict[str, list[dict]]:
    path = SITE_DATA / collection / "records.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


collections = list_collections()
if not collections:
    st.warning(
        "No exported `records.json` found under site/public/data/. "
        "Run `uv run python scripts/export_site.py` first."
    )
    st.stop()

with st.sidebar:
    collection = st.selectbox(
        "Collection",
        options=collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="records-collection",
        help="Only collections with an exported records.json are listed.",
    )

provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

data = load_records(collection)
# only keep non-empty record boards (mirror Records.tsx `keys`)
keys = [k for k in RECORD_LABELS if data.get(k)]
# include any extra keys present in the JSON but not in our label map
keys += [k for k in data if k not in RECORD_LABELS and data.get(k)]

if not keys:
    st.info(f"No records available for {collection}.")
    st.stop()

tabs = st.tabs([RECORD_LABELS.get(k, k.replace("_", " ").title()) for k in keys])
for tab, key in zip(tabs, keys, strict=True):
    with tab:
        rows = data.get(key) or []
        if not rows:
            st.info("No rows for this record board.")
            continue
        df = pd.DataFrame(rows)
        # Records.tsx drops the match_id column from the displayed table.
        if "match_id" in df.columns:
            df = df.drop(columns=["match_id"])

        # optional year-range filter on dated records (mirror Records.tsx)
        if "match_date" in df.columns:
            years = pd.to_datetime(df["match_date"], errors="coerce").dt.year.dropna()
            if not years.empty:
                lo, hi = int(years.min()), int(years.max())
                if lo < hi:
                    frm, to = st.slider(
                        "Year range",
                        min_value=lo,
                        max_value=hi,
                        value=(lo, hi),
                        key=f"records-years-{key}",
                        help=(
                            "Limits this table to feats between the two years. "
                            "Career-leader tables have no single date, so they "
                            "are unaffected."
                        ),
                    )
                    yr = pd.to_datetime(df["match_date"], errors="coerce").dt.year
                    df = df[(yr.isna()) | ((yr >= frm) & (yr <= to))]
                    st.caption(f"**{len(df)}** of {len(rows)} rows")

        df = df.rename(columns={c: COL_LABELS.get(c, c.replace("_", " ")) for c in df.columns})
        df.insert(0, "#", range(1, len(df) + 1))
        st.dataframe(df, width="stretch", hide_index=True)
