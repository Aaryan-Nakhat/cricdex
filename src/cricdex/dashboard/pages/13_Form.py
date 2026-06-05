"""Streamlit page: Form board — recent window vs career baseline.

Each metric recomputed over the recent window (last 1y, else last 3y) and
compared against the player's career value. Positive "form Δ" = improving form
(direction-corrected for 'lower is better' metrics). Reads the same exported
leaderboard JSON as the web app (`site/src/pages/Form.tsx`).
"""

from __future__ import annotations

import streamlit as st

from cricdex.common.filters import WINDOW_LABELS, load_leaderboard
from cricdex.common.metrics import METRICS
from cricdex.dashboard._widgets import provenance_banner
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Form", page_icon="📈", layout="wide")
st.title("📈 CricDex — form board")
st.caption(
    "Who's trending up and who's fading — each metric recomputed over the recent "
    "window and compared against the player's career baseline. Positive Δ means "
    "improving form (already direction-corrected for 'lower is better' metrics)."
)


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    cols = [d.name for d in SITE_DATA.iterdir() if d.is_dir() and (d / "leaderboards").is_dir()]
    return sorted(cols) or ["ipl"]


@st.cache_data(ttl=300)
def _load(collection: str, slug: str, window: str) -> list[dict]:
    try:
        return load_leaderboard(collection, slug, window)
    except FileNotFoundError:
        return []


collections = list_collections()
with st.sidebar:
    collection = st.selectbox(
        "Collection",
        collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="form-collection",
    )
    metric_name = st.selectbox("Metric", [m.name for m in METRICS], key="form-metric")
    top_n = st.slider("Top N each way", 5, 50, 20, step=5, key="form-topn")

metric = next(m for m in METRICS if m.name == metric_name)
provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

# Prefer last-1y as "recent form", fall back to last-3y.
recent_win = next((w for w in ("last1y", "last3y") if _load(collection, metric.slug, w)), None)
career = _load(collection, metric.slug, "all")

if recent_win is None or not career:
    st.info(
        f"No recent window for `{metric.slug}` in `{collection}` — form needs a "
        "recomputed last-1y/3y leaderboard."
    )
    st.stop()

recent = _load(collection, metric.slug, recent_win)
val = metric.sort_col
name_col = metric.name_col
career_by = {r[name_col]: r for r in career if r.get(name_col) is not None}

rows: list[dict] = []
for rr in recent:
    name = rr.get(name_col)
    cr = career_by.get(name)
    if cr is None or rr.get(val) is None or cr.get(val) is None:
        continue
    career_v = float(cr[val])
    recent_v = float(rr[val])
    raw = recent_v - career_v
    mv = raw if metric.higher_is_better else -raw  # +ve = improving
    rows.append(
        {
            "Player": name,
            "Career": round(career_v, 2),
            "Recent": round(recent_v, 2),
            "Form Δ": round(mv, 2),
        }
    )

if not rows:
    st.info(f"No players appear in both the career and {WINDOW_LABELS[recent_win]} boards.")
    st.stop()

rows.sort(key=lambda r: r["Form Δ"], reverse=True)
st.caption(
    f"**{metric.name}** — {WINDOW_LABELS[recent_win].lower()} vs career"
    + ("  ·  lower is better → sign-flipped" if not metric.higher_is_better else "")
)
with st.expander("How it's calculated"):
    st.write(metric.how)

c1, c2 = st.columns(2)
c1.metric("Biggest riser", str(rows[0]["Player"]), f"+{rows[0]['Form Δ']:.2f}")
c2.metric("Biggest faller", str(rows[-1]["Player"]), f"{rows[-1]['Form Δ']:.2f}")

left, right = st.columns(2)
with left:
    st.subheader("📈 Heating up")
    st.dataframe(rows[:top_n], hide_index=True, width="stretch")
with right:
    st.subheader("📉 Cooling down")
    st.dataframe(list(reversed(rows))[:top_n], hide_index=True, width="stretch")
