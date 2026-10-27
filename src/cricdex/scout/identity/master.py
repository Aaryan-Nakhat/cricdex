"""The player master: one identity record per player of every exported league.

`build()` joins, by Cricsheet id:

- the People Register (scorecard names, name variants, ESPNcricinfo ids) and each exported league's
  match registry and XIs (who played where, when) — read-only;
- the ball data across every exported league (overs bowled, balls faced, batting position,
  stumpings) for a data-driven role;
- Wikidata (label, aliases, date of birth, country) and the Wikipedia infobox (full name, batting
  hand, bowling style, role) — see `sources`;
- Cricsheet's men's T20I / ODI / Test XIs for the capped flag;
- the 2026 IPL squads and retirements (Wikipedia personnel page, cached and hand-editable);
- the LLM taxonomy (`player_taxonomy.json`, the old single source) and the LLM name check;
- `player_overrides.json`, the reviewed file that always wins;
- `ipl_availability.json`, the reviewed retirements (with evidence) behind `retired` / `retired_scope`.

It writes `data/curated/player_master.json` (what the exporter reads) and
`data/curated/player_master_review.json` (every disagreement between sources, for a human to settle
in the overrides file). Nothing here writes to the DuckDB file.
"""

from __future__ import annotations

import datetime as _dt
import json
from collections import Counter
from typing import Any

import duckdb
from loguru import logger

from cricdex import leagues
from cricdex.common.sql import MAIN_INNINGS, player_ids, table_suffix
from cricdex.config import CURATED_DIR, DATA_DIR
from cricdex.scout.identity import countries, names, sources
from cricdex.scout.identity import taxonomy as taxonomy_schema
from cricdex.scout.identity.sources import read_json, write_json

DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
MASTER_PATH = CURATED_DIR / "player_master.json"
REVIEW_PATH = CURATED_DIR / "player_master_review.json"
OVERRIDES_PATH = CURATED_DIR / "player_overrides.json"
TAXONOMY_PATH = CURATED_DIR / "player_taxonomy.json"
LEGACY_WIKIDATA = CURATED_DIR / "wikidata_enrichment.json"

# "Active" = played a match in any registry league (or a men's international) within this many
# months of the newest match in the data.
ACTIVE_MONTHS = 18

ROLES = ("batter", "bowler", "allrounder", "wk_batter")
STYLES = tuple(sources.STYLE_CATEGORY)

# Data-driven role thresholds (pooled over every exported T20 league, main innings only).
MIN_MATCHES_FOR_DATA_ROLE = 12  # below this the ball data is too thin to overrule anyone
THIN_MATCHES = 3  # ...but a short career still beats no role at all, as a last resort
REGULAR_BOWLER_OVERS = 1.8  # overs per match appeared, to count as a regular bowler
REGULAR_BOWLER_SHARE = 0.5  # ...bowling in at least this share of matches
PART_TIME_OVERS = 0.6  # under this a player effectively doesn't bowl
REAL_BATTER_POS = 7.0  # mean batting position at or above (numerically below) this
REAL_BATTER_BF = 7.0  # ...and balls faced per match appeared
KEEPER_STUMPINGS = 2  # stumpings in the recent window (RECENT_YEARS) that make a keeper
# A source's keeper claim (Wikipedia / LLM) stands for a player the data can't see keeping, unless
# the recent data has this many T20 matches without one stumping: a keeper stumps someone about
# every 14 matches (the median of the 163 keepers with 20+ recent T20 matches, 2026-10-27), so 40
# matches without one would happen to a real keeper about 6% of the time (exp(-40 / 14)).
KEEPER_UNSEEN_MATCHES = 40
# Batting slot, keeper and the Keep page's death / spin tags read the recent window, not the whole
# career: a role changes (Kohli opens since 2023; Duckett last kept in 2018).
RECENT_YEARS = 3
OPENER_INNINGS = 30  # the last this-many T20 innings (within RECENT_YEARS) set the batting slot
OPENER_MIN_INNINGS = 8  # ...when he has at least this many; below it the LLM taxonomy decides
OPENER_SHARE = 0.5  # an opener walks out at 1 or 2 in at least this share of them
DOB_MIN_DEBUT_AGE = 13  # a source birth date younger than this at debut is a namesake / typo
DOB_MAX_PLAYING_AGE = 55  # ...or older than this at his last match
DOB_LATE_DEBUT_AGE = 38  # a first match in the data at this age or older is logged for review


def _age_years(dob: str | None, on: str | None) -> float | None:
    try:
        return (_dt.date.fromisoformat(on[:10]) - _dt.date.fromisoformat(dob[:10])).days / 365.25
    except (TypeError, ValueError):
        return None


