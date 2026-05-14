"""Streamlit page: English-cricket-commentary → IN regional languages."""

from __future__ import annotations

import streamlit as st

from cricdex.commentary_translate import translate

st.set_page_config(page_title="CricDex Commentary Translate", page_icon="🌐", layout="wide")
st.title("🌐 CricDex — commentary translator")
st.caption(
    "English → Hindi / Tamil / Bengali / Urdu / Sinhala / Marathi / Telugu / "
    "Kannada. Powered by Gemini — needs a Gemini key configured via "
    "`cricdex config set gemini_api_key …`. Voice-cloned audio is the "
    "deferred year-2 milestone."
)
from cricdex.config import settings  # noqa: E402

if not (settings.gemini_api_key or settings.gemini_tmp_url):
    st.warning(
        "No Gemini credential set. Run `cricdex config set gemini_api_key sk-…` "
        "(or `cricdex init`) and reload the page."
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
