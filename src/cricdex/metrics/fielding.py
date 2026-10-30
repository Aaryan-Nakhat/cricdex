"""Fielding + wicketkeeping boards from the `fielders` dismissal field.

Cricsheet records the fielder(s) involved in a dismissal in `balls.fielders`
(a VARCHAR[]). We count, per fielder:
  • catches      — wicket_kind = 'caught'   (NB: 'caught and bowled' is a
                   separate kind with an empty fielders array — a bowling
                   wicket — so it's excluded here, correctly)
  • stumpings    — wicket_kind = 'stumped'
  • run-outs     — wicket_kind = 'run out'  (every fielder in the array is
                   credited an involvement; rows with a null/empty array are
                   skipped — incomplete data)

Each dismissal goes on one of two boards, by whether the fielder kept wicket in that innings
(read from the fielding side's XI: see `_tally`):
  • Wicketkeeping — dismissals made while keeping
  • Fielding      — dismissals made in the field (a keeper who played as a fielder counts here)

This is a dismissal *count* (no diving/range/positioning — that needs video).
Keyed by the fielder's registry id (`cricsheet_id`; `fielder` is his scorecard name), tagged with
matches/taxonomy/activity at export time like every other leaderboard.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from cricdex.common.sql import (
    MAIN_INNINGS,
    UNRESOLVED,
    _tables,
    base_suffix,
    keyed_query,
    table_suffix,
)
from cricdex.config import CURATED_DIR, DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
TAXONOMY_PATH = CURATED_DIR / "player_taxonomy.json"


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def _keeper_ids() -> set[str]:
    """Cricsheet ids of the players classified as wicket-keepers: the player master when it is built,
    else the LLM taxonomy (both keyed by id, so a namesake of a keeper isn't one)."""
    from cricdex.scout.identity import master

    ident = master.load()
    if not ident and TAXONOMY_PATH.exists():
        from cricdex.scout.identity.taxonomy import load_taxonomy

        ident = load_taxonomy(TAXONOMY_PATH)  # LLM output: allow-lists checked
    return {
        cid
        for cid, rec in ident.items()
        if isinstance(rec, dict) and rec.get("primary_role") == "wk_batter"
    }


def _tally(collection: str, db_path: Path | str) -> pl.DataFrame:
    """Per-fielder {catches, stumpings, runouts, dismissals} split by whether he kept wicket in that
    innings (`kept`): one row per (fielder, kept), plus `matches_kept` on the kept rows.

    Cricsheet doesn't say who kept. The keeper of an innings is read from the fielding side's XI
    (`match_players_<col>`): whoever made a stumping in it, else an XI player the player master
    tags as a wicket-keeper, else one who has stumped anyone in this league; ties go to the most
    stumpings in the league. A DB without the XI table falls back to the tag alone (every
    dismissal by a tagged keeper, or by anyone with a stumping, counts as keeping; `matches_kept`
    then counts only the matches with such a dismissal)."""
    table_suffix(collection)  # rejects an unsafe collection name
    keepers = sorted(_keeper_ids())
    with _connect(db_path) as con:
        xi = f"match_players_{base_suffix(collection)}"
        con.register("_wk_tagged", pl.DataFrame({"pid": keepers}, schema={"pid": pl.String}))
        if xi in _tables(con):
            keeper_sql = f"""
            inn AS (
                SELECT DISTINCT match_id, innings_idx, bowling_team FROM __BALLS__ WHERE {MAIN_INNINGS}
            ),
            st_inn AS (
                SELECT match_id, innings_idx, fielder, COUNT(*) AS n FROM dis
                WHERE wicket_kind = 'stumped' GROUP BY ALL
            ),
            st_all AS (SELECT fielder, COUNT(*) AS n FROM dis WHERE wicket_kind = 'stumped' GROUP BY 1),
            cand AS (
                SELECT inn.match_id, inn.innings_idx, x.pid,
                       COALESCE(si.n, 0) AS st_here,
                       x.pid IN (SELECT pid FROM _wk_tagged) AS tagged,
                       COALESCE(sa.n, 0) AS st_all
                FROM inn
                JOIN (SELECT match_id, team, COALESCE(identifier, '{UNRESOLVED}' || name) AS pid
                      FROM {xi}) x ON x.match_id = inn.match_id AND x.team = inn.bowling_team
                LEFT JOIN st_inn si ON si.match_id = inn.match_id AND si.innings_idx = inn.innings_idx
                                   AND si.fielder = x.pid
                LEFT JOIN st_all sa ON sa.fielder = x.pid
            ),
            keeper AS (
                SELECT match_id, innings_idx, pid FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY match_id, innings_idx
                        ORDER BY st_here DESC, tagged DESC, st_all DESC, pid
                    ) AS rk
                    FROM cand WHERE st_here > 0 OR tagged OR st_all > 0
                ) WHERE rk = 1
            ),
            credited AS (
                SELECT d.*, k.pid IS NOT NULL AS kept FROM dis d
                LEFT JOIN keeper k ON k.match_id = d.match_id AND k.innings_idx = d.innings_idx
                                  AND k.pid = d.fielder
            ),
            kept_matches AS (SELECT pid AS fielder, COUNT(DISTINCT match_id) AS n FROM keeper GROUP BY 1)"""
        else:
            keeper_sql = """
            st_all AS (SELECT fielder, COUNT(*) AS n FROM dis WHERE wicket_kind = 'stumped' GROUP BY 1),
            credited AS (
                SELECT d.*, (d.fielder IN (SELECT pid FROM _wk_tagged)
                             OR d.fielder IN (SELECT fielder FROM st_all)) AS kept
                FROM dis d
            ),
            kept_matches AS (
                SELECT fielder, COUNT(DISTINCT match_id) AS n FROM credited WHERE kept GROUP BY 1
            )"""
        # every wicket on a delivery (a second one off the same ball is lost from balls_), fielders
        # as ids
        sql = f"""
        WITH dis AS (
            SELECT match_id, innings_idx, unnest(fielders) AS fielder, wicket_kind
            FROM __WICKETS__
            WHERE wicket_kind IN ('caught', 'stumped', 'run out') AND len(fielders) > 0
              AND {MAIN_INNINGS}
        ),
        {keeper_sql}
        SELECT
            c.fielder,
            c.kept,
            SUM(CASE WHEN c.wicket_kind = 'caught' THEN 1 ELSE 0 END) AS catches,
            SUM(CASE WHEN c.wicket_kind = 'stumped' THEN 1 ELSE 0 END) AS stumpings,
            SUM(CASE WHEN c.wicket_kind = 'run out' THEN 1 ELSE 0 END) AS runouts,
            COUNT(*) AS dismissals,
            CASE WHEN c.kept THEN ANY_VALUE(km.n) ELSE 0 END AS matches_kept
        FROM credited c LEFT JOIN kept_matches km ON km.fielder = c.fielder
        WHERE c.fielder IS NOT NULL
        GROUP BY c.fielder, c.kept
        """
        df = keyed_query(con, collection, sql, ("fielder",))
        con.unregister("_wk_tagged")
    if df.is_empty():
        return df
    return df.with_columns(
        pl.col("catches").cast(pl.Int64),
        pl.col("stumpings").cast(pl.Int64),
        pl.col("runouts").cast(pl.Int64),
        pl.col("dismissals").cast(pl.Int64),
        pl.col("matches_kept").cast(pl.Int64),
    )


def keeping(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Wicketkeeping board — by dismissals made while keeping wicket (catches + stumpings + run-out
    involvements in the innings he kept), with the matches he kept wicket in (`matches_kept`)."""
    df = _tally(collection, db_path)
    if df.is_empty():
        return df
    df = df.filter(pl.col("kept")).select(
        "fielder", "cricsheet_id", "display_name", "dismissals", "catches", "stumpings", "runouts",
        "matches_kept",
    ).sort(["dismissals", "cricsheet_id"], descending=[True, False])  # fmt: skip
    return df.head(top_n) if top_n is not None else df


def fielding(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Fielding board — by dismissals made in the field (catches + run-outs in the innings he didn't
    keep wicket), so a keeper's catches on days he fielded count here."""
    df = _tally(collection, db_path)
    if df.is_empty():
        return df
    df = (
        df.filter(~pl.col("kept"))
        .select("fielder", "cricsheet_id", "display_name", "dismissals", "catches", "runouts")
        .sort(["dismissals", "cricsheet_id"], descending=[True, False])
    )
    return df.head(top_n) if top_n is not None else df


__all__ = ["fielding", "keeping"]