def _pick_dob(
    cid: str,
    scorecard: str,
    ov: dict,
    w: dict,
    ib: dict,
    legacy: dict,
    first_m: str | None,
    last: str | None,
    review: dict,
    title: str | None = None,
) -> tuple[str | None, str | None]:
    """(date of birth, its source). Order: a reviewed override, the English Wikipedia infobox, Wikidata
    (a single day-precision date), the legacy Wikidata enrichment.

    The infobox comes before Wikidata since 2026-10-26 (ROADMAP I17e). The two agree for 93% of
    the players that have both (4,024 of 4,327). Where they differed, seven IPL players checked
    against their iplt20.com profiles and other published profiles had the infobox's date every
    time (Mukesh Choudhary 1996, Wikidata 1986; Venkatesh Iyer 1994, Wikidata 1990; Deepak Chahar
    1992, Wikidata 1972; Jaydev Unadkat, Jacob Duffy, Kuldeep Sen, Gulbadin Naib). Until this
    change Wikidata's dates were also read without their precision, so a year-only date became
    1 January. A disagreement is logged in the review (`dob_disagree`).

    A source date that makes him implausibly young at debut or old at his last match (an id match
    on a namesake) is skipped for the next source and logged; so is one whose year isn't the year
    the linked article's title gives ("(cricketer, born 1983)"). A kept date that makes his first
    match in the data a debut at DOB_LATE_DEBUT_AGE or older is logged (`dob_late_debut`): often a
    namesake's article."""
    cands: list[tuple[str, str]] = []
    if ov.get("dob"):
        return str(ov["dob"]), "override"
    if ib.get("dob"):
        cands.append((ib["dob"], "wikipedia"))
    if w.get("dob"):
        cands.append((w["dob"], "wikidata"))
    if legacy.get("_status") == "ok" and legacy.get("dob"):
        cands.append((legacy["dob"], "wikidata"))
    if ib.get("dob") and (w.get("dob") or w.get("dob_all")) and w.get("dob") != ib["dob"]:
        review.setdefault("dob_disagree", []).append(
            {"cricsheet_id": cid, "scorecard": scorecard, "wikipedia": ib["dob"],
             "wikidata": w.get("dob") or w.get("dob_all"), "kept": "wikipedia"}
        )  # fmt: skip
    import re

    born = re.search(r"\bborn (\d{4})\)", title or "")
    for dob, src in cands:
        age_first = _age_years(dob, first_m)
        age_last = _age_years(dob, last)
        if (
            (age_first is not None and age_first < DOB_MIN_DEBUT_AGE)
            or (age_last is not None and age_last > DOB_MAX_PLAYING_AGE)
            or (born and str(dob)[:4] != born.group(1))
        ):
            review["dob"].append(
                {
                    "cricsheet_id": cid,
                    "scorecard": scorecard,
                    "dob": dob,
                    "source": src,
                    "first_match": first_m,
                    "last_match": last,
                    "issue": "implausible age at debut or last match — skipped; add the right "
                    "`dob` to player_overrides.json if no other source has it",
                }
            )
            continue
        if age_first is not None and age_first >= DOB_LATE_DEBUT_AGE:
            review.setdefault("dob_late_debut", []).append(
                {"cricsheet_id": cid, "scorecard": scorecard, "dob": dob, "source": src,
                 "title": title, "first_match": first_m, "age_at_first_match": round(age_first, 1),
                 "issue": "first match in the data at this age: check the linked article is him"}
            )  # fmt: skip
        return dob, src
    return None, None


IDENTITY_FIELDS = (
    "display_name",
    "full_name",
    "aliases",
    "capped",
    "active",
    "retired",
    "country",
    "team",
    "batting_hand",
    "bowling_arm",
    "bowling_category",
    "bowling_style",
    "primary_role",
)


# ---- read-only gathering from the DB ------------------------------------------------------------


def exported_collections(con: duckdb.DuckDBPyConnection) -> list[str]:
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    return [k for k in leagues.exported_keys() if f"balls_{table_suffix(k)}" in have]


def gather_appearances(con: duckdb.DuckDBPyConnection, cols: list[str]) -> dict[str, dict]:
    """cid → {names: {col: name}, leagues: {col: {first, last, matches}}} from each league's XIs
    (falling back to the ball data where a league has no XI table)."""
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    out: dict[str, dict] = {}
    for col in cols:
        safe = table_suffix(col)
        if f"match_players_{safe}" in have and f"matches_{safe}" in have:
            rows = con.execute(
                f"""
                SELECT p.identifier, MODE(p.name), MIN(m.match_date), MAX(m.match_date),
                       COUNT(DISTINCT p.match_id)
                FROM match_players_{safe} p JOIN matches_{safe} m USING (match_id)
                WHERE p.identifier IS NOT NULL GROUP BY 1
                """
            ).fetchall()
        else:
            rows = []
        # anyone in the ball data the XI table missed (older ingests)
        ids = player_ids(con, col)
        if ids:
            extra = con.execute(
                f"""
                SELECT i.identifier, MODE(x.nm), MIN(x.match_date), MAX(x.match_date),
                       COUNT(DISTINCT x.match_id)
                FROM (SELECT batter nm, match_id, match_date FROM balls_{safe}
                      UNION ALL SELECT bowler, match_id, match_date FROM balls_{safe}
                      UNION ALL SELECT non_striker, match_id, match_date FROM balls_{safe}) x
                JOIN {ids} i ON i.name = x.nm
                GROUP BY 1
                """
            ).fetchall()
            seen = {r[0] for r in rows}
            rows += [r for r in extra if r[0] not in seen]
        for cid, nm, first, last, n in rows:
            rec = out.setdefault(cid, {"names": {}, "leagues": {}})
            rec["names"][col] = nm
            rec["leagues"][col] = {
                "first": str(first)[:10] if first else None,
                "last": str(last)[:10] if last else None,
                "matches": int(n or 0),
            }
    return out


def gather_ball_stats(con: duckdb.DuckDBPyConnection, cols: list[str]) -> dict[str, dict]:
    """Per player, pooled over every exported league (a match counted once even when two
    collections carry it): XI matches, balls faced, innings at the crease, mean batting position,
    legal balls bowled, matches bowled in, stumpings."""
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    parts: list[str] = []
    for col in cols:
        safe = table_suffix(col)
        ids = player_ids(con, col)
        if not ids:
            continue
        b = f"(SELECT * FROM balls_{safe} WHERE {MAIN_INNINGS})"
        parts.append(
            f"""
            SELECT i.identifier cid, b.match_id, 'bf' k,
                   COUNT(*) FILTER (WHERE COALESCE(b.extras_type,'') <> 'wides') v
            FROM {b} b JOIN {ids} i ON i.name = b.batter GROUP BY 1, 2
            UNION ALL
            SELECT i.identifier, b.match_id, 'bb',
                   COUNT(*) FILTER (WHERE COALESCE(b.extras_type,'') NOT IN ('wides','noballs'))
            FROM {b} b JOIN {ids} i ON i.name = b.bowler GROUP BY 1, 2
            UNION ALL
            SELECT i.identifier, e.match_id, 'pos', MIN(e.pos)
            FROM (
                SELECT match_id, nm,
                       ROW_NUMBER() OVER (PARTITION BY match_id, innings_idx ORDER BY s, nm) pos
                FROM (
                    SELECT match_id, innings_idx, nm, MIN(seq) s FROM (
                        SELECT match_id, innings_idx, batter nm, "over" * 100 + ball_in_over seq
                        FROM {b}
                        UNION ALL
                        SELECT match_id, innings_idx, non_striker, "over" * 100 + ball_in_over
                        FROM {b} WHERE non_striker IS NOT NULL
                    ) GROUP BY ALL
                )
            ) e JOIN {ids} i ON i.name = e.nm GROUP BY 1, 2
            """
        )
        if f"wickets_{safe}" in have:
            parts.append(
                f"""
                SELECT i.identifier, w.match_id, 'st', COUNT(*)
                FROM wickets_{safe} w JOIN {ids} i ON i.name = w.fielders[1]
                WHERE w.wicket_kind = 'stumped' AND len(w.fielders) > 0 GROUP BY 1, 2
                """
            )
        if f"match_players_{safe}" in have:
            parts.append(
                f"SELECT identifier, match_id, 'xi', 1 FROM match_players_{safe} "
                "WHERE identifier IS NOT NULL"
            )
    if not parts:
        return {}
    rows = con.execute(
        f"""
        WITH x AS (
            SELECT cid, match_id, k, MAX(v) v FROM ({" UNION ALL ".join(parts)}) GROUP BY ALL
        )
        SELECT cid,
               COUNT(DISTINCT match_id) AS m_any,
               COUNT(*) FILTER (WHERE k = 'xi') AS m_xi,
               COALESCE(SUM(v) FILTER (WHERE k = 'bf'), 0) AS bf,
               COUNT(*) FILTER (WHERE k = 'pos') AS bat_inns,
               AVG(v) FILTER (WHERE k = 'pos') AS mean_pos,
               COALESCE(SUM(v) FILTER (WHERE k = 'bb'), 0) AS bb,
               COUNT(*) FILTER (WHERE k = 'bb' AND v > 0) AS bowl_m,
               COALESCE(SUM(v) FILTER (WHERE k = 'st'), 0) AS stumpings
        FROM x GROUP BY cid
        """
    ).fetchall()
    out = {}
    for cid, m_any, m_xi, bf, inns, pos, bb, bowl_m, st in rows:
        m = max(int(m_xi or 0), int(m_any or 0))
        out[cid] = {
            "matches": m,
            "balls_faced": int(bf),
            "bat_innings": int(inns),
            "mean_bat_pos": round(float(pos), 2) if pos is not None else None,
            "balls_bowled": int(bb),
            "bowl_matches": int(bowl_m),
            "stumpings": int(st),
        }
    return out


