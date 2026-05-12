"""Streamlit page: English-cricket-commentary → IN regional languages."""

from __future__ import annotations

import streamlit as st

from cricdex.commentary_translate import translate

st.set_page_config(page_title="CricDex Commentary Translate", page_icon="🌐", layout="wide")
st.title("🌐 CricDex — commentary translator")
st.caption(
    "English → Hindi / Tamil / Bengali / Urdu / Sinhala / Marathi / Telugu / "
    "Kannada. Voice-cloned audio is the deferred year-2 milestone."
)

with st.sidebar:
    target = st.selectbox(
        "Target language",
        options=list(translate.TARGETS.keys()),
        format_func=lambda k: f"{k} — {translate.TARGETS[k]}",
    )

default = (
    "Bumrah comes in from over the wicket. Fast yorker on middle stump, "
    "Kohli digs it out to mid-on. Just a single. CSK need 14 off 6."
)
text = st.text_area("English commentary", value=default, height=200)

if st.button("Translate"):
    if not text.strip():
        st.warning("type something to translate")
    else:
        with st.spinner("calling LLM …"):
            try:
                out = translate.translate(text, target=target)
                st.markdown("### Translated")
                st.write(out)
            except Exception as e:
                st.error(f"translation failed: {e}")
