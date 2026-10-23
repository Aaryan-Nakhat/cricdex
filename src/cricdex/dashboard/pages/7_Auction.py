"""Streamlit page: Auction room — real-rules IPL auction Monte-Carlo.

Identical to the web Auction room (and locked to it by
`test_scripts/test_web_parity.py`): same exported pool
(`site/public/data/ipl/{auction_pool,retentions}.json`), same logic
(`cricdex.web_parity`), same seeded RNG — so a run here reproduces the
browser trial-for-trial. Pick Mega/Mini, edit retentions per team, run; see
who lands each star and how each squad shapes up.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cricdex import leagues
from cricdex.common.display import display_name, player_label
from cricdex.dashboard._widgets import load_players, provenance_banner
from cricdex.scout import translation
from cricdex.web_parity import (
    IPL_TEAMS_DEFAULT,
    build_pool,
    default_retentions,
    load_activity_index,
    load_auction_pool,
    load_retentions,
    simulate_auction,
)
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Auction", page_icon="💰", layout="wide")
st.title("💰 CricDex — Auction room")
st.caption(
    "Monte-Carlo of a real IPL auction. Each franchise retains its core (Mega = the "
    "real 2025 lists; Mini = keep most of the squad — editable below), then the ten "
    "teams bid for everyone else by a demand model fitted on real auctions, hundreds of "
    "times. Same data + "
    "logic + seeded RNG as the web app."
)
provenance_banner(source="cricsheet", path=SITE_DATA / "ipl" / "auction_pool.json")

# who feeds the pool and how each league translates (config/leagues.toml and the fitted
# config/league_translation.json)
_POOL = {**leagues.auction_pool_summary(), "translation": translation.summary_text()}

with st.expander("How the auction math works (plain English)"):
    st.markdown(
        "The data only knows how **good** a player is (a skill rating) — never what he **costs**. "
        "So step zero is inventing a fair price from skill, then everything builds on that.\n\n"
        "**Part 1 · Skill → crore price**\n"
        "1. *Market price* — a model fitted on every IPL auction since 2018 prices each player from "
        "his value, nationality, caps, age, IPL record and the auction type (section 6b).\n"
        "2. *Playing time* — the pool is ranked by expected season value: the chance he plays a "
        "match × his runs above a replacement a match (section 6c).\n"
        "3. *Base price* — the opening tag, snapped to IPL bands (0.3 / 0.5 / 0.75 / 1 / 1.5 / 2 cr); "
        "bidding pushes the final price up from there.\n\n"
        "**Part 2 · Who's in the pool** — the whole active T20 world: IPL players (retainable) + "
        f"free agents (overseas via {_POOL['overseas']}, uncapped Indians via {_POOL['uncapped']}). "
        "Active only (last ~3 yrs). Every other league's rating is translated onto the IPL scale, "
        "per league and role, by a fit on players seen in both, then blended with his IPL record "
        f"by how certain each is ({_POOL['translation']}).\n\n"
        "**Part 3 · Retentions + auction** — each franchise retains its core (Mega/Mini), then the "
        "lots (as many as real shortlists held for the open places; capped first) go up one by one. "
        "Each team with a place and the purse decides whether to bid and how high from a demand model "
        "fitted on who really bought whom, and for how much, at the 2019–2026 auctions: his market and "
        "base price, the money per open place, its places short in his role and overseas, its purse "
        "per place, how much he'd improve its squad, how far the auction has gone, plus the lot's heat "
        "and each team's own view. The highest bid wins one ladder step above the second-highest. "
        "Hundreds of runs, same seeded RNG as the web app."
    )


@st.cache_data(ttl=600, show_spinner=False)
def _load():
    return load_auction_pool("ipl"), load_retentions("ipl")


try:
    pool_rows, ret = _load()
except (FileNotFoundError, ValueError) as e:  # missing or corrupt export
    st.error(f"{e}")
    st.stop()

pool = build_pool(pool_rows)
by_id = {p["cricsheet_id"]: p for p in pool}
# fan-facing names (the priced pool keeps only the scorecard name)
_display = {r["cricsheet_id"]: display_name(r) for r in pool_rows}


def _nm(p: dict) -> str:
    return _display.get(p.get("cricsheet_id", "")) or p.get("name", "")


try:
    act = load_activity_index("ipl")  # cid -> last-IPL / age / p_play
except ValueError as e:
    st.error(f"Could not read `activity_index.json` ({e}); plays % / last IPL / age left blank.")
    act = {}


def _fit(cid: str) -> int | None:
    a = act.get(cid)
    p = (a or {}).get("p_play")
    return round(p * 100) if p is not None else None


def _last_ipl(cid: str):
    a = act.get(cid)
    return (a.get("last_ipl") or "never")[:4] if a else None


def _age(cid: str):
    a = act.get(cid)
    return a.get("age") if a else None


from cricdex.web_parity.auction import retention_inputs  # noqa: E402

_ri = retention_inputs(ret)  # the real 2025 lists, prices and the slab rule they cost
mega_ids = _ri["mega_ids"]

# ---- controls --------------------------------------------------------------
mode = st.radio(
    "Auction type",
    ["mega", "mini"],
    horizontal=True,
    format_func=lambda m: "Mega auction" if m == "mega" else "Mini auction",
)
c1, c2, c3, c4 = st.columns(4)
purse = c1.number_input(
    "Purse / team (cr)",
    10.0,
    500.0,
    value=120.0 if mode == "mega" else 30.0,
    step=5.0,
    key=f"purse_{mode}",
)
squad_size = c2.number_input("Squad cap", 20, 25, value=25, key="squad")
overseas_cap = c3.number_input("Overseas cap", 0, 11, value=8, key="overseas")
trials = c4.number_input("Trials", 50, 1000, value=300, step=50, key="trials")

teams = [{"team": t["team"]} for t in IPL_TEAMS_DEFAULT]

# default retentions for the mode, plus any prospects drafted from Scout
base_ret = default_retentions(pool, teams, mode, mega_ids)
drafted = [c for c in st.session_state.get("drafted", []) if c in by_id]
if drafted:
    # Which franchise keeps the drafted prospect(s) — you choose, not hardcoded.
    draft_team = st.selectbox(
        f"{len(drafted)} prospect(s) drafted from Scout — assign to team",
        [t["team"] for t in teams],
        key="draft_team",
    )
    base_ret[draft_team] = list(dict.fromkeys(base_ret[draft_team] + drafted))
    st.info(
        f"{', '.join(_nm(by_id[c]) for c in drafted)} → locked as retention(s) for "
        f"{draft_team} (editable below)."
    )

with st.expander("Retentions (editable per team)", expanded=True):
    retentions = {}
    cols = st.columns(2)
    for i, t in enumerate(teams):
        team = t["team"]
        # options = all pool ids on this team OR already retained (so drafted free
        # agents show up too); label with name + projected price.
        opt_ids = [p["cricsheet_id"] for p in pool if p["team"] == team] + [
            c for c in base_ret[team] if by_id.get(c) and by_id[c]["team"] != team
        ]
        opt_ids = list(dict.fromkeys(opt_ids))
        sel = cols[i % 2].multiselect(
            team,
            opt_ids,
            default=[c for c in base_ret[team] if c in opt_ids],
            format_func=lambda c: f"{_nm(by_id[c])} ({by_id[c]['projected_value']:.0f}cr)",
            key=f"ret_{team}_{mode}",
        )
        retentions[team] = sel

# The result lives in session_state so the lookups below ("Find a player",
# "Team") don't wipe it on rerun. It is dropped as soon as any setting that
# shaped it changes (mode / purse / caps / trials /
# retentions) — the same reset rule as the web Auction room.
_settings = (
    mode,
    float(purse),
    int(squad_size),
    int(overseas_cap),
    int(trials),
    tuple((team, tuple(ids)) for team, ids in retentions.items()),
)
_saved = st.session_state.get("auction_result")
if _saved is not None and _saved[0] != _settings:
    del st.session_state["auction_result"]
    _saved = None

if st.button("🎲 Run simulation", type="primary"):
    res = simulate_auction(
        pool,
        teams,
        {
            "purse": purse,
            "squad_size": int(squad_size),
            "overseas_cap": int(overseas_cap),
            "trials": int(trials),
            "mode": mode,
            "retentions": retentions,
            "real_prices": _ri["real_prices"],
            "retention_slabs": _ri["retention_slabs"],
            "slab_holders": _ri["slab_holders"],
            "fixed_retained": _ri["fixed_retained"],
        },
    )
    st.session_state["auction_result"] = (_settings, res)
elif _saved is not None:
    res = _saved[1]
else:
    st.info("Set the knobs and retentions, then **Run simulation**.")
    st.stop()

st.subheader("How each squad shapes up")
st.caption(
    f"{'Mega' if mode == 'mega' else 'Mini'} auction · {res['auctioned']} of {res['pool_size']} unretained players under the "
    f"hammer · averaged over {int(trials)} runs"
)
teams_df = pd.DataFrame(
    [
        {
            "Team": t["team"],
            "Retained": t["retained"],
            "Bought": round(t["avg_bought"]),
            "Auction spend (cr)": round(t["avg_spend"], 1),
            "Squad value": round(t["avg_value"], 1),
            "Overseas": round(t["avg_overseas"]),
        }
        for t in sorted(res["teams"], key=lambda t: t["avg_value"], reverse=True)
    ]
)
st.dataframe(teams_df, hide_index=True, width="stretch")

st.subheader("Who lands the marquee names")
marq_df = pd.DataFrame(
    [
        {
            "Player": _nm(m["player"]),
            "Role": m["player"]["role"].replace("_", "-"),
            "Value": round(m["player"]["projected_value"], 1),
            "Plays %": _fit(m["player"]["cricsheet_id"]),
            "Last IPL": _last_ipl(m["player"]["cricsheet_id"]),
            "Age": _age(m["player"]["cricsheet_id"]),
            "Most likely": ", ".join(f"{w['team']} {w['pct']:.0f}%" for w in m["winners"])
            or "unsold",
        }
        for m in res["marquee"]
    ]
)
st.dataframe(marq_df, hide_index=True, width="stretch")

st.subheader("Find a player")
# Searchable dropdown over the run's players (type-ahead on display, scorecard, full name and
# aliases), mirroring the web Combobox instead of a bare text field.
_players_by_cid = {p["cricsheet_id"]: p for p in load_players("ipl")}
_outcome_name = {o["cricsheet_id"]: o["name"] for o in res["outcomes"]}


def _auction_label(cid: str) -> str:
    row = _players_by_cid.get(cid)
    if row:
        return player_label(row)
    disp, name = _display.get(cid), _outcome_name.get(cid, cid)
    return f"{disp} ({name})" if disp and disp != name else name


_PICK = "— pick a player —"
_cids = sorted(_outcome_name, key=lambda c: _auction_label(c).lower())
pick = st.selectbox(
    "Where did anyone land, for how much, or did they go unsold?",
    [_PICK, *_cids],
    format_func=lambda c: c if c == _PICK else _auction_label(c),
    key="auction_search",
)
if pick != _PICK:
    hits = [o for o in res["outcomes"] if o["cricsheet_id"] == pick]
    if not hits:
        st.info(f"No outcome for '{_auction_label(pick)}'.")
    else:
        srows = []
        for o in hits[:50]:
            if o["status"] == "retained":
                where = f"{o['team']} · retained"
            elif o["status"] == "unsold":
                where = "went unsold"
            else:
                where = ", ".join(f"{w['team']} {w['pct']:.0f}%" for w in o["winners"])
            srows.append(
                {
                    "Player": _nm(o),
                    "Role": o["role"].replace("_", "-"),
                    "Plays %": _fit(o["cricsheet_id"]),
                    "Last IPL": _last_ipl(o["cricsheet_id"]),
                    "Age": _age(o["cricsheet_id"]),
                    "Status": o["status"],
                    "Avg price (cr)": None if o["status"] == "unsold" else round(o["avgPrice"], 1),
                    "Sold %": round(o["soldPct"]) if o["status"] == "sold" else None,
                    "Where": where,
                }
            )
        st.dataframe(pd.DataFrame(srows), hide_index=True, width="stretch")
else:
    st.caption("Pick a player to see where they landed, for how much, or if they went unsold.")

st.subheader("A representative squad")
if not res["sample_draft"]:
    st.caption("No sample squad in this run.")
    st.stop()
squad_team = st.selectbox("Team", [s["team"] for s in res["sample_draft"]], key="squad_team")
st_state = next(s for s in res["sample_draft"] if s["team"] == squad_team)


def _squad_chip(p: dict) -> str:
    plane = " ✈" if p.get("is_overseas") else ""
    return f"- **{_nm(p)}** · {p['role'].replace('_', '-')}{plane}"


rc, bc = st.columns(2)
with rc:
    st.markdown(f"**Retained ({len(st_state['retained'])})**")
    st.markdown("\n".join(_squad_chip(p) for p in st_state["retained"]) or "_none_")
with bc:
    st.markdown(f"**Bought ({len(st_state['bought'])})**")
    st.markdown("\n".join(_squad_chip(p) for p in st_state["bought"]) or "_no buys in this sample_")
st.caption(
    f"{len(st_state['retained']) + len(st_state['bought'])} total · "
    f"{st_state['overseas']} overseas · auction spend {st_state['spent']:.1f} cr"
)
