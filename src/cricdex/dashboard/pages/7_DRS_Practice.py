"""Streamlit page: DRS / umpire-decision practice game."""

from __future__ import annotations

import streamlit as st

from cricdex.drs import scenarios

st.set_page_config(page_title="CricDex DRS Practice", page_icon="⚖️", layout="wide")
st.title("⚖️ CricDex — DRS / umpire practice")
st.caption(
    "Decide each scenario yourself, then see whether the umpire would agree — "
    "with the MCC Law / ICC Playing-Condition citation. Scenarios are hand-"
    "curated; the citations dereference into the parsed rulebook corpus."
)
st.caption(
    "**Source:** [MCC Laws / ICC Playing Conditions](https://www.lords.org/mcc/the-laws-of-cricket) "
    "— hand-curated scenarios + matched clause citations."
)

pool = scenarios.load_scenarios()
if not pool:
    st.error("No scenarios loaded — check `data/drs/scenarios.jsonl`.")
    st.stop()

with st.sidebar:
    cats = ["All"] + scenarios.categories()
    chosen_cat = st.selectbox("Category", cats)
    diffs = ["Any"] + sorted({s["difficulty"] for s in pool})
    chosen_diff = st.selectbox("Difficulty", diffs)
    n = st.slider("Number of scenarios", 1, min(20, len(pool)), 5)
    if st.button("New round 🎲"):
        st.session_state.drs_seed = st.session_state.get("drs_seed", 0) + 1
        st.session_state.drs_answers = {}

seed = st.session_state.get("drs_seed", 0)
round_ = scenarios.pick(
    n=n,
    category=None if chosen_cat == "All" else chosen_cat,
    difficulty=None if chosen_diff == "Any" else chosen_diff,
    seed=seed,
)

if "drs_answers" not in st.session_state:
    st.session_state.drs_answers = {}

for s in round_:
    st.markdown(f"### `{s['category']}` — {s['id']}")
    st.markdown(f"**Difficulty:** {s['difficulty']}")
    st.markdown(s["description"])
    st.session_state.drs_answers[s["id"]] = st.radio(
        "Your decision:",
        s["options"],
        key=f"radio_{s['id']}_{seed}",
        index=None,
    )
    st.divider()

if st.button("Score round"):
    answered = {k: v for k, v in st.session_state.drs_answers.items() if v is not None}
    if not answered:
        st.warning("Pick at least one decision before scoring.")
    else:
        result = scenarios.score(answered)
        st.success(f"You scored **{result['correct']} / {result['total']}** ({result['pct']}%)")
        for r in result["rows"]:
            with st.expander(f"{'✅' if r['got_right'] else '❌'} `{r['id']}` — {r['category']}"):
                st.write(f"**Correct:** {r['correct_answer']}")
                st.write(f"**You answered:** {r['your_answer']}")
                st.write(r["explanation"])
                st.caption(f"Citation: {r['citation']}")
