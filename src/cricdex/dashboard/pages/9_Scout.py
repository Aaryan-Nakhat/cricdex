"""Streamlit page: Scout — cross-competition look-alikes over six pools.

Identical to the web Scout room (and locked to it by
`test_scripts/test_web_parity.py`): it reads the SAME exported JSON
(`site/public/data/ipl/scout_index.json`) and uses the SAME logic
(`cricdex.web_parity`). Pick an active IPL player → similar IPL peers,
uncapped SMAT prospects, and overseas BBL / SA20 / CPL / T20 Blast options, ranked by within-tier
skill standing — with est. crore price, saving-vs-pick, an uncapped-gem
flag, role/slot filters, and a draft-to-auction handoff.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cricdex.dashboard._widgets import load_players, provenance_banner
from cricdex.web_parity import est_value, gem_threshold, is_gem, load_scout_index, similar_to
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Scout", page_icon="🔭", layout="wide")
st.title("🔭 CricDex — Scout")
st.caption(
    "Pick an active IPL player and find others of the same mould at three levels — "
    "IPL peers, uncapped Indian prospects (SMAT), overseas options (BBL) — with an "
    "estimated price, the saving vs your pick, and a draft into the Auction room. "
    "Same data + logic as the web app."
)
provenance_banner(source="cricsheet", path=SITE_DATA / "ipl" / "scout_index.json")

with st.expander("How the scout works (plain English)"):
    st.markdown(
        "Pick an active IPL player. We find players of the **same archetype** (same role; for "
        "bowlers, same seam/spin type) at three levels and rank them by how close their **skill "
        "standing** is to your pick:\n\n"
        "- **IPL peers** — who else in the IPL is most like them.\n"
        "- **Uncapped (SMAT)** — domestic Indian prospects of the same mould — the 'next one'.\n"
        "- **Overseas** — Big Bash (BBL), SA20, CPL & T20 Blast players of the same mould.\n\n"
        "'Skill standing' is the player's Bayesian value *for his role* (batting for batters and "
        "keepers, bowling for bowlers, both for all-rounders) as a z-score among the listed players "
        "of that role *in his own competition* (mean 0, sd 1), so a SMAT star and an IPL star line up even though raw numbers aren't "
        "comparable. Similarity = how close those standings are. Each row shows an **estimated "
        "crore price** (the same skill→price curve the Auction room uses, discounted for the weaker "
        "tier) and, for SMAT/BBL, the **saving** vs your IPL pick. A 💎 **gem** flags an uncapped "
        "prospect with unusually high standing for how little he's played. Hit **Draft** to drop a "
        "prospect straight into the Auction room as a retention."
    )

ROLE_OPTS = ["batter", "all_rounder", "keeper", "bowler"]
POS = {
    "": "Any",
    "opener": "Opener",
    "no3": "No. 3",
    "middle": "Middle",
    "finisher": "Finisher",
    "lower": "Lower",
    "tailender": "Tailender",
}
TIER_TITLE = {
    "ipl": "IPL peers",
    "smat": "Uncapped · SMAT",
    "bbl": "Overseas · BBL",
    "sa20": "Overseas · SA20",
    "cpl": "Overseas · CPL",
    "blast": "Overseas · T20 Blast",
}
TIER_ORDER = ["ipl", "smat", "bbl", "sa20", "cpl", "blast"]
DRAFTABLE_TIERS = ["smat", "bbl", "sa20", "cpl", "blast"]


@st.cache_data(ttl=600, show_spinner=False)
def _index() -> dict:
    return load_scout_index("ipl")


@st.cache_data(ttl=600, show_spinner=False)
def _auction_pool_cids() -> set[str]:
    """Cids in the priced auction pool — only these can be drafted."""
    try:
        from cricdex.web_parity import load_auction_pool

        return {p["cricsheet_id"] for p in load_auction_pool("ipl")}
    except Exception:  # noqa: BLE001
        return set()


try:
    idx = _index()
except (FileNotFoundError, ValueError) as e:  # missing or corrupt export
    st.error(f"{e}")
    st.stop()

ipl = sorted(idx["ipl"], key=lambda p: p["name"])
by_cid = {p["cricsheet_id"]: p for p in ipl}
gem_med = gem_threshold(idx["smat"])

# Type-ahead label carries full + scorecard name (full_name joined from
# players.json by cricsheet_id), so typing either filters the dropdown.
_full = {p["cricsheet_id"]: p.get("full_name") for p in load_players("ipl")}


def _scout_label(p: dict) -> str:
    full = _full.get(p["cricsheet_id"])
    return f"{full} ({p['name']})" if full and full != p["name"] else p["name"]


_labels = {p["cricsheet_id"]: _scout_label(p) for p in ipl}

# --- "The next X": pick-independent headline of standout uncapped gems ----
gems = sorted((p for p in idx["smat"] if is_gem(p, gem_med)), key=lambda p: p["z"], reverse=True)[
    :12
]
if gems:
    with st.expander("💎 The next big things — top uncapped SMAT gems", expanded=True):
        st.caption(
            "Uncapped prospects punching above their sample — high standing on below-median "
            "exposure (moneyball). Pick-independent."
        )
        st.dataframe(
            [
                {
                    "Player": g["name"],
                    "Country": g.get("country") or "—",
                    "Standing": round(g["z"], 2),
                    "Balls": g.get("balls", 0),
                    "Est cr": round(est_value(g["value"], g["role"], "smat"), 1),
                }
                for g in gems
            ],
            hide_index=True,
            width="stretch",
        )

pick_cid = st.selectbox(
    "Active IPL player",
    list(by_cid),
    index=0,
    format_func=lambda c: _labels[c],
    key="scout-pick",
)
sel = by_cid[pick_cid]

c1, c2 = st.columns(2)
role = c1.selectbox(
    "Match role", ROLE_OPTS, index=ROLE_OPTS.index(sel["role"]) if sel["role"] in ROLE_OPTS else 0
)
pos_label = c2.selectbox("Batting slot", list(POS.values()), index=0, disabled=role == "bowler")
pos = "" if role == "bowler" else next(k for k, v in POS.items() if v == pos_label)

sel_price = est_value(sel["value"], sel["role"], "ipl")
st.markdown(
    f"**{sel['name']}** · {sel['role'].replace('_', '-')} · standing {sel['z']:.2f} · "
    f"≈ **{sel_price:.1f} cr**"
)


def _tier_df(tier: str) -> pd.DataFrame:
    out = []
    for r in similar_to(sel, idx[tier], role, pos):
        price = est_value(r["value"], r["role"], tier)
        saving = sel_price - price if price < sel_price else 0.0
        out.append(
            {
                "Player": r["name"],
                "Country": r.get("country") or "—",
                "Last": (r.get("last_match_date") or "")[:4],
                "Est cr": round(price, 1),
                "Save cr": round(saving, 1) if saving > 0 else None,
                "Sim %": round(r["sim"] * 100),
                "💎": "💎" if (tier == "smat" and is_gem(r, gem_med)) else "",
            }
        )
    return pd.DataFrame(out)


# 6 pools laid out in rows of up to 3 columns.
for start in range(0, len(TIER_ORDER), 3):
    chunk = TIER_ORDER[start : start + 3]
    cols = st.columns(len(chunk))
    for col, tier in zip(cols, chunk, strict=True):
        with col:
            st.subheader(TIER_TITLE[tier])
            df = _tier_df(tier)
            if df.empty:
                st.info("No close match of this archetype.")
            else:
                st.dataframe(df, hide_index=True, width="stretch")

# --- draft handoff: same effect as the web's ?draft= -----------------------
st.divider()
# Options are keyed by cricsheet_id (two prospects can share a name).
prospects: dict[str, str] = {}
for tier in DRAFTABLE_TIERS:
    for r in similar_to(sel, idx[tier], role, pos):
        prospects.setdefault(r["cricsheet_id"], f"{r['name']} ({tier.upper()})")
# The draft list accumulates across picks: this pick's multiselect only adds or
# removes its own prospects; drafts made from earlier picks are kept.
drafted_before: list[str] = list(st.session_state.get("drafted", []))
chosen = st.multiselect(
    "Draft prospects into the Auction room (locked as retentions there)",
    list(prospects),
    default=[c for c in prospects if c in drafted_before],
    format_func=lambda c: prospects[c],
    key=f"draftpick_{pick_cid}_{role}_{pos}",
    help="SMAT/BBL look-alikes you pick here are pre-loaded as retentions on the Auction page.",
)
# Only players in the priced auction pool can be drafted (the rest are too few
# balls / a non-IPL nation) — mirrors the web's draft guard.
pool_cids = _auction_pool_cids()
eligible = [c for c in chosen if c in pool_cids]
ineligible = [prospects[c] for c in chosen if c not in pool_cids]
drafted = [c for c in drafted_before if c not in prospects] + eligible
st.session_state["drafted"] = drafted
if ineligible:
    st.warning(
        f"{', '.join(ineligible)} — not in the priced auction pool (too few balls, or a "
        "non-IPL nation), so can't be drafted."
    )
if drafted:
    st.success(f"{len(drafted)} prospect(s) queued — open the **Auction** page to place them.")
    if st.button("Clear all drafts", key="draft_clear"):
        st.session_state["drafted"] = []
        for k in [k for k in st.session_state if str(k).startswith("draftpick_")]:
            del st.session_state[k]
        st.rerun()
