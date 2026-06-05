"""CricDex Leaderboards — the same 10 metrics as the web app.

Reads the exported leaderboard JSON the React site uses
(`site/public/data/<collection>/leaderboards/<slug>[.<window>].json`) so the
rankings are identical to the live site. Mirrors the web Leaderboards page:
a time-window switcher (all-time / last 3 yrs / last 1 yr), the full player
filter bar (activity / role / bowling / position / country / min matches), an
inline magnitude bar on the headline column, the Intent-Curve sparkline, and
the per-metric "what / how" explainer. Each metric is one tab.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cricdex.common.filters import (
    ACTIVITY_OPTS,
    BOWLING_OPTS,
    FILTER_HELP,
    POSITION_OPTS,
    ROLE_OPTS,
    WINDOW_LABELS,
    WINDOWS,
    Filters,
    apply_filters,
    countries_in,
    load_leaderboard,
)
from cricdex.common.metrics import METRICS, MetricDef
from cricdex.dashboard._widgets import provenance_banner
from cricdex.web_parity.loader import SITE_DATA


@st.cache_data(ttl=300)
def discover_collections() -> list[str]:
    cols = [d.name for d in SITE_DATA.iterdir() if d.is_dir() and (d / "leaderboards").is_dir()]
    return sorted(cols) or ["ipl"]


@st.cache_data(ttl=300)
def load_metric(slug: str, collection: str, window: str) -> list[dict]:
    try:
        return load_leaderboard(collection, slug, window)
    except FileNotFoundError:
        return []


def _select(label: str, opts: list[tuple[str, str]], key: str, help_: str | None = None) -> str:
    """Selectbox over (value, label) option pairs → returns the value."""
    values = [v for v, _ in opts]
    labels = dict(opts)
    return st.selectbox(label, values, format_func=lambda v: labels[v], key=key, help=help_)


def _column_config(m: MetricDef, df: pd.DataFrame) -> dict:
    """st.column_config mirroring the web DataTable: inline magnitude bar on
    the primary column, a sparkline for the Intent-Curve, formatted numbers."""
    cfg: dict = {}
    for col in m.columns:
        if col.key not in df.columns:
            continue
        if col.key == "curve":
            cfg[col.key] = st.column_config.LineChartColumn(
                col.label, help="Strike rate across innings-depth buckets (0–5 → 51+)."
            )
        elif col.primary and pd.api.types.is_numeric_dtype(df[col.key]):
            series = pd.to_numeric(df[col.key], errors="coerce").dropna()
            lo = float(series.min()) if not series.empty else 0.0
            hi = float(series.max()) if not series.empty else 1.0
            if hi <= lo:  # all-equal / single row → give the bar a finite span
                hi = lo + 1.0
            cfg[col.key] = st.column_config.ProgressColumn(
                col.label,
                format=f"%.{col.digits}f" if col.digits is not None else "%d",
                min_value=lo,
                max_value=hi,
            )
        elif col.digits is not None:
            cfg[col.key] = st.column_config.NumberColumn(col.label, format=f"%.{col.digits}f")
        else:
            cfg[col.key] = st.column_config.TextColumn(col.label)
    return cfg


def render() -> None:
    st.set_page_config(page_title="CricDex Leaderboards", page_icon="🏏", layout="wide")
    st.title("🏏 CricDex — leaderboards")
    st.caption(
        "The 10 novel impact metrics — identical to the web app (reads the same exported "
        "data). Each isolates a skill that batting average / economy can't see. Pick a metric "
        "tab; set the time window and filters in the sidebar."
    )
    provenance_banner(source="cricsheet", path=SITE_DATA / "ipl" / "meta.json")

    collections = discover_collections()
    with st.sidebar:
        collection = st.selectbox(
            "Collection", collections, index=collections.index("ipl") if "ipl" in collections else 0
        )
        window = st.radio(
            "Time window",
            WINDOWS,
            format_func=lambda w: WINDOW_LABELS[w],
            horizontal=True,
            help="All-time, or metrics recomputed over the last 3 / 1 year(s).",
        )
        st.divider()
        min_matches = st.slider("Min matches", 0, 100, 20, step=5, help=FILTER_HELP["min_matches"])
        activity = _select("Activity", ACTIVITY_OPTS, "f_activity", FILTER_HELP["activity"])
        role = _select("Role", ROLE_OPTS, "f_role", FILTER_HELP["role"])
        bowling = _select("Bowling", BOWLING_OPTS, "f_bowling", FILTER_HELP["bowling"])
        position = _select("Batting position", POSITION_OPTS, "f_position", FILTER_HELP["position"])
        # Country options come from the all-time NGI board (widest roster).
        country_opts = countries_in(load_metric("ngi", collection, "all"))
        country = _select("Country", country_opts, "f_country", FILTER_HELP["country"])
        st.divider()
        top_n = st.slider("Top N", 10, 200, 25, step=5)
        if st.button("Reset filters"):
            for k in ("f_activity", "f_role", "f_bowling", "f_position", "f_country"):
                st.session_state.pop(k, None)
            st.rerun()

    filters = Filters(
        min_matches=min_matches,
        activity=activity,
        role=role,
        bowling=bowling,
        position=position,
        country=country,
    )

    tabs = st.tabs([m.name for m in METRICS])
    for tab, m in zip(tabs, METRICS, strict=True):
        with tab:
            head = st.columns([5, 1])
            head[0].subheader(m.name)
            if not m.higher_is_better:
                head[1].markdown(
                    "<span style='color:#a3e635;font-size:0.8rem'>▼ lower is better</span>",
                    unsafe_allow_html=True,
                )
            st.caption(m.what)
            with st.expander("How it's calculated"):
                st.write(m.how)

            rows = load_metric(m.slug, collection, window)
            if not rows or m.sort_col not in rows[0]:
                st.info(
                    f"No `{m.slug}` data for `{collection}` ({WINDOW_LABELS[window]}) — run "
                    f"`cricdex data ingest metrics -c {collection}` then re-export."
                )
                continue

            kept = apply_filters(rows, filters)
            kept.sort(
                key=lambda r: (r.get(m.sort_col) is None, r.get(m.sort_col) or 0),
                reverse=m.higher_is_better,
            )
            shown = kept[:top_n]
            st.caption(f"{len(shown)} shown · {len(kept)} after filters · {len(rows)} total")
            if not shown:
                st.info("No players match these filters — loosen them in the sidebar.")
                continue

            df = pd.DataFrame(shown)
            cols = [c.key for c in m.columns if c.key in df.columns]
            st.dataframe(
                df[cols],
                width="stretch",
                hide_index=True,
                column_config=_column_config(m, df),
            )


if __name__ == "__main__":
    render()
