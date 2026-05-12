"""Streamlit page: natural-language rule Q&A over the CricDex corpus.

Uses `cricdex.rules.qa.answer` end-to-end — same retrieval (dense + BM25
+ RRF) + same LLM-via-proxy citation discipline as the CLI.
"""

from __future__ import annotations

import streamlit as st

from cricdex.rules import qa

st.set_page_config(page_title="CricDex Rules", page_icon="📋", layout="wide")
st.title("📋 CricDex — ask a cricket rule")
st.caption(
    "Answers are grounded in the rulebook corpus we've parsed "
    "(MCC Laws, ICC PCs, IPL, Hundred, BBL, WBBL, SA20, Cricket Australia "
    "domestic, ICC Codes of Conduct, Anti-Corruption + curated supplementary "
    "clauses). Every claim cites its source — no hallucinated rule text."
)

FORMAT_OPTIONS = sorted(qa.FORMAT_TO_SOURCE_IDS.keys())

with st.sidebar:
    st.subheader("Filter by format")
    selected_formats = st.multiselect(
        "Restrict retrieval to these formats (empty = search everything)",
        options=FORMAT_OPTIONS,
        default=[],
    )
    top_k = st.slider("Passages to retrieve", min_value=4, max_value=20, value=8)
    st.markdown("---")
    if st.button("Clear conversation"):
        st.session_state.pop("rule_messages", None)
        st.rerun()


if "rule_messages" not in st.session_state:
    st.session_state.rule_messages: list[dict] = []

for msg in st.session_state.rule_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("citations"):
            with st.expander(f"{len(msg['citations'])} cited clauses"):
                for cite in msg["citations"]:
                    st.markdown(f"- `[{cite[0]} §{cite[1]}]`")

prompt = st.chat_input("ask any cricket rule …")
if prompt:
    st.session_state.rule_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("retrieving + citing …"):
            result = qa.answer(prompt, formats=selected_formats or None, top_k=top_k)
        st.markdown(result["answer"])
        if result["citations"]:
            with st.expander(f"{len(result['citations'])} cited clauses"):
                for src_id, law in result["citations"]:
                    st.markdown(f"- `[{src_id} §{law}]`")
        st.session_state.rule_messages.append(
            {
                "role": "assistant",
                "content": result["answer"],
                "citations": result["citations"],
            }
        )
