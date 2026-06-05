"""Shared Streamlit widgets — provenance banner + fuzzy name input +
collection picker.

Keeps the dashboard pages thin and lets every data-backed page use
the same UX for "did you mean?" confirmation, "data as of …"
provenance, and collection selection.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb
import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.profiles.identity import resolve_name


@st.cache_data(ttl=60)
def discover_collections() -> list[str]:
    """Return the list of collections we have data for — scans the
    cricsheet DuckDB for `balls_*` tables. Fallback to ['ipl'] when
    DuckDB isn't ingested yet so the picker still has a default."""
    db = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
    if not db.exists():
        return ["ipl"]
    try:
        con = duckdb.connect(str(db), read_only=True)
        try:
            rows = con.execute("SHOW TABLES").fetchall()
            cols = sorted(r[0].removeprefix("balls_") for r in rows if r[0].startswith("balls_"))
            return cols or ["ipl"]
        finally:
            con.close()
    except Exception:
        return ["ipl"]


def collection_picker(
    label: str = "Collection",
    default: str = "ipl",
    key: str | None = None,
) -> str:
    """Selectbox over the available collections — same source as
    `cricdex data ingest cricsheet -c <name>`."""
    options = discover_collections()
    index = options.index(default) if default in options else 0
    return st.selectbox(
        label,
        options=options,
        index=index,
        key=key,
        help=(
            "Pick a Cricsheet collection. New collections appear here once "
            "`cricdex data ingest cricsheet -c <name>` lands the duckdb table."
        ),
    )


def fuzzy_player_input(
    label: str = "Player",
    default: str = "V Kohli",
    collection: str = "ipl",
    key: str | None = None,
) -> str | None:
    """Free-text player input with a 'did you mean?' confirmation.

    Returns the resolved unique_name (string) once the user accepts a
    suggestion, or None while a decision is pending.
    """
    raw = st.text_input(label, default, key=key)
    if not raw.strip():
        return None

    exact, suggestions = resolve_name(raw, collection=collection)
    if exact:
        return exact

    if not suggestions:
        st.warning(f"No close match for '{raw}'. Check spelling, or try a different collection.")
        return None

    top = suggestions[0]
    st.warning(f"No exact match for **{raw}**. Closest: **{top.name}** ({top.score}%).")
    accept = st.button(f"Use {top.name}", key=f"{key}-accept" if key else None)
    if accept:
        return top.name

    with st.expander("Other suggestions"):
        for s in suggestions:
            st.markdown(f"- **{s.name}** ({s.score}%)")
    return None


_SOURCE_URLS = {
    "cricsheet": "https://cricsheet.org/",
    "people_register": "https://cricsheet.org/register/people.csv",
    "gemini": "https://ai.google.dev/gemini-api",
}


def provenance_banner(
    *,
    source: str = "cricsheet",
    path: Path | None = None,
    note: str | None = None,
) -> None:
    """Render the canonical 'data source / as-of / load latest' banner.

    `path` defaults to the cricsheet DuckDB; for derived JSONs pass the
    specific file so `mtime` reflects when *that* artifact last refreshed.
    """
    path = path or (DATA_DIR / "cricsheet" / "cricsheet.duckdb")
    url = _SOURCE_URLS.get(source, "")
    if not path.exists():
        st.warning(f"Data missing at `{path}`. Run `cricdex data ingest …` first.")
        return

    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M UTC")
    bits = [
        f"**Source:** [{source}]({url})" if url else f"**Source:** `{source}`",
        f"**Last refreshed:** {mtime}",
    ]
    if note:
        bits.append(note)
    st.caption(" · ".join(bits))
    if st.button("⟳ Load latest data", key=f"refresh-{source}"):
        st.info(
            "Trigger a refresh from the CLI: `cricdex data ingest "
            f"{source if source in ('cricsheet', 'rules') else 'metrics'} --force`"
            " — Streamlit will pick up the new files automatically."
        )
