"""Shared Streamlit widgets — provenance banner + fuzzy name input.

Keeps the dashboard pages thin and lets every data-backed page use
the same UX for "did you mean?" confirmation and "data as of …"
provenance.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.profiles.identity import resolve_name


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
    "rules_pdfs": "/repo/src/cricdex/rules/SOURCES.md",  # local link
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