def recent_since(asof: str | None, years: int = RECENT_YEARS) -> str:
    """The first day of the recent window: `years` before the data's as-of date."""
    d = _dt.date.fromisoformat(asof[:10]) if asof else _dt.date.today()
    try:
        return d.replace(year=d.year - years).isoformat()
    except ValueError:  # 29 February
        return d.replace(year=d.year - years, day=28).isoformat()


def gather_recent_stats(
    con: duckdb.DuckDBPyConnection, cols: list[str], since: str
) -> dict[str, dict]:
    """Per player, T20 matches only, from `since` on, pooled over every exported league (a match
    counted once): XI matches, legal balls bowled, matches bowled in, stumpings, and his batting
    slot in each innings (1 and 2 open), newest first, at most OPENER_INNINGS of them."""
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    parts: list[str] = []
    for col in cols:
        safe = table_suffix(col)
        ids = player_ids(con, col)
        if not ids:
            continue
        b = (
            f"(SELECT * FROM balls_{safe} WHERE {MAIN_INNINGS} AND match_type = 'T20' "
            f"AND match_date >= '{since}')"
        )
        parts.append(
            f"""
            SELECT i.identifier cid, b.match_id, MIN(b.match_date) d, 'bb' k,
                   COUNT(*) FILTER (WHERE COALESCE(b.extras_type,'') NOT IN ('wides','noballs')) v
            FROM {b} b JOIN {ids} i ON i.name = b.bowler GROUP BY 1, 2
            UNION ALL
            SELECT i.identifier, e.match_id, MIN(e.d), 'pos:{col}', MIN(e.pos)
            FROM (
                SELECT match_id, nm, d,
                       ROW_NUMBER() OVER (PARTITION BY match_id, innings_idx ORDER BY s, nm) pos
                FROM (
                    SELECT match_id, innings_idx, nm, MIN(match_date) d, MIN(seq) s FROM (
                        SELECT match_id, innings_idx, match_date, batter nm,
                               "over" * 100 + ball_in_over seq
                        FROM {b}
                        UNION ALL
                        SELECT match_id, innings_idx, match_date, non_striker,
                               "over" * 100 + ball_in_over
                        FROM {b} WHERE non_striker IS NOT NULL
                    ) GROUP BY ALL
                )
            ) e JOIN {ids} i ON i.name = e.nm GROUP BY 1, 2
            """
        )
        if f"matches_{safe}" in have:
            m = (
                f"(SELECT match_id, match_date FROM matches_{safe} "
                f"WHERE match_type = 'T20' AND match_date >= '{since}')"
            )
            if f"wickets_{safe}" in have:
                parts.append(
                    f"""
                    SELECT i.identifier, w.match_id, MIN(m.match_date), 'st', COUNT(*)
                    FROM wickets_{safe} w JOIN {m} m USING (match_id)
                    JOIN {ids} i ON i.name = w.fielders[1]
                    WHERE w.wicket_kind = 'stumped' AND len(w.fielders) > 0 GROUP BY 1, 2
                    """
                )
            if f"match_players_{safe}" in have:
                parts.append(
                    f"SELECT p.identifier, p.match_id, MIN(m.match_date), 'xi', 1 "
                    f"FROM match_players_{safe} p JOIN {m} m USING (match_id) "
                    "WHERE p.identifier IS NOT NULL GROUP BY 1, 2"
                )
    if not parts:
        return {}
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _recent_x AS
        SELECT cid, match_id, MIN(d) d, k, MAX(v) v
        FROM ({" UNION ALL ".join(parts)}) GROUP BY cid, match_id, k
        """
    )
    rows = con.execute(
        """
        SELECT cid,
               COUNT(DISTINCT match_id) AS m_any,
               COUNT(*) FILTER (WHERE k = 'xi') AS m_xi,
               COALESCE(SUM(v) FILTER (WHERE k = 'bb'), 0) AS bb,
               COUNT(*) FILTER (WHERE k = 'bb' AND v > 0) AS bowl_m,
               COALESCE(SUM(v) FILTER (WHERE k = 'st'), 0) AS st
        FROM (SELECT cid, match_id, k, MAX(v) v FROM _recent_x
              WHERE k IN ('xi', 'bb', 'st') OR k LIKE 'pos:%' GROUP BY ALL)
        GROUP BY cid
        """
    ).fetchall()
    out = {}
    for cid, m_any, m_xi, bb, bowl_m, st in rows:
        out[cid] = {
            "since": since,
            "matches": max(int(m_xi or 0), int(m_any or 0)),
            "balls_bowled": int(bb),
            "bowl_matches": int(bowl_m),
            "stumpings": int(st),
            "bat_slots": [],
            "league_slots": {},
        }
    # batting slots, newest first: pooled (a match two collections carry counted once) and per
    # league (a league where he has OPENER_MIN_INNINGS of them)
    pooled: dict[str, dict[str, tuple]] = {}
    per: dict[tuple[str, str], list[tuple]] = {}
    for cid, mid, d, k, v in con.execute(
        "SELECT cid, match_id, d, k, v FROM _recent_x WHERE k LIKE 'pos:%'"
    ).fetchall():
        key = (str(d)[:10], str(mid))
        cur = pooled.setdefault(cid, {}).get(mid)
        if cur is None or int(v) < cur[1]:
            pooled[cid][mid] = (key, int(v))
        per.setdefault((cid, k[4:]), []).append((key, int(v)))
    for cid, ms in pooled.items():
        rec = out.setdefault(cid, {"since": since, "matches": 0, "balls_bowled": 0,
                                   "bowl_matches": 0, "stumpings": 0, "bat_slots": [],
                                   "league_slots": {}})  # fmt: skip
        rec["bat_slots"] = [p for _, p in sorted(ms.values(), reverse=True)][:OPENER_INNINGS]
    for (cid, col), xs in per.items():
        if len(xs) >= OPENER_MIN_INNINGS:
            out[cid]["league_slots"][col] = [p for _, p in sorted(xs, reverse=True)][
                :OPENER_INNINGS
            ]
    con.execute("DROP TABLE IF EXISTS _recent_x")
    return out


def _opener_share(recent: dict | None) -> float | None:
    slots = (recent or {}).get("bat_slots") or []
    return round(sum(1 for s in slots if s <= 2) / len(slots), 3) if slots else None


def batting_slot(recent: dict | None, llm_slot: str | None) -> tuple[str | None, str]:
    """(batting position, its source). From the last OPENER_INNINGS T20 innings of the recent
    window when he has OPENER_MIN_INNINGS of them: "opener" when he walked out at 1 or 2 in at least
    OPENER_SHARE of them; otherwise the LLM taxonomy's slot, unless that says "opener" (or is
    missing), when his median slot gives no3 / middle (4-5) / finisher (6-7) / lower (8) /
    tailender (9+). With fewer innings, the LLM taxonomy's slot. He is also an opener when he opened
    in OPENER_SHARE of his last innings in any one league with OPENER_MIN_INNINGS of them
    (`league_slots`)."""
    slots = (recent or {}).get("bat_slots") or []
    llm = llm_slot if llm_slot not in (None, "unknown") else None
    if len(slots) < OPENER_MIN_INNINGS:
        return llm, "llm" if llm else "none"

    def opens(xs: list[int]) -> bool:
        return (
            len(xs) >= OPENER_MIN_INNINGS and sum(1 for s in xs if s <= 2) / len(xs) >= OPENER_SHARE
        )

    # pooled over every T20 league, or in any one league he plays regularly (Narine opens for KKR
    # but bats lower in the other leagues)
    if opens(slots) or any(opens(xs) for xs in ((recent or {}).get("league_slots") or {}).values()):
        return "opener", "ball_data"
    if llm and llm != "opener":
        return llm, "llm"
    med = sorted(slots)[len(slots) // 2]
    band = (
        "no3"
        if med <= 3
        else "middle"
        if med <= 5
        else "finisher"
        if med <= 7
        else "lower"
        if med <= 8
        else "tailender"
    )
    return band, "ball_data"


def cricinfo_search_set(
    apps: dict[str, dict], cids: set[str], squad_keys: set[str], asof: str | None
) -> set[str]:
    """The players worth a Wikipedia search by ESPNcricinfo id: every IPL player, every squad row
    with an id, and the players active (ACTIVE_MONTHS) in an auction-pool league or a T20I."""
    pool = {lg.key for lg in leagues.auction_pool()} | {"t20s_male"}
    asof_d = _dt.date.fromisoformat(asof) if asof else _dt.date.today()
    cut = (asof_d - _dt.timedelta(days=int(ACTIVE_MONTHS * 30.44))).isoformat()
    out = {c for c in squad_keys if c in cids}
    for cid in cids:
        lg = apps[cid]["leagues"]
        if "ipl" in lg or any(k in pool and (v.get("last") or "") >= cut for k, v in lg.items()):
            out.add(cid)
    return out


def gather_register(con: duckdb.DuckDBPyConnection, cids: set[str]) -> dict[str, dict]:
    """cid → {name, unique_name, cricinfo_ids, variants} from the People Register."""
    cols = {r[0] for r in con.execute("DESCRIBE people").fetchall()}
    keys = [c for c in ("key_cricinfo", "key_cricinfo_2", "key_cricinfo_3") if c in cols]
    sel = ", ".join(f"CAST({k} AS VARCHAR)" for k in keys) or "NULL"
    out: dict[str, dict] = {}
    for row in con.execute(f"SELECT identifier, name, unique_name, {sel} FROM people").fetchall():
        cid = row[0]
        if cid not in cids:
            continue
        out[cid] = {
            "name": row[1],
            "unique_name": row[2],
            "cricinfo_ids": [str(v).removesuffix(".0") for v in row[3:] if v],
            "variants": [],
        }
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "people_names" in have:
        for cid, nm in con.execute("SELECT identifier, name FROM people_names").fetchall():
            if cid in out and nm and nm not in out[cid]["variants"]:
                out[cid]["variants"].append(nm)
    return out


def data_as_of(con: duckdb.DuckDBPyConnection, cols: list[str]) -> str | None:
    best = None
    for col in cols:
        d = con.execute(f"SELECT MAX(match_date) FROM balls_{table_suffix(col)}").fetchone()[0]
        if d and (best is None or str(d)[:10] > best):
            best = str(d)[:10]
    return best


# ---- role / style reconciliation ----------------------------------------------------------------


def data_role(
    st: dict | None, min_matches: int = MIN_MATCHES_FOR_DATA_ROLE
) -> tuple[str | None, str]:
    """A role from the ball data alone, with a short reason. None when the evidence is ambiguous
    (a part-time bowler between the thresholds) or too thin. A keeper needs KEEPER_STUMPINGS in the
    recent window (`recent_stumpings`, set by `build`; the career count when it's absent): a
    career count kept tagging players who last kept years ago."""
    if not st or st["matches"] < min_matches:
        return None, "too few matches"
    m = st["matches"]
    overs_pm = st["balls_bowled"] / 6 / m
    share = st["bowl_matches"] / m
    bf_pm = st["balls_faced"] / m
    pos = st["mean_bat_pos"] or 11.0
    regular = overs_pm >= REGULAR_BOWLER_OVERS and share >= REGULAR_BOWLER_SHARE
    real_bat = pos <= REAL_BATTER_POS and bf_pm >= REAL_BATTER_BF
    why = f"{overs_pm:.1f} ov/m, bowls in {share:.0%}, bats #{pos:.1f}, {bf_pm:.1f} bf/m"
    stumpings = st.get("recent_stumpings", st["stumpings"])
    if stumpings >= KEEPER_STUMPINGS and not regular:
        return "wk_batter", f"{stumpings} recent stumpings; {why}"
    if regular and real_bat:
        return "allrounder", why
    if regular:
        return "bowler", why
    # a part-timer: barely bowls, or bowls an over now and then in a minority of games
    if overs_pm < PART_TIME_OVERS or (overs_pm < 1.0 and share < 0.4):
        return ("batter" if real_bat or bf_pm >= 4 else None), why
    return None, f"ambiguous: {why}"


def _norm_role(r: Any) -> str | None:
    return r if r in ROLES else None


def _norm_style(s: Any) -> str | None:
    return s if s in STYLES else None


def keeper_unseen(recent: dict | None) -> bool:
    """True when the recent data can't rule out that he keeps: fewer than KEEPER_UNSEEN_MATCHES
    recent T20 matches, or a stumping among them (no recent data: True)."""
    if not recent:
        return True
    return recent.get("stumpings", 0) > 0 or recent.get("matches", 0) < KEEPER_UNSEEN_MATCHES


def resolve_role(
    tax: dict,
    wiki_role: str | None,
    d_role: str | None,
    thin_role: str | None = None,
    recent: dict | None = None,
) -> tuple[str | None, str]:
    """Final primary role and its source. Order: ball data when it is decisive, then the
    Wikipedia infobox, then the LLM taxonomy, then the ball data of a short career (`thin_role`).
    A keeper the data can't see (no stumpings yet) keeps a keeper tag from Wikipedia or the LLM
    when the data says batter, unless his recent data (`recent`, from `gather_recent_stats`) has
    KEEPER_UNSEEN_MATCHES T20 matches without a stumping (`keeper_unseen`)."""
    llm_role = _norm_role(tax.get("primary_role"))
    if not keeper_unseen(recent):
        # the data has seen him play long enough to have stumped someone if he kept: a keeper
        # claim from a source is out of date (or never was right)
        wiki_role = None if wiki_role == "wk_batter" else wiki_role
        llm_role = None if llm_role == "wk_batter" else llm_role
    if d_role:
        if d_role == "batter" and "wk_batter" in (wiki_role, llm_role):
            return "wk_batter", "wikipedia" if wiki_role == "wk_batter" else "llm"
        return d_role, "ball_data"
    if wiki_role:
        return wiki_role, "wikipedia"
    if llm_role:
        return llm_role, "llm"
    if thin_role:
        return thin_role, "ball_data_thin"
    return None, "none"


def _wd_country(wd: dict) -> str | None:
    for lab in wd.get("sport_country") or []:
        c = countries.normalise(lab)
        if c:
            return c
    for iso in wd.get("sport_country_iso") or []:
        c = countries.normalise(iso)
        if c:
            return c
    return None


# ---- build --------------------------------------------------------------------------------------


def initial_key(name: str) -> str | None:
    """ "Digvesh Rathi" / "DS Rathi" / "D Rathi" → "d rathi": first initial + surname, for matching a
    page's full name to a scorecard name."""
    toks = [t for t in name.replace(".", " ").split() if t]
    if len(toks) < 2:
        return None
    return f"{toks[0][0].lower()} {toks[-1].lower()}"


def _squad_index(
    squads: dict,
    title_to_cid: dict[str, str],
    name_to_cid: dict[str, str],
    initials_to_cid: dict[str, str] | None = None,
):
    """{cid: (team, status)} for the current IPL squads, matched by Wikipedia title first, then by
    the name shown on the page. Unmatched rows are returned for the review file."""
    teams: dict[str, dict] = {}
    unmatched: list[dict] = []
    for code, rows in (squads.get("squads") or {}).items():
        for p in rows:
            cid = p.get("cricsheet_id") or title_to_cid.get(p.get("wiki_title") or "")
            cid = cid or name_to_cid.get((p.get("name") or "").lower())
            if not cid and initials_to_cid:
                cid = initials_to_cid.get(initial_key(p.get("name") or "") or "")
            if not cid:
                unmatched.append({"team": code, **p})
                continue
            withdrawn = p.get("withdrawn")
            released = isinstance(withdrawn, str) and (
                "release" in withdrawn.lower() or "bcci" in withdrawn.lower()
            )
            if released:
                continue
            # a replacement signing doesn't displace an earlier entry for the same player
            teams.setdefault(
                cid,
                {
                    "team": code,
                    "status": p.get("status"),
                    "withdrawn": withdrawn,
                    "page_name": p.get("name"),
                },
            )
    return teams, unmatched


def build(
    *,
    fetch: bool = True,
    force: bool = False,
    llm_names: bool = True,
    llm_limit: int = 0,
    db_path=DB_PATH,
) -> dict[str, Any]:
    """Assemble the master and the review file. `fetch=False` uses only what is cached on disk."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        cols = exported_collections(con)
        asof = data_as_of(con, cols)
        apps = gather_appearances(con, cols)
        stats = gather_ball_stats(con, cols)
        recent = gather_recent_stats(con, cols, recent_since(asof))
        cids = set(apps)
        register = gather_register(con, cids)
        if fetch:
            caps = sources.build_caps(con, cids, force=force)
        else:
            caps = sources.load_caps()
    logger.info(f"master: {len(cids)} players across {len(cols)} exported leagues, as of {asof}")

    wd: dict[str, dict] = {}
    if fetch:
        wd = sources.fetch_wikidata(
            {cid: register.get(cid, {}).get("cricinfo_ids", []) for cid in cids}, force=force
        )
    else:
        wd = read_json(sources.WIKIDATA_CACHE, {})
    squads = (
        sources.fetch_ipl_personnel(force=force) if fetch else read_json(sources.IPL_SQUADS, {})
    )
    titles = {cid: r["enwiki"] for cid, r in wd.items() if cid in cids and r.get("enwiki")}
    # a squad player Wikidata can't find by his ESPNcricinfo id (a debutant whose item lacks it, or
    # who has no item yet) still has the article the IPL personnel page links: read its infobox
    # (keyed by his Cricsheet id, or `wiki:<title>` for a player with no match data)
    # a player whose Wikidata item lacks his ESPNcricinfo id: the cricketer article that links his
    # ESPNcricinfo profile (Wikipedia search, cached), for the players an IPL auction can reach
    # (IPL players, today's squads, and the active players of the auction-pool leagues and T20Is)
    squad_titles = sources.squad_titles(squads)
    by_ci = sources.find_titles_by_cricinfo(
        {cid: register.get(cid, {}).get("cricinfo_ids", []) for cid in cricinfo_search_set(
            apps, cids, set(squad_titles), asof) if cid not in titles},
        fetch=fetch,
    )  # fmt: skip
    for cid, r in by_ci.items():
        if cid in cids and cid not in titles and r.get("title"):
            titles[cid] = r["title"]
    for key, t in squad_titles.items():
        if key.startswith("wiki:") or (key in cids and key not in titles):
            titles[key] = t
    infobox = (
        sources.fetch_infoboxes(titles, force=force)
        if fetch
        else read_json(sources.INFOBOX_CACHE, {})
    )
    taxonomy = taxonomy_schema.load_taxonomy(TAXONOMY_PATH)  # LLM output: allow-lists checked
    overrides = {k: v for k, v in read_json(OVERRIDES_PATH, {}).items() if not k.startswith("_")}
    legacy = read_json(LEGACY_WIKIDATA, {})

    # ---- names: candidates, then the LLM check
    cand: dict[str, tuple[str, str]] = {}
    known: dict[str, list[str]] = {}
    scorecard: dict[str, str] = {}
    for cid in cids:
        reg = register.get(cid, {})
        rec = apps[cid]
        sc = rec["names"].get("ipl") or next(iter(rec["names"].values()))
        scorecard[cid] = sc
        w = wd.get(cid, {}) if wd.get(cid, {}).get("_status") == "ok" else {}
        variants = [*reg.get("variants", []), reg.get("name") or "", *rec["names"].values()]
        cand[cid] = names.candidate(sc, w.get("label"), variants)
        known[cid] = sorted(
            {v for v in [*variants, *(w.get("alias") or []), w.get("label") or ""] if v}
        )
    # squads: title → cid via Wikidata's article link; names via display candidates / variants
    title_to_cid = {r["enwiki"]: cid for cid, r in wd.items() if r.get("enwiki") and cid in cids}
    for cid, ib in infobox.items():
        if cid in cids:
            for t in (ib.get("_title"), ib.get("_page")):
                if t:
                    title_to_cid.setdefault(t, cid)
    ipl_cids = {cid for cid in cids if "ipl" in apps[cid]["leagues"]}
    name_to_cid: dict[str, str] = {}
    amb: set[str] = set()
    for cid in sorted(cids, key=lambda c: (c not in ipl_cids, c)):
        for n in {cand[cid][0], *known[cid]}:
            k = n.lower()
            if k in name_to_cid and name_to_cid[k] != cid:
                if (name_to_cid[k] in ipl_cids) == (cid in ipl_cids):
                    amb.add(k)
                continue
            name_to_cid[k] = cid
    for k in amb:
        name_to_cid.pop(k, None)
    for cid, ov in overrides.items():
        if ov.get("display_name") and cid in cids:
            name_to_cid.setdefault(ov["display_name"].lower(), cid)
    # last resort for a debutant with no Wikidata item: first initial + surname among the players
    # of the last two IPL seasons, when exactly one matches
    recent_cut = f"{int((asof or '2000')[:4]) - 2}-01-01"
    initials_to_cid: dict[str, str] = {}
    clash: set[str] = set()
    for cid in ipl_cids:
        if (apps[cid]["leagues"]["ipl"].get("last") or "") < recent_cut:
            continue
        for n in {scorecard[cid], *known[cid]}:
            k = initial_key(n)
            if not k:
                continue
            if initials_to_cid.get(k, cid) != cid:
                clash.add(k)
            initials_to_cid.setdefault(k, cid)
    for k in clash:
        initials_to_cid.pop(k, None)
    squad_of, squad_unmatched = _squad_index(squads, title_to_cid, name_to_cid, initials_to_cid)
    # a squad page names each IPL player as Wikipedia does: for a player Wikidata doesn't know (a
    # debutant), that page name is a better candidate than a register variant or scorecard initials
    for cid, sq in squad_of.items():
        if (
            cand[cid][1] != "wikidata"
            and sq.get("page_name")
            and names.is_full_words(sq["page_name"])
        ):
            cand[cid] = (names.clean_label(sq["page_name"]) or sq["page_name"], "wikipedia")
            known[cid] = sorted({*known[cid], sq["page_name"]})
    llm_cache = taxonomy_schema.load_names(names.LLM_NAMES_CACHE)
    if llm_names:
        # most-capped / most-played first, so a partial run covers the players people look up
        order = sorted(cids, key=lambda c: -(stats.get(c, {}).get("matches") or 0))
        todo = [
            {
                "id": cid,
                "candidate": cand[cid][0],
                "scorecard": scorecard[cid],
                "known_names": [n for n in known[cid] if n != cand[cid][0]],
                "country": countries.normalise((taxonomy.get(cid) or {}).get("country")),
            }
            for cid in order
            if not (overrides.get(cid) or {}).get("display_name")
        ]
        llm_cache = names.verify_with_llm(todo, limit=llm_limit)

    from cricdex.competitions import load_availability

    availability = load_availability("ipl")
    retired_ipl = {}
    for r in squads.get("retired") or []:
        cid = title_to_cid.get(r.get("wiki_title") or "") or name_to_cid.get(
            (r.get("name") or "").lower()
        )
        if cid:
            retired_ipl[cid] = r

    asof_d = _dt.date.fromisoformat(asof) if asof else _dt.date.today()
    active_cutoff = (asof_d - _dt.timedelta(days=int(ACTIVE_MONTHS * 30.44))).isoformat()

    master: dict[str, dict] = {}
    review: dict[str, list] = {
        "role": [],
        "bowling_style": [],
        "batting_hand": [],
        "country": [],
        "names": [],
        "dob": [],
        "dob_disagree": [],
        "dob_late_debut": [],
        "squads_unmatched": squad_unmatched,
        "todo": [],
    }
    counts: Counter = Counter()
    for cid in sorted(cids):
        reg = register.get(cid, {})
        rec = apps[cid]
        st = stats.get(cid)
        w = wd.get(cid, {}) if wd.get(cid, {}).get("_status") == "ok" else {}
        ib = infobox.get(cid, {}) if cid in titles else {}
        tax = taxonomy.get(cid) or {}
        ov = overrides.get(cid) or {}
        cap = caps.get(cid)

        # names
        nm = names.resolve(
            cid, scorecard[cid], *cand[cid], known[cid], llm_cache, ov.get("display_name")
        )
        counts[f"name:{nm['name_source']}"] += 1
        counts[f"check:{nm['name_check']}"] += 1
        if nm["name_check"] in ("llm_rejected", "llm_corrected"):
            review["names"].append({"cricsheet_id": cid, "scorecard": scorecard[cid], **nm})
        full = (
            ov.get("full_name")
            or ib.get("full_name")
            or w.get("birth_name")
            or names.longest_full_name([*reg.get("variants", []), reg.get("name") or ""])
            or nm["display_name"]
        )
        aliases = sorted(
            {
                a.strip()
                for a in [
                    *known[cid],
                    nm["display_name"],
                    full,
                    reg.get("unique_name") or "",
                    ib.get("name") or "",
                    *(ov.get("aliases") or []),
                ]
                if a and a.strip()
            },
            key=lambda s: (s.lower(), s),
        )

        # role (keeper evidence and batting slot from the recent window)
        rc = recent.get(cid)
        if st:
            st = {**st, "recent_stumpings": (rc or {}).get("stumpings", 0)}
        wiki_role = sources.parse_role(ib.get("role"))
        d_role, d_why = data_role(st)
        thin_role = data_role(st, min_matches=THIN_MATCHES)[0] if not d_role else None
        role, role_src = resolve_role(tax, wiki_role, d_role, thin_role, rc)
        bat_slot, bat_slot_src = batting_slot(rc, tax.get("batting_position"))
        if ov.get("primary_role"):
            role, role_src = ov["primary_role"], "override"
        llm_role = _norm_role(tax.get("primary_role"))
        if llm_role and role and llm_role != role:
            counts["role_changed"] += 1
        opinions = {"llm": llm_role, "wikipedia": wiki_role, "ball_data": d_role}
        if len({v for v in opinions.values() if v}) > 1:
            review["role"].append(
                {
                    "cricsheet_id": cid,
                    "name": nm["display_name"],
                    "final": role,
                    "source": role_src,
                    **opinions,
                    "ball_data_note": d_why,
                }
            )

        # bowling style / arm / category
        wiki_style = sources.parse_bowling_style(ib.get("bowling"))
        llm_style = _norm_style(tax.get("bowling_style"))
        style = ov.get("bowling_style") or wiki_style or llm_style
        style_src = (
            "override"
            if ov.get("bowling_style")
            else ("wikipedia" if wiki_style else ("llm" if llm_style else "none"))
        )
        cat = sources.STYLE_CATEGORY.get(style) if style else None
        if not style and tax.get("bowling_category") in ("seam", "spin"):
            cat = tax["bowling_category"]
        if wiki_style and llm_style and wiki_style != llm_style:
            counts["style_changed"] += 1
            review["bowling_style"].append(
                {
                    "cricsheet_id": cid,
                    "name": nm["display_name"],
                    "final": style,
                    "wikipedia": wiki_style,
                    "wikipedia_text": ib.get("bowling"),
                    "llm": llm_style,
                    "category_changed": sources.STYLE_CATEGORY[wiki_style]
                    != sources.STYLE_CATEGORY[llm_style],
                }
            )
        arm = sources.STYLE_ARM.get(style) if style else None

        # batting hand
        wiki_hand = sources.parse_batting_hand(ib.get("batting"))
        wd_hand = None
        for h in w.get("hand") or []:
            wd_hand = sources.parse_batting_hand(h.replace("handedness", "handed"))
            if wd_hand:
                break
        llm_hand = tax.get("batting_hand") if tax.get("batting_hand") in ("left", "right") else None
        hand = ov.get("batting_hand") or wiki_hand or wd_hand or llm_hand
        if wiki_hand and llm_hand and wiki_hand != llm_hand:
            review["batting_hand"].append(
                {
                    "cricsheet_id": cid,
                    "name": nm["display_name"],
                    "wikipedia": wiki_hand,
                    "llm": llm_hand,
                }
            )

        # country: override > latest international side > Wikidata > Wikipedia infobox > the
        # linked article's title ("(Trinidad and Tobago cricketer)") > LLM. The LLM never wins over
        # a linked article that names a nation.
        intl = countries.team_country(cap.get("team")) if cap else None
        wd_c = _wd_country(w)
        ib_c = countries.normalise(ib.get("country")) or countries.title_country(
            ib.get("_page") or ib.get("_title") or w.get("enwiki")
        )
        llm_c = tax.get("country")  # already a canonical code (taxonomy.load_taxonomy)
        country = ov.get("country") or intl or wd_c or ib_c or llm_c
        country = countries.normalise(country)
        c_ops = {"international": intl, "wikidata": wd_c, "wikipedia": ib_c, "llm": llm_c}
        if len({v for v in c_ops.values() if v}) > 1:
            review["country"].append(
                {"cricsheet_id": cid, "name": nm["display_name"], "final": country, **c_ops}
            )

        # activity, retirement, squad
        lasts = [lg["last"] for lg in rec["leagues"].values() if lg.get("last")]
        if cap and cap.get("last"):
            lasts.append(cap["last"])
        last = max(lasts) if lasts else None
        firsts = [lg["first"] for lg in rec["leagues"].values() if lg.get("first")]
        # retirements: the reviewed availability file (data/curated/ipl_availability.json), or an
        # override's own `retired` flag
        av = availability.get(cid) or {}
        retired = bool(ov.get("retired")) or av.get("status") == "retired"
        retired_scope = (ov.get("retired_scope") or av.get("scope")) if retired else None
        if not retired and cid in retired_ipl:
            review["todo"].append(
                {
                    "cricsheet_id": cid,
                    "name": nm["display_name"],
                    "issue": "listed as retired from the IPL on the Wikipedia personnel page but "
                    "not in ipl_availability.json — verify and add a `retired` record with evidence",
                    "evidence": retired_ipl[cid],
                }
            )
        sq = squad_of.get(cid)
        team = None if retired else (sq or {}).get("team")
        if "team" in ov:
            team = ov["team"]

        dob, dob_src = _pick_dob(
            cid, scorecard[cid], ov, w, ib, legacy.get(cid) or {},
            min(firsts) if firsts else None, last, review, titles.get(cid),
        )  # fmt: skip

        master[cid] = {
            "cricsheet_id": cid,
            "display_name": nm["display_name"],
            "full_name": full,
            "scorecard_name": scorecard[cid],
            "scorecard_names": dict(sorted(rec["names"].items())),
            "aliases": aliases,
            "name_source": nm["name_source"],
            "name_check": nm["name_check"],
            "capped": bool(cap),
            "first_international": cap.get("first") if cap else None,
            "last_international": cap.get("last") if cap else None,
            "international_formats": cap.get("formats") if cap else {},
            "active": bool(last and last >= active_cutoff)
            and not (retired and retired_scope == "all"),
            "last_match_date": last,
            "first_match_date": min(firsts) if firsts else None,
            "retired": retired,
            "retired_scope": retired_scope,
            "country": country,
            "country_source": next(
                (k for k, v in [("override", ov.get("country")), *c_ops.items()] if v), None
            ),
            "team": team,
            "squad_status": (sq or {}).get("status") if team else None,
            "batting_hand": hand,
            "bowling_arm": arm,
            "bowling_category": cat,
            "bowling_style": style,
            "bowling_style_source": style_src,
            "primary_role": role,
            "role_source": role_src,
            "batting_position": bat_slot,
            "batting_position_source": bat_slot_src,
            "dob": dob,
            "dob_source": dob_src,
            "wikidata_qid": w.get("qid"),
            "wikipedia_title": titles.get(cid),
            "leagues": dict(sorted(rec["leagues"].items())),
            "ball_stats": st or {},
            # T20 only, the last RECENT_YEARS: keeper evidence, batting slot, Keep's spin tag
            "recent_stats": {
                k: v for k, v in (rc or {}).items() if k not in ("bat_slots", "league_slots")
            }  # fmt: skip
            | {
                "slot_innings": len((rc or {}).get("bat_slots") or []),
                "opener_share": _opener_share(rc),
                "league_opener_share": {
                    c: _opener_share({"bat_slots": xs})
                    for c, xs in sorted(((rc or {}).get("league_slots") or {}).items())
                },
            },
        }
        counts["capped"] += bool(cap)
        counts["dob"] += bool(dob)
        counts["retired"] += retired
        counts["in_squad"] += bool(team)
        counts["active"] += master[cid]["active"]
        if cid in ipl_cids:
            counts["ipl_players"] += 1
            counts["ipl_dob"] += bool(dob)

    meta = {
        "_built": _dt.date.today().isoformat(),
        "_built_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "_data_as_of": asof,
        "_active_months": ACTIVE_MONTHS,
        "_sources": [
            "Cricsheet People Register, match registries and XIs (ODC-By)",
            "Cricsheet men's T20I / ODI / Test XIs, for capped (ODC-By)",
            "Wikidata (CC0), by ESPNcricinfo id P2697",
            "English Wikipedia infoboxes (CC BY-SA 4.0)",
            squads.get("_source", "IPL squads: data/curated/ipl_squads_2026.json"),
            "LLM taxonomy and name check (data/curated/player_taxonomy.json, player_names_llm.json)",
            "Reviewed overrides: data/curated/player_overrides.json",
        ],
        "_counts": dict(sorted(counts.items())),
        "_recent_since": recent_since(asof),
        # IPL squad players with no match data (no Cricsheet id): what their own Wikipedia article
        # gives, by the title the personnel page links (`squad_only`)
        "_squad_only": {
            t: {"dob": ib["dob"], "dob_source": "wikipedia"}
            for key, t in sorted(squad_titles.items())
            if key.startswith("wiki:") and (ib := infobox.get(key) or {}).get("dob")
        },
    }
    write_json(MASTER_PATH, {**meta, **master})
    write_json(
        REVIEW_PATH,
        {
            "_note": (
                "Disagreements between sources, for review. Settle a row by adding the right value "
                "to data/curated/player_overrides.json (keyed by cricsheet_id); overrides always win."
            ),
            "_counts": {k: len(v) for k, v in review.items()},
            **review,
        },
    )
    logger.info(f"master: wrote {len(master)} players → {MASTER_PATH}; counts {dict(counts)}")
    return {
        "players": len(master),
        "counts": dict(counts),
        "review": {k: len(v) for k, v in review.items()},
    }


def load(path=MASTER_PATH) -> dict[str, dict]:
    """cid → identity record (empty when the master hasn't been built)."""
    return {k: v for k, v in read_json(path, {}).items() if not k.startswith("_")}


def build_stamp(path=MASTER_PATH) -> dict[str, str | None]:
    """{built, hash} of the master file: its build time and the first 16 hex of its SHA-256 (what
    each league export stamps in meta.json, so mixed builds can be caught)."""
    import hashlib

    if not path.exists():
        return {"built": None, "hash": None}
    raw = path.read_bytes()
    meta = json.loads(raw)
    return {
        "built": meta.get("_built_at") or meta.get("_built"),
        "hash": hashlib.sha256(raw).hexdigest()[:16],
    }


def squad_only(path=MASTER_PATH) -> dict[str, dict]:
    """Wikipedia title → {dob, dob_source} for the IPL squad players with no match data."""
    return read_json(path, {}).get("_squad_only") or {}


def identity_block(rec: dict | None, fallback_name: str | None = None) -> dict[str, Any]:
    """The contract block every surface carries (`IDENTITY_FIELDS`), with safe defaults."""
    rec = rec or {}
    out: dict[str, Any] = {k: rec.get(k) for k in IDENTITY_FIELDS}
    out["display_name"] = out["display_name"] or fallback_name
    out["full_name"] = out["full_name"] or out["display_name"]
    out["aliases"] = list(out["aliases"] or ([fallback_name] if fallback_name else []))
    for flag in ("capped", "active", "retired"):
        out[flag] = bool(out[flag])
    return out
