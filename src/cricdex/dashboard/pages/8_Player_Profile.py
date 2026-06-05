"""Streamlit page: per-player dossier.

Reads the SAME pre-cooked JSON the React web app
(`site/src/pages/PlayerProfile.tsx`) fetches — `players.json` for the picker,
`profiles/<cricsheet_id>.json` for the full dossier, and
`cohorts/<cricsheet_id>.json` for the graph cohort — so the desktop dashboard
matches the live site instead of recomputing from DuckDB.
"""

from __future__ import annotations

import datetime as dt
import json

import streamlit as st

from cricdex.common.filters import load_cohorts
from cricdex.dashboard._widgets import player_select, provenance_banner
from cricdex.web_parity.loader import SITE_DATA

st.set_page_config(page_title="CricDex Profile", page_icon="🪪", layout="wide")
st.title("🪪 CricDex — player profile")
st.caption(
    "A full dossier per player: identity, four Bayesian skill axes with their "
    "uncertainty, career totals, the novel metrics, how they get out, and "
    "their closest stylistic twins. Reads the exact same exported JSON the "
    "website does."
)

POS_LABEL = {
    "opener": "Opener",
    "no3": "No. 3",
    "middle": "Middle order",
    "finisher": "Finisher",
    "lower": "Lower order",
    "tailender": "Tailender",
}

# slug -> (title, value-key, subtitle) — mirror PlayerProfile.tsx MetricCard
METRIC_CARDS = {
    "pressure_runs": ("Pressure Runs", "pressure_sr_per_100_balls", "SR under chase pressure"),
    "dot_ball_recovery": (
        "Dot-Ball Recovery",
        "runs_per_6_after_dot",
        "runs / 6 balls after a dot",
    ),
    "counter_attack": ("Counter-Attack", "counter_attack_sr", "SR after a partner falls"),
    "boundary_dependency": ("Boundary Dependency", "bdr_pct", "% of runs from boundaries"),
    "pressure_conversion": ("Pressure Conversion", "wicket_rate_pct", "pressure balls → wickets"),
}


