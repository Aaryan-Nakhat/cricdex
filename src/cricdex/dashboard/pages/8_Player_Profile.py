"""Streamlit page: per-player profile.

Pulls everything CricDex knows about a player into one card. Inputs
go through the fuzzy resolver so typos / partial names are caught
with a 'did you mean?' confirmation.
"""

from __future__ import annotations

import duckdb
import streamlit as st

from cricdex.config import DATA_DIR
from cricdex.dashboard._widgets import collection_picker, fuzzy_player_input, provenance_banner
from cricdex.profiles import builder

DUCKDB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

st.set_page_config(page_title="CricDex Profile", page_icon="🪪", layout="wide")
st.title("🪪 CricDex — player profile")
st.caption(
    "Everything CricDex knows about one player — cross-source IDs, "
    "career totals, novel metrics, Bayesian scout-rating skills, "
    "top style twins, and the graph cohort. All derived live from "
    "Cricsheet ball-by-ball + the People Register."
)
provenance_banner(source="cricsheet", path=DUCKDB_PATH)


@st.cache_data
def list_players(collection: str) -> list[str]:
    safe = collection.replace("-", "_")
    if not DUCKDB_PATH.exists():
        return []
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if f"balls_{safe}" not in tables:
            return []
        rows = con.execute(
            f"""
            SELECT batter, COUNT(*) AS n
            FROM balls_{safe}
            WHERE batter IS NOT NULL
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 2000
            """
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


with st.sidebar:
    collection = collection_picker(default="ipl", key="profile-collection")
    pool = list_players(collection)
    if not pool:
        st.warning(
            f"no balls_{collection} — run `cricdex data ingest cricsheet -c {collection}` first"
        )
        st.stop()
    st.markdown("Type a player name — fuzzy-matched against the collection.")
    name = fuzzy_player_input(
        label="Player",
        default="V Kohli",
        collection=collection,
        key="profile-player",
    )
    if not name:
        st.info("Confirm a player above to load the profile.")
        st.stop()

profile = builder.build(name, collection)

st.header(profile["name"])
ids = profile.get("ids") or {}
if ids:
    chips: list[str] = []
    for k, v in ids.items():
        if v and k != "unique_name":
            chips.append(f"`{k}={v}`")
    st.caption(" · ".join(chips))


def _load_wikidata_for(cricsheet_id: str) -> dict:
    """Wikidata enrichment cache lookup. None-safe."""
    import datetime as _dt
    import json as _json

    from cricdex.config import ROOT

    path = ROOT / "data" / "curated" / "wikidata_enrichment.json"
    if not path.exists():
        return {}
    try:
        data = _json.loads(path.read_text())
    except Exception:
        return {}
    record = data.get(cricsheet_id) or {}
    # Age computation
    dob = record.get("dob")
    if dob:
        try:
            d = _dt.date.fromisoformat(dob[:10])
            today = _dt.date.today()
            age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
            record["age"] = age
        except Exception:
            pass
    return record


wd = _load_wikidata_for(profile.get("cricsheet_id") or "")
if wd and wd.get("_status") == "ok":
    img_col, info_col = st.columns([1, 3])
    with img_col:
        if wd.get("image_url"):
            st.image(wd["image_url"], width=180)
    with info_col:
        m = st.columns(4)
        m[0].metric("DOB", wd.get("dob") or "—")
        m[1].metric("Age", wd.get("age") or "—")
        m[2].metric("Country (Wikidata Q-id)", wd.get("country_qid") or "—")
        m[3].metric("Birthplace (Q-id)", wd.get("birthplace_qid") or "—")
        social = []
        if wd.get("twitter"):
            social.append(f"[𝕏 @{wd['twitter']}](https://twitter.com/{wd['twitter']})")
        if wd.get("instagram"):
            social.append(
                f"[Instagram @{wd['instagram']}](https://instagram.com/{wd['instagram']})"
            )
        if wd.get("espn_id"):
            social.append(
                f"[ESPNcricinfo](https://www.espncricinfo.com/cricketers/{wd['espn_id']})"
            )
        if wd.get("cricbuzz_id"):
            social.append(f"[Cricbuzz](https://www.cricbuzz.com/profiles/{wd['cricbuzz_id']})")
        if wd.get("wikidata_qid"):
            social.append(f"[Wikidata](https://www.wikidata.org/wiki/{wd['wikidata_qid']})")
        if social:
            st.markdown(" · ".join(social))
        st.caption(
            "Wikidata-sourced (image + DOB + cross-source IDs). Country / birthplace are "
            "raw Q-ids in v1 — label resolution in vNext. Refresh with "
            "`cricdex data ingest wikidata --force`."
        )
elif wd and wd.get("_status") == "not_found":
    st.caption("Wikidata: no entity found for this player.")
else:
    st.caption(
        "Wikidata enrichment not yet pulled for this player — run "
        "`cricdex data ingest wikidata` to populate."
    )

st.subheader("Career totals")
career = profile.get("career") or {}
c1, c2, c3, c4 = st.columns(4)
c1.metric("Runs", career.get("career_runs", 0))
c2.metric("Balls faced", career.get("career_balls_faced", 0))
c3.metric("Sixes", career.get("career_sixes", 0))
c4.metric("Wickets", career.get("career_wickets", 0))

st.subheader("Novel metrics")
metrics = profile.get("metrics") or {}
METRIC_HINTS = {
    "pressure_runs": (
        "Strike rate on balls where the required run rate is ≥ 1.5× the venue "
        "median (chase only). Higher = better under pressure."
    ),
    "recoverability": (
        "How efficiently this batter recovers after a slow patch. Higher = "
        "doesn't let one dot ball spiral."
    ),
    "counter_attack": (
        "Strike rate inflation right after a wicket falls. Higher = aggressive "
        "after partnership-breaking dismissals."
    ),
    "boundary_dependency": (
        "Share of runs from 4s + 6s. Higher = boundary-reliant; lower = strong strike-rotator."
    ),
    "sticky_dot_pressure": (
        "Wicket rate on the next ball after a 4+ consecutive dot streak in the "
        "same over (bowler metric). Higher = turns pressure into dismissals."
    ),
}


def _metric_to_rows(slug: str, payload) -> list[dict]:
    if not payload:
        return [
            {
                "value": "—",
                "note": "no data — below min-balls threshold or not computed for this collection",
            }
        ]
    if isinstance(payload, dict):
        return [
            {"field": k, "value": v}
            for k, v in payload.items()
            if k not in {"batter", "bowler", "cricsheet_id"} and v is not None
        ] or [{"value": "—", "note": "all fields empty"}]
    return [{"value": str(payload)}]


for slug, hint in METRIC_HINTS.items():
    with st.expander(f"**{slug.replace('_', ' ').title()}** — {hint}"):
        st.table(_metric_to_rows(slug, metrics.get(slug)))


st.markdown("### Bayesian scout-rating")
bayes = profile.get("bayes") or {}


def _bayes_sentence(role_key: str, label: str, skill_key: str = "skill") -> str:
    # builder.build returns nested dicts: `bayes.bayes_batter / bayes_bowler`
    rec = (bayes or {}).get(f"bayes_{role_key}") or {}
    skill = rec.get(skill_key)
    if skill is None:
        return f"{label}: not enough data."
    sd = rec.get(f"{skill_key}_sd")
    balls = rec.get("balls")
    sd = sd if sd is not None else 1.0
    confidence = "high" if sd < 0.05 else ("medium" if sd < 0.10 else "low")
    tail = f" on {balls or '?'} balls" if skill_key == "skill" else ""
    return f"{label}: **{skill:+.3f}** ({confidence} confidence; σ={sd:.3f}{tail})."


st.markdown(_bayes_sentence("batter", "Batter scoring rate"))
st.markdown(_bayes_sentence("batter", "Batter survival (dismissal resistance)", "survival_skill"))
st.markdown(_bayes_sentence("bowler", "Bowler economy"))
st.markdown(_bayes_sentence("bowler", "Bowler strike (wicket-taking)", "strike_skill"))
st.caption(
    "Skills are on the natural-log scale of the NumPyro / JAX hierarchical "
    "joint fit (runs Negative-Binomial + dismissals Binomial). 0 = league "
    "average, higher = better on every axis. Scoring rate + survival "
    "together give complete batting value; economy + strike give complete "
    "bowling value. A fast slogger who gets out often scores high on "
    "scoring but low on survival."
)

st.subheader("Style twins")
left, right = st.columns(2)
with left:
    st.markdown("**As batter**")
    twins = profile.get("style_twins_batter") or []
    if twins:
        st.dataframe(twins, use_container_width=True, hide_index=True)
    else:
        st.info("no batter style-twins available for this player + collection")
with right:
    st.markdown("**As bowler**")
    twins = profile.get("style_twins_bowler") or []
    if twins:
        st.dataframe(twins, use_container_width=True, hide_index=True)
    else:
        st.info("no bowler style-twins available for this player + collection")

st.subheader("🎯 Dismissal fingerprint")
st.caption(
    "*How* this player gets out / takes wickets — descriptive scouting "
    "metadata, separate from the skill model (which only cares about the "
    "rate). High bowled+lbw = beaten at the stumps (technique); high "
    "caught = false / aerial shots; high stumped = footwork vs spin. For "
    "bowlers: bowled+lbw = attacks the stumps; caught = bowls for the "
    "catch; stumped = flights it."
)
fp = profile.get("dismissal_fingerprint") or {}
fp_left, fp_right = st.columns(2)
with fp_left:
    bat_fp = fp.get("batter") or {}
    st.markdown(f"**As batter** ({bat_fp.get('total', 0)} dismissals)")
    if bat_fp.get("rows"):
        st.dataframe(bat_fp["rows"], use_container_width=True, hide_index=True)
        st.caption(f"→ {bat_fp.get('read', '')}")
    else:
        st.info("no dismissals recorded")
with fp_right:
    bowl_fp = fp.get("bowler") or {}
    st.markdown(f"**As bowler** ({bowl_fp.get('total', 0)} wickets)")
    if bowl_fp.get("rows"):
        st.dataframe(bowl_fp["rows"], use_container_width=True, hide_index=True)
        st.caption(f"→ {bowl_fp.get('read', '')}")
    else:
        st.info("no bowler-credited wickets recorded")

st.subheader("🔗 Graph cohort (Neo4j)")
st.caption(
    "Players in the same competitive neighbourhood — derived from the scout "
    "graph's FACED and TEAMMATE_OF edges. Complements the cosine style-twins "
    "above with a relational signal."
)
try:
    from cricdex.scout.graph import similar

    g_col1, g_col2 = st.columns(2)
    with g_col1:
        st.markdown("**Co-faced bowlers cohort**")
        rows = similar.co_faced_bowlers(name, top_k=8)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("no graph cohort — populate scout graph for this collection")
    with g_col2:
        st.markdown("**Teammate overlap cohort**")
        rows = similar.teammate_overlap(name, top_k=8)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("no teammate overlap — populate scout graph")

    st.markdown(
        "**Suggested substitutes** (graph similarity × Bayes value, role-matched, on a 10 cr budget)"
    )
    try:
        from cricdex.auction import advisor

        rec = advisor.recommend_substitutes(name, budget=10.0, n=8)
        if rec.is_empty():
            st.info(
                "no affordable substitutes — try a higher budget via "
                "`scripts/auction_advisor.py` or the Auction page."
            )
        else:
            st.dataframe(rec.to_pandas(), use_container_width=True, hide_index=True)
    except ImportError:
        pass
except ImportError:
    st.info("`neo4j` extra not installed — run `uv sync --extra graph`.")

with st.expander("Raw profile JSON"):
    st.json(profile)
