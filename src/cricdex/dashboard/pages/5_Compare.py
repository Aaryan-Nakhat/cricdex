"""Streamlit page: side-by-side player comparator.

Reads the SAME pre-cooked JSON the React web app (`site/src/pages/Compare.tsx`)
fetches — `site/public/data/<collection>/players.json` for the picker and
`profiles/<cricsheet_id>.json` for each player's numbers — so the desktop
dashboard matches the live site instead of recomputing from DuckDB.
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cricdex.dashboard._widgets import player_multiselect, provenance_banner
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Compare", page_icon="🆚", layout="wide")
st.title("🆚 CricDex — compare players")
st.caption(
    "Put two to four players side by side across every number — Bayesian skill "
    "axes, career totals, and the novel metrics. Best value in each row is "
    "highlighted. Reads the exact same exported JSON the website does."
)


def _num(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        n = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if n == n else None  # drop NaN


def _g(profile: dict, *path: str) -> object:
    cur: object = profile
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _sr(profile: dict) -> float | None:
    r = _num(_g(profile, "career", "career_runs"))
    b = _num(_g(profile, "career", "career_balls_faced"))
    return (r / b * 100) if (r is not None and b) else None


# --- mirror Compare.tsx ROWS (group, label, getter, digits, better) ------
ROWS: list[tuple[str, str, object, int, str]] = [
    (
        "Bayesian skill",
        "Batting · scoring",
        lambda p: _num(_g(p, "bayes", "bayes_batter", "skill")),
        3,
        "high",
    ),
    (
        "Bayesian skill",
        "Batting · survival",
        lambda p: _num(_g(p, "bayes", "bayes_batter", "survival_skill")),
        3,
        "high",
    ),
    (
        "Bayesian skill",
        "Batting value",
        lambda p: _num(_g(p, "bayes", "bayes_batter", "value")),
        3,
        "high",
    ),
    (
        "Bayesian skill",
        "Bowling · economy",
        lambda p: _num(_g(p, "bayes", "bayes_bowler", "skill")),
        3,
        "high",
    ),
    (
        "Bayesian skill",
        "Bowling · strike",
        lambda p: _num(_g(p, "bayes", "bayes_bowler", "strike_skill")),
        3,
        "high",
    ),
    ("Career", "Runs", lambda p: _num(_g(p, "career", "career_runs")), 0, "high"),
    ("Career", "Balls faced", lambda p: _num(_g(p, "career", "career_balls_faced")), 0, "high"),
    ("Career", "Strike rate", _sr, 1, "high"),
    ("Career", "Wickets", lambda p: _num(_g(p, "career", "career_wickets")), 0, "high"),
    (
        "Metrics",
        "Pressure SR",
        lambda p: _num(_g(p, "metrics", "pressure_runs", "pressure_sr_per_100_balls")),
        1,
        "high",
    ),
    (
        "Metrics",
        "Counter-attack SR",
        lambda p: _num(_g(p, "metrics", "counter_attack", "counter_attack_sr")),
        1,
        "high",
    ),
    (
        "Metrics",
        "Boundary %",
        lambda p: _num(_g(p, "metrics", "boundary_dependency", "bdr_pct")),
        1,
        "low",
    ),
    (
        "Metrics",
        "Dot recovery",
        lambda p: _num(_g(p, "metrics", "dot_ball_recovery", "runs_per_6_after_dot")),
        2,
        "high",
    ),
]
GROUPS = ["Bayesian skill", "Career", "Metrics"]


def _has_players(collection: str) -> bool:
    return (SITE_DATA / collection / "players.json").exists() and (
        SITE_DATA / collection / "profiles"
    ).is_dir()


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    cols_file = SITE_DATA / "collections.json"
    names: list[str] = []
    if cols_file.exists():
        try:
            names = [c["collection"] for c in json.loads(cols_file.read_text())]
        except Exception:
            names = []
    if not names:
        names = sorted(p.name for p in SITE_DATA.iterdir() if p.is_dir())
    return [c for c in names if _has_players(c)]


@st.cache_data(ttl=300)
def load_profile(collection: str, cid: str) -> dict | None:
    path = SITE_DATA / collection / "profiles" / f"{cid}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _fmt(v: float | None, digits: int) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.{digits}f}"


collections = list_collections()
if not collections:
    st.warning(
        "No exported players.json / profiles found under site/public/data/. "
        "Run `uv run python scripts/export_site.py` first."
    )
    st.stop()

with st.sidebar:
    collection = st.selectbox(
        "Collection",
        options=collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="compare-collection",
        help="Only collections with exported players.json + profiles are listed.",
    )

provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

picked = player_multiselect(
    collection, "Players (pick 2–4)", key="compare-players", max_selections=4
)

if len(picked) < 2:
    st.info("Pick at least two players to compare.")
    st.stop()

profiles: list[tuple[str, dict]] = []
for p in picked:
    prof = load_profile(collection, p["cricsheet_id"])
    if prof:
        profiles.append((p["name"], prof))

if len(profiles) < 2:
    st.error("Could not load at least two profiles from the exported data.")
    st.stop()

# --- radar over the 4 bayes axes, min-max normalised across the set ------
st.subheader("Skill shape")
st.caption(
    "Four Bayesian axes — Score & Survive (batting), Economy & Strike "
    "(bowling) — scaled 0–100 across the selected players (relative, not "
    "absolute). The best of the picked players is pushed to the rim, the worst "
    "to the centre."
)
RADAR_AXES = [
    ("Score", lambda p: _num(_g(p, "bayes", "bayes_batter", "skill"))),
    ("Survive", lambda p: _num(_g(p, "bayes", "bayes_batter", "survival_skill"))),
    ("Economy", lambda p: _num(_g(p, "bayes", "bayes_bowler", "skill"))),
    ("Strike", lambda p: _num(_g(p, "bayes", "bayes_bowler", "strike_skill"))),
]
axis_labels = [a for a, _ in RADAR_AXES]
fig = go.Figure()
# precompute per-axis min/max across players (clamped like Compare.tsx)
scaled: dict[str, list[float]] = {nm: [] for nm, _ in profiles}
for _, getter in RADAR_AXES:
    vals = [getter(p) for _, p in profiles]
    finite = [v for v in vals if v is not None]
    lo = min(finite + [0.0]) if finite else 0.0
    hi = max(finite + [0.01]) if finite else 0.01
    rng = (hi - lo) or 1
    for (nm, _p), v in zip(profiles, vals, strict=True):
        scaled[nm].append(0.0 if v is None else (v - lo) / rng * 100)
for nm, _p in profiles:
    r = scaled[nm]
    fig.add_trace(
        go.Scatterpolar(
            r=r + [r[0]],
            theta=axis_labels + [axis_labels[0]],
            fill="toself",
            name=nm,
        )
    )
fig.update_layout(
    polar={"radialaxis": {"visible": True, "range": [0, 100]}},
    showlegend=True,
    height=480,
)
st.plotly_chart(fig, width="stretch")

# --- side-by-side comparison table (grouped, best highlighted) -----------
st.subheader("Side by side")
st.caption("Best value in each row is highlighted (greener cell wins each row).")

records: list[dict] = []
best_mask: list[list[bool]] = []
player_names = [nm for nm, _ in profiles]
for group in GROUPS:
    for g, label, getter, digits, better in ROWS:
        if g != group:
            continue
        vals = [getter(p) for _, p in profiles]
        finite = [v for v in vals if v is not None]
        best = (max(finite) if better == "high" else min(finite)) if finite else None
        records.append(
            {
                "Group": group,
                "Metric": label,
                **{nm: _fmt(v, digits) for nm, v in zip(player_names, vals, strict=True)},
            }
        )
        best_mask.append([v is not None and best is not None and v == best for v in vals])

table = pd.DataFrame(records)


def _highlight(row: pd.Series) -> list[str]:
    i = row.name
    styles = ["", ""]  # Group, Metric columns
    for is_best in best_mask[i]:
        styles.append("color:#34d399;font-weight:700" if is_best else "")
    return styles


st.dataframe(
    table.style.apply(_highlight, axis=1),
    width="stretch",
    hide_index=True,
)
