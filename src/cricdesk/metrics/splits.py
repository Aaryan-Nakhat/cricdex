"""Four context metrics added 2026-10-29, each measured against the league on the same kind of ball (same
phase, or the same over of a chase), so a player's phase mix doesn't pass for skill.

They are the candidates that passed a split-half reliability test declared before any number (IPL, every
season: each player's matches split alternately in two; a metric is kept when the two halves' rankings
agree with Spearman r >= 0.30, p < 0.01, over 40+ players; docs/METHODOLOGY.md section 3):

    dot_avoidance   batters: dots avoided per 100 balls against the league in the same phase   r = 0.70
    pace_spin       batters: runs per 100 balls above the league against spin, against pace,
                    and the difference                                                     r = 0.37
                    (against spin alone 0.66)
    finisher        batters: runs per 100 balls above the league in overs 17-20 of a chase   r = 0.44
    hand_split      bowlers: runs per 100 balls saved against left- and right-handers, and the
                    difference                                                            r = 0.30
                    (the weakest that passed)

Every rate is shrunk toward the league (0) by how much its sample says (`_shrink`, empirical Bayes:
the spread between players beyond what ball-to-ball noise gives sets the prior), so a 47-ball record
doesn't top a list; the raw figure is kept beside it.

Wicket-based candidates failed it (wickets of set batters, wickets with the new ball: r -0.05, -0.16), as
did Pressure Conversion (-0.18): wickets are too rare for a split of a player's matches to agree.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from cricdesk.common.sql import MAIN_INNINGS, keyed_query, table_suffix
from cricdesk.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
LEGAL_BAT = "COALESCE(extras_type, '') <> 'wides'"


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def _shrink(df: pl.DataFrame, mean: str, n: str, s2: str, out: str, n_min: int = 0) -> pl.DataFrame:
    """`out` = `mean` × n / (n + k): each player's average residual per ball pulled toward 0 (the
    league) with k = s² / τ², s² the per-ball residual variance and τ² the spread of true player
    means (the variance of the players' means less their average noise s² / n, method of moments).
    No spread beyond the noise: everyone at 0. τ² is estimated on the players with `n_min` balls or
    more (a one-ball sample's noise would swamp it)."""
    if df.is_empty():
        return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(out))
    fit = df.filter(pl.col(n) >= n_min)
    m = fit[mean].to_numpy().astype(float)
    w = fit[n].to_numpy().astype(float)
    v = fit[s2].to_numpy().astype(float)
    tau2 = float(m.var(ddof=1) - (v / w).mean()) if len(m) > 2 else 0.0
    if tau2 <= 0:
        return df.with_columns(pl.lit(0.0).alias(out))
    k = float(v.mean()) / tau2
    return df.with_columns((pl.col(mean) * pl.col(n) / (pl.col(n) + k)).alias(out))


def _shrink_edge(
    df: pl.DataFrame, a: str, b: str, n_a: str, n_b: str, s2: dict, out: str
) -> pl.DataFrame:
    """`out` = the raw difference (a − b) × τ² / (τ² + its noise), its noise s²_a / n_a + s²_b / n_b and
    τ² the spread of true differences across players (method of moments). Shrinking each side apart and
    subtracting would let the two shrink amounts make an edge of their own (a tail-ender poor against
    both reads strong against one)."""
    if df.is_empty():
        return df.with_columns(pl.lit(None, dtype=pl.Float64).alias(out))
    raw = (df[a] - df[b]).to_numpy().astype(float)
    noise = s2["a"] / df[n_a].to_numpy().astype(float) + s2["b"] / df[n_b].to_numpy().astype(float)
    tau2 = float(raw.var(ddof=1) - noise.mean()) if len(raw) > 2 else 0.0
    w = tau2 / (tau2 + noise) if tau2 > 0 else noise * 0.0
    return df.with_columns(pl.Series(f"{out}_raw", raw), pl.Series(out, raw * w))


def _identity_table(field: str) -> pl.DataFrame:
    """cid -> the player master's `field` (bowling_category: seam / spin; batting_hand: left / right)."""
    from cricdesk.scout.identity import master

    rows = [
        (cid, r.get(field))
        for cid, r in master.load().items()
        if isinstance(r, dict) and r.get(field)
    ]
    return pl.DataFrame(rows, schema={"cid": pl.String, "v": pl.String}, orient="row")


def dot_avoidance(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 150,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Dots avoided per 100 balls: (the league's dot rate in the phase of each ball he faced − his dots)
    per 100 balls faced (wides don't count), shrunk toward the league (`dots_avoided_per100`; the raw
    figure `dots_avoided_raw`). Higher = he turns more balls into runs than the average batter would
    on the same balls: strike rotation, which boundary-heavy numbers hide."""
    table_suffix(collection)
    sql = f"""
    WITH b AS (
        SELECT batter, phase, CAST(runs_batter = 0 AS DOUBLE) AS dot
        FROM __BALLS__ WHERE batter IS NOT NULL AND {LEGAL_BAT} AND {MAIN_INNINGS}
    ),
    lg AS (SELECT phase, AVG(dot) AS e FROM b GROUP BY 1),
    x AS (SELECT batter, dot, e, e - dot AS res FROM b JOIN lg USING (phase))
    SELECT batter,
           COUNT(*) AS balls,
           100 * AVG(dot) AS dot_pct,
           100 * AVG(e) AS expected_dot_pct,
           100 * AVG(res) AS dots_avoided_raw,
           100 * 100 * ANY_VALUE(s2) AS s2
    FROM x, (SELECT VAR_POP(res) AS s2 FROM x)
    GROUP BY batter
    HAVING COUNT(*) >= {int(min_balls)}
    """
    with _connect(db_path) as con:
        df = keyed_query(con, collection, sql, ("batter",))
    df = _shrink(df, "dots_avoided_raw", "balls", "s2", "dots_avoided_per100")
    return _finish(
        df, "dots_avoided_per100", ["dot_pct", "expected_dot_pct", "dots_avoided_raw"], top_n
    )


def _finish(df: pl.DataFrame, key: str, also: list[str], top_n: int | None) -> pl.DataFrame:
    """Rounded, sorted by `key` (then id), the variance columns dropped, top_n rows."""
    if df.is_empty():
        return df
    df = df.with_columns([pl.col(c).round(2) for c in [key, *also]]).drop(
        [c for c in df.columns if c.startswith("s2")]
    )
    df = df.sort([key, "cricsheet_id"], descending=[True, False])
    return df.head(top_n) if top_n is not None else df


def pace_spin(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 100,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Runs per 100 balls above the league against spin and against pace (each against the league's
    rate for that bowling type in the same phase, each shrunk toward the league), and spin minus pace
    (`spin_edge`, the difference itself shrunk by its own noise: `_shrink_edge`): positive = relatively
    better against spin. Needs `min_balls` against each type; the
    bowling type is the player master's."""
    table_suffix(collection)
    cats = _identity_table("bowling_category")
    sql = """
    WITH b AS (
        SELECT x.batter, x.phase, c.v AS cat, CAST(x.runs_batter AS DOUBLE) AS r
        FROM __BALLS__ x JOIN _bowl_cat c ON c.cid = x.bowler
        WHERE x.batter IS NOT NULL AND COALESCE(x.extras_type, '') <> 'wides'
          AND (x.innings_idx <= 1 OR x.match_type IN ('Test', 'MDM'))
          AND c.v IN ('spin', 'seam')
    ),
    lg AS (SELECT phase, cat, AVG(r) AS e FROM b GROUP BY ALL),
    x AS (SELECT batter, cat, r, r - e AS res FROM b JOIN lg USING (phase, cat)),
    v AS (SELECT cat, VAR_POP(res) AS s2 FROM x GROUP BY 1)
    SELECT batter, cat, COUNT(*) AS n, 100 * AVG(r) AS sr, 100 * AVG(res) AS above,
           100 * 100 * ANY_VALUE(v.s2) AS s2
    FROM x JOIN v USING (cat)
    GROUP BY batter, cat
    """
    with _connect(db_path) as con:
        con.register("_bowl_cat", cats)
        df = keyed_query(con, collection, sql, ("batter",))
        con.unregister("_bowl_cat")
    if df.is_empty():
        return df
    s2 = {
        tag: float(df.filter(pl.col("cat") == cat)["s2"][0])
        for cat, tag in (("spin", "spin"), ("seam", "pace"))
    }
    parts = {}
    for cat, tag in (("spin", "spin"), ("seam", "pace")):
        d = _shrink(df.filter(pl.col("cat") == cat), "above", "n", "s2", "shrunk", min_balls)
        parts[tag] = d.select(
            "batter", "cricsheet_id", "display_name",
            pl.col("n").alias(f"balls_{tag}"), pl.col("sr").round(1).alias(f"sr_{tag}"),
            pl.col("above").alias(f"above_vs_{tag}_raw"), pl.col("shrunk").alias(f"above_vs_{tag}"),
        )  # fmt: skip
    out = (
        parts["spin"]
        .join(parts["pace"].drop("batter", "display_name"), on="cricsheet_id", how="inner")
        .filter((pl.col("balls_spin") >= min_balls) & (pl.col("balls_pace") >= min_balls))
    )
    out = _shrink_edge(out, "above_vs_spin_raw", "above_vs_pace_raw", "balls_spin", "balls_pace",
                       {"a": s2["spin"], "b": s2["pace"]}, "spin_edge")  # fmt: skip
    return _finish(
        out, "spin_edge",
        ["above_vs_spin", "above_vs_pace", "above_vs_spin_raw", "above_vs_pace_raw", "spin_edge_raw"],
        top_n,
    )  # fmt: skip


def finisher(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 40,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Runs per 100 balls above the league in overs 17-20 of a chase (each ball against the league's
    rate in that over of a chase), shrunk toward the league (`above_per100`; raw `above_raw`), with his
    innings there and how often he was still in at the end."""
    table_suffix(collection)
    sql = f"""
    WITH b AS (
        SELECT match_id, batter, over, CAST(runs_batter AS DOUBLE) AS r
        FROM __BALLS__
        WHERE batter IS NOT NULL AND {LEGAL_BAT} AND innings_idx = 1 AND over >= 16
    ),
    lg AS (SELECT over, AVG(r) AS e FROM b GROUP BY 1),
    x AS (SELECT match_id, batter, r, r - e AS res FROM b JOIN lg USING (over)),
    outs AS (
        SELECT DISTINCT match_id, player_out AS batter FROM __BALLS__
        WHERE innings_idx = 1 AND player_out IS NOT NULL
    ),
    inn AS (
        SELECT batter, COUNT(*) AS innings, AVG(CAST(not_out AS DOUBLE)) AS not_out_share FROM (
            SELECT DISTINCT x.match_id, x.batter, o.batter IS NULL AS not_out
            FROM x LEFT JOIN outs o ON o.match_id = x.match_id AND o.batter = x.batter
        ) GROUP BY 1
    )
    SELECT x.batter,
           COUNT(*) AS balls,
           ROUND(100 * AVG(r), 1) AS sr,
           100 * AVG(res) AS above_raw,
           ANY_VALUE(i.innings) AS innings,
           ROUND(100 * ANY_VALUE(i.not_out_share), 1) AS not_out_pct,
           100 * 100 * ANY_VALUE(v.s2) AS s2
    FROM x JOIN inn i ON i.batter = x.batter, (SELECT VAR_POP(res) AS s2 FROM x) v
    GROUP BY x.batter
    HAVING COUNT(*) >= {int(min_balls)}
    """
    with _connect(db_path) as con:
        df = keyed_query(con, collection, sql, ("batter",))
    df = _shrink(df, "above_raw", "balls", "s2", "above_per100")
    return _finish(df, "above_per100", ["above_raw"], top_n)


def hand_split(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 90,
    top_n: int | None = 500,
) -> pl.DataFrame:
    """Runs saved per 100 legal balls against left- and right-handed batters (the league's rate
    against that hand in the same phase, less his; each shrunk toward the league), and left minus
    right (`left_edge`, shrunk by its own noise: `_shrink_edge`): positive = relatively better against
    left-handers. Needs `min_balls` against
    each hand; the hand is the player master's. The weakest signal of the four (split-half r 0.30)."""
    table_suffix(collection)
    hands = _identity_table("batting_hand")
    sql = """
    WITH b AS (
        SELECT x.bowler, x.phase, h.v AS hand, CAST(x.runs_total AS DOUBLE) AS r
        FROM __BALLS__ x JOIN _bat_hand h ON h.cid = x.batter
        WHERE x.bowler IS NOT NULL AND COALESCE(x.extras_type, '') NOT IN ('wides', 'noballs')
          AND (x.innings_idx <= 1 OR x.match_type IN ('Test', 'MDM'))
          AND h.v IN ('left', 'right')
    ),
    lg AS (SELECT phase, hand, AVG(r) AS e FROM b GROUP BY ALL),
    x AS (SELECT bowler, hand, e - r AS res FROM b JOIN lg USING (phase, hand)),
    v AS (SELECT hand, VAR_POP(res) AS s2 FROM x GROUP BY 1)
    SELECT bowler, hand, COUNT(*) AS n, 100 * AVG(res) AS saved, 100 * 100 * ANY_VALUE(v.s2) AS s2
    FROM x JOIN v USING (hand)
    GROUP BY bowler, hand
    """
    with _connect(db_path) as con:
        con.register("_bat_hand", hands)
        df = keyed_query(con, collection, sql, ("bowler",))
        con.unregister("_bat_hand")
    if df.is_empty():
        return df
    s2 = {hand: float(df.filter(pl.col("hand") == hand)["s2"][0]) for hand in ("left", "right")}
    parts = {}
    for hand in ("left", "right"):
        d = _shrink(df.filter(pl.col("hand") == hand), "saved", "n", "s2", "shrunk", min_balls)
        parts[hand] = d.select(
            "bowler", "cricsheet_id", "display_name",
            pl.col("n").alias(f"balls_vs_{hand}"), pl.col("saved").alias(f"saved_vs_{hand}_raw"),
            pl.col("shrunk").alias(f"saved_vs_{hand}"),
        )  # fmt: skip
    out = (
        parts["left"]
        .join(parts["right"].drop("bowler", "display_name"), on="cricsheet_id", how="inner")
        .filter((pl.col("balls_vs_left") >= min_balls) & (pl.col("balls_vs_right") >= min_balls))
    )
    out = _shrink_edge(out, "saved_vs_left_raw", "saved_vs_right_raw", "balls_vs_left",
                       "balls_vs_right", {"a": s2["left"], "b": s2["right"]}, "left_edge")  # fmt: skip
    return _finish(
        out, "left_edge",
        ["saved_vs_left", "saved_vs_right", "saved_vs_left_raw", "saved_vs_right_raw",
         "left_edge_raw"], top_n,
    )  # fmt: skip


__all__ = ["dot_avoidance", "finisher", "hand_split", "pace_spin"]
