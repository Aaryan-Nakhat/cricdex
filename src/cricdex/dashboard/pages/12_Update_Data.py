"""Streamlit page: refresh local data without dropping to the shell.

Each button calls `cricdex.cli.data_cmd.run_ingest(slice, collection,
force)` — the same code path the CLI uses — so behaviour stays in
lockstep across the terminal + browser surfaces.

Order if running individually: cricsheet → ratings → metrics → graph.
Rules + wikidata are independent. The All-chained button runs every
slice in dependency order.
"""

from __future__ import annotations

import time

import streamlit as st

from cricdex.cli.data_cmd import SLICES, run_ingest

st.set_page_config(page_title="CricDex — Update Data", page_icon="🔄", layout="wide")
st.title("🔄 CricDex — refresh local data")
st.caption(
    "Same code paths as `cricdex data ingest <slice>`. Each slice "
    "skips if its output already exists, unless **Force** is checked. "
    "Slices write to `~/.cricdex/data/` and both surfaces (terminal "
    "+ browser) pick up the new files on the next read."
)

col_left, col_right = st.columns([1, 2])
with col_left:
    collection = st.text_input("Collection", value="ipl")
    force = st.checkbox(
        "Force refresh",
        value=False,
        help="Re-download / re-emit even if the output already exists.",
    )
    st.markdown(
        "**Dependency order**\n"
        "1. `cricsheet` (ball-by-ball)\n"
        "2. `ratings` (NumPyro Bayes fit)\n"
        "3. `metrics` (10 novel metrics)\n"
        "4. `graph` (Neo4j FACED/TEAMMATE)\n\n"
        "Independent:\n"
        "- `rules` (21 PDFs → Qdrant)\n"
        "- `wikidata` (Q-id bridge + cache)"
    )

with col_right:
    st.subheader("Run a slice")
    btn_cols = st.columns(3)
    pending_slice: str | None = None
    for i, slice_ in enumerate(SLICES):
        if btn_cols[i % 3].button(
            slice_.title(),
            key=f"btn-{slice_}",
            use_container_width=True,
        ):
            pending_slice = slice_

    if st.button(
        "All slices (chained, in dependency order)",
        type="primary",
        use_container_width=True,
    ):
        pending_slice = "__all__"

if pending_slice == "__all__":
    chained = ("cricsheet", "ratings", "metrics", "graph", "rules", "wikidata")
    st.info(f"chained refresh starting — {' → '.join(chained)}")
    log_area = st.empty()
    lines: list[str] = []
    for s in chained:
        lines.append(f"▶ ingest **{s}** (collection={collection}, force={force})")
        log_area.markdown("\n\n".join(lines))
        try:
            t0 = time.time()
            msg = run_ingest(s, collection=collection, force=force)
            dt = time.time() - t0
            lines.append(f"✅ `{s}` ({dt:.1f}s)  —  {msg}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"❌ `{s}` failed: `{e}`")
        log_area.markdown("\n\n".join(lines))
    st.success("All slices complete.")
elif pending_slice:
    placeholder = st.empty()
    placeholder.info(f"▶ ingest **{pending_slice}** (collection={collection}, force={force})")
    try:
        t0 = time.time()
        msg = run_ingest(pending_slice, collection=collection, force=force)
        dt = time.time() - t0
        placeholder.success(f"✅ `{pending_slice}` ({dt:.1f}s) — {msg}")
    except Exception as e:  # noqa: BLE001
        placeholder.error(f"❌ `{pending_slice}` failed: `{e}`")

st.caption(
    "Heads-up: `cricsheet` downloads can be hundreds of MB; "
    "`rules` will re-embed the 11k+ clause corpus on force; "
    "`ratings` runs the NumPyro/JAX fit (~30–60 s on CPU)."
)
