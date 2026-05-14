"""Streamlit page: auto-generated match report viewer.

Pick a match from the matches table; either re-use the cached Markdown
under `data/reports/<collection>/<match_id>.md` or regenerate.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.dashboard._widgets import provenance_banner
from cricdex.reports import match_report

DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

st.set_page_config(page_title="CricDex Match Reports", page_icon="📰", layout="wide")
st.title("📰 CricDex — auto match reports")
st.caption(
    "LLM-written 350-500 word reports grounded in Cricsheet facts — no "
    "invented names or numbers, scores quoted verbatim. Needs a Gemini key "
    "for live generation; cached Markdown is reused when present."
)
provenance_banner(source="cricsheet", path=DUCKDB_PATH)


@st.cache_data
def list_matches(collection: str, limit: int = 200) -> list[tuple[str, str]]:
    safe = collection.replace("-", "_")
    if not DUCKDB_PATH.exists():
        return []
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if f"matches_{safe}" not in tables:
            return []
        rows = con.execute(
            f"""
            SELECT match_id, match_date, team_home, team_away, event_name
            FROM matches_{safe}
            ORDER BY match_date DESC NULLS LAST
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [
            (
                r[0],
                f"{r[1]}  {r[2] or '?'} vs {r[3] or '?'}  ({r[4] or '?'})",
            )
            for r in rows
        ]
    finally:
        con.close()


with st.sidebar:
    collection = st.text_input("Cricsheet collection", value="ipl")
    matches = list_matches(collection)
    if not matches:
        st.warning(f"no matches_{collection.replace('-', '_')} table — run the ingest first")
        st.stop()
    options = {f"{label} — {mid}": mid for mid, label in matches}
    pick = st.selectbox("Match", list(options.keys()))
    match_id = options[pick]
    regenerate = st.button("Regenerate report")

out_path = DATA_DIR / "reports" / collection / f"{match_id}.md"

if regenerate or not out_path.exists():
    with st.spinner("calling LLM …"):
        try:
            match_report.generate(match_id=match_id, collection=collection)
        except Exception as e:
            st.error(f"generation failed: {e}")
            st.stop()

if out_path.exists():
    st.markdown(out_path.read_text())
else:
    st.info("press Regenerate to render this match.")
Path(out_path).touch()  # keep on-disk artefact even if read empty
