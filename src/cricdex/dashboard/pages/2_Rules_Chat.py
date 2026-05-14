"""Streamlit page: natural-language rule Q&A over the CricDex corpus.

Uses `cricdex.rules.qa.answer` end-to-end — same retrieval (dense + BM25
+ RRF) + same LLM-via-proxy citation discipline as the CLI.
"""

from __future__ import annotations

import streamlit as st

from cricdex.dashboard._widgets import provenance_banner
from cricdex.rules import qa, sources

st.set_page_config(page_title="CricDex Rules", page_icon="📋", layout="wide")
st.title("📋 CricDex — ask a cricket rule")
st.caption(
    "Answers are grounded in the parsed rulebook corpus (21 PDFs: MCC Laws, "
    "ICC Playing Conditions for every format, IPL, The Hundred, BBL, WBBL, "
    "SA20, Cricket Australia domestic, ICC Codes of Conduct, Anti-Corruption, "
    "plus curated supplementary clauses for the IPL Impact Player rule). "
    "When a rule isn't in the corpus, the answer says so plainly — no "
    "hallucinated rule text."
)
provenance_banner(source="rules_pdfs", path=None)

FORMAT_OPTIONS = sorted(qa.FORMAT_TO_SOURCE_IDS.keys())


def _render_citations(citations: list[tuple[str, str]]) -> None:
    """Render the cited-clauses list with human-readable labels + URLs."""
    if not citations:
        return
    with st.expander(f"{len(citations)} cited clauses"):
        for src_id, law in citations:
            st.markdown("- " + sources.render_citation(src_id, law))


with st.sidebar:
    st.subheader("Filter by format")
    selected_formats = st.multiselect(
        "Restrict retrieval to these formats (empty = search every parsed corpus)",
        options=FORMAT_OPTIONS,
        default=[],
        help=(
            "Each option maps to one or more parsed rulebook PDFs — e.g. `ipl` "
            "covers `ipl_pc_2026` + `ipl_impact_player_2025_27`. Leave empty to "
            "search every format at once."
        ),
    )
    top_k = st.slider(
        "Passages to retrieve",
        min_value=4,
        max_value=20,
        value=8,
        help="Higher = more passages fed to the LLM. 8 is the sweet spot.",
    )
    show_trace = st.toggle(
        "Show retrieval trace",
        value=False,
        help="Reveals the raw retrieved passages (debug / power-user).",
    )
    st.markdown("---")
    if st.button("Clear conversation"):
        st.session_state.pop("rule_messages", None)
        st.rerun()


if "rule_messages" not in st.session_state:
    st.session_state.rule_messages: list[dict] = []

for msg in st.session_state.rule_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            _render_citations(msg.get("citations") or [])

prompt = st.chat_input("ask any cricket rule …")
if prompt:
    st.session_state.rule_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("retrieving + citing …"):
            result = qa.answer(prompt, formats=selected_formats or None, top_k=top_k)
        st.markdown(result["answer"])
        _render_citations(result.get("citations") or [])
        if show_trace and result.get("passages"):
            with st.expander("Retrieval trace (raw passages)"):
                for p in result["passages"]:
                    st.markdown(
                        f"**{sources.label_for(p['source_id'])} §{p['law_number']}** "
                        f"— *{p.get('title', '')[:120]}*"
                    )
                    st.code(p.get("text", "")[:800])
        st.session_state.rule_messages.append(
            {
                "role": "assistant",
                "content": result["answer"],
                "citations": result["citations"],
            }
        )