def _num(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        n = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if n == n else None


def _fmt(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.{digits}f}"


def _age_from(dob: str | None) -> int | None:
    if not dob:
        return None
    try:
        d = dt.date.fromisoformat(dob[:10])
    except (ValueError, TypeError):
        return None
    today = dt.date.today()
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def _has_players(collection: str) -> bool:
    return (SITE_DATA / collection / "players.json").exists() and (
        SITE_DATA / collection / "profiles"
    ).is_dir()


@st.cache_data(ttl=300)
def list_collections() -> list[str]:
    cols_file = SITE_DATA / "collections.json"
    names: list[str] = []
    if cols_file.exists():
        try:
            names = [c["collection"] for c in json.loads(cols_file.read_text())]
        except Exception:
            names = []
    if not names:
        names = sorted(p.name for p in SITE_DATA.iterdir() if p.is_dir())
    return [c for c in names if _has_players(c)]


@st.cache_data(ttl=300)
def load_profile(collection: str, cid: str) -> dict | None:
    path = SITE_DATA / collection / "profiles" / f"{cid}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


@st.cache_data(ttl=300)
def load_cohort(collection: str, cid: str) -> dict:
    try:
        return load_cohorts(collection, cid)
    except FileNotFoundError:
        return {}


collections = list_collections()
if not collections:
    st.warning(
        "No exported players.json / profiles found under site/public/data/. "
        "Run `uv run python scripts/export_site.py` first."
    )
    st.stop()

with st.sidebar:
    collection = st.selectbox(
        "Collection",
        options=collections,
        index=collections.index("ipl") if "ipl" in collections else 0,
        key="profile-collection",
        help="Only collections with exported players.json + profiles are listed.",
    )

provenance_banner(source="cricsheet", path=SITE_DATA / collection / "meta.json")

with st.sidebar:
    sel = player_select(collection, "Player", key="profile-player")
if sel is None:
    st.warning("No players in the exported players.json for this collection.")
    st.stop()

cid = sel["cricsheet_id"]
player_name = sel["name"]
profile = load_profile(collection, cid)
if not profile:
    st.error(f"No exported profile found for {player_name} ({cid}).")
    st.stop()

wd = profile.get("wikidata") or {}
tax = profile.get("taxonomy") or {}
act = profile.get("activity") or {}
ids = profile.get("ids") or {}
bat = (profile.get("bayes") or {}).get("bayes_batter") or {}
bowl = (profile.get("bayes") or {}).get("bayes_bowler") or {}
career = profile.get("career") or {}
metrics = profile.get("metrics") or {}

# --- identity card ------------------------------------------------------
img_col, info_col = st.columns([1, 4])
with img_col:
    if wd.get("image_url"):
        st.image(wd["image_url"], width=150)
with info_col:
    st.header(wd.get("label") or profile.get("name") or player_name)
    dob = wd.get("dob")
    if dob:
        age = _age_from(dob)
        try:
            pretty = dt.date.fromisoformat(dob[:10]).strftime("%-d %b %Y")
        except (ValueError, TypeError):
            pretty = dob
        st.caption(f"🎂 Born {pretty}" + (f" · {age} yrs" if age is not None else ""))

    # taxonomy + activity + value badges (mirror Identity badges)
    chips: list[str] = []
    if act:
        last = (act.get("last_match_date") or "")[:4]
        chips.append(
            "🟢 active"
            if act.get("active")
            else (f"⚪ retired · last {last}" if last else "⚪ retired")
        )
    if tax.get("primary_role"):
        chips.append(f"**{str(tax['primary_role']).replace('_', '-')}**")
    if tax.get("bowling_style") and tax.get("bowling_category") != "none":
        chips.append(str(tax["bowling_style"]).replace("-", " "))
    if tax.get("batting_position"):
        chips.append(POS_LABEL.get(tax["batting_position"], tax["batting_position"]))
    if tax.get("country"):
        chips.append(str(tax["country"]))
    if _num(bat.get("value")) is not None:
        chips.append(f"batting value {_fmt(_num(bat.get('value')), 3)}")
    if _num(bowl.get("value")) is not None and (_num(bowl.get("balls")) or 0) > 60:
        chips.append(f"bowling value {_fmt(_num(bowl.get('value')), 3)}")
    chips.append(f"id {cid}")
    st.markdown(" · ".join(chips))

    # socials (instagram / twitter / espncricinfo / wikidata)
    social: list[str] = []
    if wd.get("instagram"):
        social.append(f"[Instagram](https://instagram.com/{wd['instagram']})")
    if wd.get("twitter"):
        social.append(f"[𝕏 Twitter](https://twitter.com/{wd['twitter']})")
    cricinfo = ids.get("key_cricinfo")
    if cricinfo:
        social.append(f"[ESPNcricinfo](https://www.espncricinfo.com/cricketers/x-{cricinfo})")
    if wd.get("wikidata_qid"):
        social.append(f"[Wikidata](https://www.wikidata.org/wiki/{wd['wikidata_qid']})")
    if social:
        st.markdown(" · ".join(social))

# --- career tiles -------------------------------------------------------
if career:
    st.subheader("Career")
    c = st.columns(6)
    c[0].metric("Runs", _fmt(_num(career.get("career_runs")), 0))
    c[1].metric("Balls faced", _fmt(_num(career.get("career_balls_faced")), 0))
    c[2].metric("Innings", _fmt(_num(career.get("career_innings")), 0))
    c[3].metric("Fours / Sixes", f"{career.get('career_fours', 0)}/{career.get('career_sixes', 0)}")
    c[4].metric("Wickets", _fmt(_num(career.get("career_wickets")), 0))
    c[5].metric("Balls bowled", _fmt(_num(career.get("career_legal_balls_bowled")), 0))


def _axis_pct(x: float) -> float:
    """Map a latent skill value ~[-0.6, 0.6] onto 0..100 (mirror web SkillAxis)."""
    return max(0.0, min(100.0, (x + 0.6) / 1.2 * 100))


def _skill_axis(label: str, mean: float | None, sd: float | None, hint: str) -> None:
    if mean is None:
        return
    val = f"{'+' if mean >= 0 else ''}{mean:.3f}"
    if sd is not None:
        val += f" ± {sd:.3f}"
    st.markdown(f"**{label}** — {val}")
    # Track with a shaded ±sd band and a marker at the mean — mirrors the
    # web SkillAxis (dot at mean, uncertainty band around it).
    mean_pct = _axis_pct(mean)
    if sd is not None and sd > 0:
        lo, hi = _axis_pct(mean - sd), _axis_pct(mean + sd)
    else:
        lo = hi = mean_pct
    st.markdown(
        f"""<div style="position:relative;height:12px;border-radius:6px;
        background:#1f2937;margin:2px 0 4px">
          <div style="position:absolute;left:{lo}%;width:{max(0.5, hi - lo)}%;top:0;bottom:0;
            background:rgba(52,211,153,0.35);border-radius:6px"></div>
          <div style="position:absolute;left:calc({mean_pct}% - 3px);top:-1px;width:6px;height:14px;
            border-radius:3px;background:#34d399"></div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.caption(hint)


# --- bayesian skill axes ------------------------------------------------
sk_left, sk_right = st.columns(2)
with sk_left:
    if bat:
        st.subheader("Batting skill")
        st.caption("Two latent axes — scoring & survival — with model uncertainty")
        _skill_axis(
            "Scoring (runs added)",
            _num(bat.get("skill")),
            _num(bat.get("skill_sd")),
            "how fast they score above a replacement batter",
        )
        _skill_axis(
            "Survival (wicket-avoidance)",
            _num(bat.get("survival_skill")),
            _num(bat.get("survival_skill_sd")),
            "how well they avoid getting out per ball",
        )
        st.caption(f"From {_fmt(_num(bat.get('balls')), 0)} balls faced.")
with sk_right:
    if bowl and (_num(bowl.get("balls")) or 0) > 60:
        st.subheader("Bowling skill")
        st.caption("Two latent axes — economy & strike — with model uncertainty")
        _skill_axis(
            "Economy (run suppression)",
            _num(bowl.get("skill")),
            _num(bowl.get("skill_sd")),
            "how few runs they concede per ball",
        )
        _skill_axis(
            "Strike (wicket-taking)",
            _num(bowl.get("strike_skill")),
            _num(bowl.get("strike_skill_sd")),
            "how often they take a wicket per ball",
        )
        st.caption(f"From {_fmt(_num(bowl.get('balls')), 0)} balls bowled.")

# --- novel metrics cards ------------------------------------------------
if any(metrics.get(slug) for slug in METRIC_CARDS):
    st.subheader("Novel metrics")
    cols = st.columns(5)
    for col, (slug, (title, val_key, sub)) in zip(cols, METRIC_CARDS.items(), strict=True):
        with col:
            m = metrics.get(slug)
            v = _num(m.get(val_key)) if isinstance(m, dict) else None
            st.markdown(f"**{title}**")
            st.markdown(f"### {_fmt(v, 1)}")
            st.caption(sub)

# --- dismissal fingerprint ----------------------------------------------
fp = profile.get("dismissal_fingerprint") or {}
if fp.get("batter") or fp.get("bowler"):
    st.subheader("🎯 Dismissal fingerprint")
    st.caption("How they get out (batting) / take wickets (bowling)")
    fp_left, fp_right = st.columns(2)

    def _fp_block(col, title: str, d: dict | None) -> None:
        with col:
            if not d or not d.get("rows"):
                st.info(f"No data for {title.lower()}.")
                return
            st.markdown(f"**{title}** · {d.get('total', 0)} total")
            for r in d["rows"][:6]:
                pct = _num(r.get("pct")) or 0
                st.markdown(
                    f"{str(r.get('kind', '')).capitalize()} — {pct:.1f}% ({r.get('count')})"
                )
                st.progress(min(1.0, pct / 100))
            if d.get("read"):
                st.caption(f"“{d['read']}”")

    _fp_block(fp_left, "As batter", fp.get("batter"))
    _fp_block(fp_right, "As bowler", fp.get("bowler"))

# --- style twins --------------------------------------------------------
st.subheader("Style twins")
st.caption("Nearest players in feature space")
tw_left, tw_right = st.columns(2)


def _twins_block(col, role: str, twins: list[dict] | None) -> None:
    with col:
        st.markdown(f"**{role}**")
        if not twins:
            st.info(f"No {role.lower()} style twins for this player.")
            return
        rows = []
        for t in twins[:6]:
            dist = _num(t.get("distance"))
            sim = max(0.0, 1 - dist) * 100 if dist is not None else None
            rows.append(
                {"Player": t.get("name"), "% alike": f"{sim:.1f}%" if sim is not None else "—"}
            )
        st.dataframe(rows, width="stretch", hide_index=True)


_twins_block(tw_left, "Batter", profile.get("style_twins_batter"))
_twins_block(tw_right, "Bowler", profile.get("style_twins_bowler"))

# --- graph cohort -------------------------------------------------------
st.subheader("Graph cohort")
st.caption("Players who faced the same bowlers / shared a side")
co_faced = (load_cohort(collection, cid) or {}).get("co_faced") or []
if not co_faced:
    st.info("No graph cohort available.")
else:
    st.dataframe(
        [
            {
                "Player": r.get("name"),
                "Role": str(r.get("primary_role", "") or "").replace("_", "-"),
                # Field is role-dependent: batters → shared_bowlers, bowlers → shared_batters.
                "Shared": r.get("shared_bowlers") or r.get("shared_batters"),
            }
            for r in co_faced[:10]
        ],
        width="stretch",
        hide_index=True,
    )
