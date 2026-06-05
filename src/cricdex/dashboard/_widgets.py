"""Shared Streamlit widgets — provenance banner + fuzzy name input +
collection picker.

Keeps the dashboard pages thin and lets every data-backed page use
the same UX for "did you mean?" confirmation, "data as of …"
provenance, and collection selection.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import duckdb
import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.web_parity.loader import SITE_DATA


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


@st.cache_data(ttl=300)
def load_players(collection: str) -> list[dict]:
    """The exported players.json for a collection (name, full_name, cricsheet_id, …)."""
    path = SITE_DATA / collection / "players.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        return []


def _player_label(p: dict) -> str:
    """'Full Name (Short)' — mirrors the web Combobox so typing either the full
    or the scorecard name filters the dropdown to the player."""
    full = p.get("full_name")
    short = p.get("name", "")
    return f"{full} ({short})" if full and full != short else short


def player_select(
    collection: str,
    label: str = "Player",
    *,
    key: str,
    default_name: str | None = "V Kohli",
) -> dict | None:
    """Type-ahead player dropdown (matches React's Combobox): the option label
    carries both the full and scorecard name, so typing either narrows the list.
    Returns the chosen player row (or None when there are no players)."""
    players = sorted(load_players(collection), key=lambda p: p.get("name", ""))
    if not players:
        return None
    by_cid = {p["cricsheet_id"]: p for p in players}
    labels = {p["cricsheet_id"]: _player_label(p) for p in players}
    cids = [p["cricsheet_id"] for p in players]
    index = next((i for i, p in enumerate(players) if p.get("name") == default_name), 0)
    cid = st.selectbox(label, cids, index=index, format_func=lambda c: labels[c], key=key)
    return by_cid.get(cid)


def player_multiselect(
    collection: str,
    label: str = "Players",
    *,
    key: str,
    max_selections: int = 4,
) -> list[dict]:
    """Type-ahead multi-player picker (same full+short label) for Compare."""
    players = sorted(load_players(collection), key=lambda p: p.get("name", ""))
    by_cid = {p["cricsheet_id"]: p for p in players}
    labels = {p["cricsheet_id"]: _player_label(p) for p in players}
    cids = st.multiselect(
        label,
        [p["cricsheet_id"] for p in players],
        format_func=lambda c: labels[c],
        max_selections=max_selections,
        key=key,
    )
    return [by_cid[c] for c in cids if c in by_cid]


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
