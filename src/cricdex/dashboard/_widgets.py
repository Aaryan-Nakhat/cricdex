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
from typing import Any

import duckdb
import streamlit as st

from cricdex import leagues
from cricdex.common.display import league_label, player_label, stale_marker
from cricdex.config import DATA_DIR
from cricdex.web_parity.loader import SITE_DATA


def collections_in(table_names: list[str] | set[str]) -> list[str]:
    """The registry leagues that have a `balls_<key>` table, in registry order. Time-window copies
    (`balls_<key>_last1y` / `_last3y`) and tables of leagues not in config/leagues.toml are left out."""
    have = {t.removeprefix("balls_") for t in table_names if t.startswith("balls_")}
    return [k for k in leagues.keys() if k in have]


@st.cache_data(ttl=60)
def discover_collections() -> list[str]:
    """Return the collections we have data for — the registry leagues with a `balls_*` table in
    the cricsheet DuckDB. Falls back to the first exported league when DuckDB isn't ingested yet
    so the picker still has a default."""
    fallback = leagues.exported_keys()[:1]
    db = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
    if not db.exists():
        return fallback
    try:
        con = duckdb.connect(str(db), read_only=True)
        try:
            rows = con.execute("SHOW TABLES").fetchall()
            return collections_in({r[0] for r in rows}) or fallback
        finally:
            con.close()
    except Exception:
        return fallback


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
        format_func=league_label,
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


def read_json(path: Path, default: Any = None) -> Any:
    """Parse an exported JSON file. Missing → `default`; corrupt or unreadable →
    an `st.error` naming the file, then `default`, so one bad export can't crash
    the page."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        st.error(
            f"Could not read `{path.name}` ({e}). Re-run `uv run python scripts/export_site.py`."
        )
        return default


def _player_label(p: dict) -> str:
    """'Display Name (Short · aliases)' — mirrors the web Combobox so typing the display, full,
    scorecard name or any alias filters the dropdown to the player."""
    return player_label(p) or p.get("name", "")


_NO_PLAYER = "— no player —"


def player_select(
    collection: str,
    label: str = "Player",
    *,
    key: str,
    default_name: str | None = "V Kohli",
) -> dict | None:
    """Type-ahead player dropdown (matches React's Combobox): the option label
    carries both the full and scorecard name, so typing either narrows the list.

    `default_name=None` makes the pick optional: a "no player" entry comes
    first and is selected by default (the web's `cid=null`). Returns the chosen
    player row, or None when nothing is picked / there are no players."""
    players = sorted(load_players(collection), key=lambda p: _player_label(p).lower())
    if not players:
        return None
    by_cid = {p["cricsheet_id"]: p for p in players}
    labels = {p["cricsheet_id"]: _player_label(p) for p in players}
    cids: list[str | None] = [p["cricsheet_id"] for p in players]
    if default_name is None:
        cids.insert(0, None)
        index = 0
    else:
        index = next((i for i, p in enumerate(players) if p.get("name") == default_name), 0)
    cid = st.selectbox(
        label,
        cids,
        index=index,
        format_func=lambda c: _NO_PLAYER if c is None else labels[c],
        key=key,
    )
    return by_cid.get(cid) if cid is not None else None


def player_multiselect(
    collection: str,
    label: str = "Players",
    *,
    key: str,
    max_selections: int = 4,
) -> list[dict]:
    """Type-ahead multi-player picker (same full+short label) for Compare."""
    players = sorted(load_players(collection), key=lambda p: _player_label(p).lower())
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

    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    bits = [
        f"**Source:** [{source}]({url})" if url else f"**Source:** `{source}`",
        f"**Last refreshed:** {mtime}",
    ]
    if note:
        bits.append(note)
    st.caption(" · ".join(bits))
    # a league whose data stops early (SMAT, CSA T20 Challenge) says so wherever it's shown
    if path.parent.parent == SITE_DATA:
        mark = stale_marker(path.parent.name)
        if mark:
            st.warning(f"{leagues.label(path.parent.name)}: {mark}.")
    if st.button("⟳ Load latest data", key=f"refresh-{source}"):
        st.info(
            "Trigger a refresh from the CLI: `cricdex data ingest "
            f"{source if source in ('cricsheet', 'rules') else 'metrics'} --force`"
            " — Streamlit will pick up the new files automatically."
        )


def out_every(balls: object, outs: object) -> str:
    """A dismissal rate a fan can read: "out once every 26 balls" ("never out" with 0 outs)."""
    try:
        b, o = float(balls), float(outs)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    if o <= 0:
        return "never out"
    return f"out once every {round(b / o):,} balls"
