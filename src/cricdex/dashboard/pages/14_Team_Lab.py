"""Streamlit page: Team Lab — optimal XI, squad balance & replacement-by-need.

Runs the SAME parity-locked engines as the web app (`cricdex.web_parity`:
best_xi / analyze_squad / replacement_by_need) on the SAME exported JSON, so the
results match `site/src/pages/TeamLab.tsx` bit-for-bit.
"""

from __future__ import annotations

import streamlit as st

from cricdex.common.filters import load_leaderboard
from cricdex.dashboard._widgets import load_players, provenance_banner
from cricdex.web_parity import (
    analyze_squad,
    best_xi,
    est_value,
    load_auction_pool,
    load_scout_index,
    replacement_by_need,
)
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Team Lab", page_icon="⚗️", layout="wide")
st.title("⚗️ CricDex — Team Lab")
st.caption(
    "Build the optimal playing XI under a budget and overseas cap (exact knapsack "
    "on Net Game Impact), check the squad's balance, and find cheaper same-mould "
    "replacements. Same engines + data as the web app."
)

ROLE_KEYS = ["batter", "bowler", "all_rounder", "keeper"]
ROLE_LABEL = {
    "batter": "Batters",
    "bowler": "Bowlers",
    "all_rounder": "All-rounders",
    "keeper": "Keepers",
}
REPL_TIERS = ["smat", "bbl", "sa20", "cpl", "blast"]


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    cols = [
        d.name for d in SITE_DATA.iterdir() if d.is_dir() and (d / "auction_pool.json").exists()
    ]
    return sorted(cols) or ["ipl"]


@st.cache_data(ttl=600)
def xi_pool(collection: str) -> list[dict]:
    """Auction pool priced at IPL tier, NGI joined from the leaderboard."""
    try:
        pool = load_auction_pool(collection)
    except FileNotFoundError:
        return []
    try:
        ngi = {
            r["cricsheet_id"]: r["ngi_total"] for r in load_leaderboard(collection, "ngi", "all")
        }
    except FileNotFoundError:
        return []
    out = []
    for r in pool:
        if r["cricsheet_id"] not in ngi:
            continue
        out.append(
            {
                "cricsheet_id": r["cricsheet_id"],
                "name": r["name"],
                "role": r["role"],
                "is_overseas": r["is_overseas"],
                "ngi": ngi[r["cricsheet_id"]],
                "price": est_value(r["value"], r["role"], "ipl"),
            }
        )
    return out


@st.cache_data(ttl=600)
def pos_by_cid(collection: str) -> dict[str, str | None]:
    return {p["cricsheet_id"]: p.get("batting_position") for p in load_players(collection)}


collections = list_collections()
with st.sidebar:
    collection = st.selectbox(
        "Collection",
        collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="teamlab-collection",
    )
    st.divider()
    st.markdown("**Optimal XI constraints**")
    budget = st.slider("Budget (cr)", 20, 200, 100, step=5, key="tl-budget")
    overseas_cap = st.slider("Overseas cap", 0, 11, 4, key="tl-overseas")
    role_mins = {
        rk: st.number_input(f"Min {ROLE_LABEL[rk].lower()}", 0, 11, dflt, key=f"tl-min-{rk}")
        for rk, dflt in zip(ROLE_KEYS, (3, 3, 1, 1), strict=True)
    }

provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

players = xi_pool(collection)
if not players:
    st.warning(
        "No auction pool / NGI leaderboard exported for this collection. "
        "Run `uv run python scripts/export_site.py` first."
    )
    st.stop()

# ============================ Optimal XI ===================================
st.header("🏏 Optimal XI builder")
st.caption("Maximise total NGI subject to budget, overseas cap and per-role minimums.")
xi = best_xi(players, float(budget), int(overseas_cap), role_mins, 11, 40)

if not xi["feasible"]:
    st.error(
        "No valid XI under these constraints — raise the budget/overseas cap or lower the "
        "role minimums (they must sum to ≤ 11)."
    )
else:
    m = st.columns(4)
    m[0].metric("Total NGI", f"{xi['total_ngi']:.2f}")
    m[1].metric("Total spend", f"{xi['total_price']:.1f} cr", help=f"of {budget} cr")
    m[2].metric("Overseas", f"{xi['overseas']} / {overseas_cap}")
    m[3].metric("Players", str(len(xi["players"])))
    st.dataframe(
        [
            {
                "Player": p["name"],
                "Role": ROLE_LABEL.get(p["role"], p["role"]),
                "O/S": "✈︎" if p["is_overseas"] else "",
                "NGI": round(p["ngi"], 2),
                "Price (cr)": round(p["price"], 1),
            }
            for p in xi["players"]
        ],
        hide_index=True,
        width="stretch",
    )

    # ========================= Squad balance ===============================
    st.header("🧩 Squad balance")
    pos = pos_by_cid(collection)
    squad = analyze_squad(
        [
            {
                "role": p["role"],
                "is_overseas": p["is_overseas"],
                "batting_position": pos.get(p["cricsheet_id"]),
            }
            for p in xi["players"]
        ],
        role_mins,
        int(overseas_cap),
    )
    if squad["balanced"]:
        st.success("Balanced — meets every role minimum, the overseas cap and slot coverage.")
    else:
        st.warning(f"{len(squad['gaps'])} gap(s): " + "; ".join(squad["gaps"]))
    b = st.columns(5)
    for col, rk in zip(b, ROLE_KEYS, strict=False):
        col.metric(ROLE_LABEL[rk], squad["roles"].get(rk, 0))
    b[4].metric("Overseas", f"{squad['overseas']}/{squad['overseas_cap']}")
    if squad["slots"]:
        st.caption("Batting slots: " + " · ".join(f"{k}: {v}" for k, v in squad["slots"].items()))

# ====================== Replacement by need ================================
st.header("🔁 Replacement by need")
st.caption("Cheaper players of the same mould (role / seam-spin / slot) — the budget-swap case.")
try:
    idx = load_scout_index(collection)
except FileNotFoundError:
    st.info("No scout index for this collection — replacement needs scout_index.json.")
    st.stop()

ipl = sorted(idx["ipl"], key=lambda p: p["name"])
by_cid = {p["cricsheet_id"]: p for p in ipl}
repl_cid = st.selectbox(
    "Player to replace",
    list(by_cid),
    format_func=lambda c: by_cid[c]["name"],
    key="tl-repl",
)
sel = by_cid[repl_cid]
sel_price = est_value(sel["value"], sel["role"], "ipl")
st.markdown(f"Replacing **{sel['name']}** (≈ {sel_price:.1f} cr) — cheaper same-mould options:")

merged: list[dict] = []
for tier in REPL_TIERS:
    for r in replacement_by_need(sel, idx[tier], tier):
        merged.append(
            {
                "Player": r["name"],
                "League": tier.upper(),
                "Country": r.get("country") or "—",
                "Sim %": round(r["sim"] * 100),
                "Est cr": r["est_cr"],
                "Save cr": r["saving"] if r["saving"] > 0 else None,
            }
        )
merged.sort(key=lambda r: (-(r["Save cr"] or 0), -r["Sim %"]))
if merged:
    st.dataframe(merged[:12], hide_index=True, width="stretch")
else:
    st.info("No cheaper same-mould option found across the scouted leagues.")
