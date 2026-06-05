"""Head-to-head matchups + pace/spin splits, straight from the ball-by-ball.

- `pairwise(collection)` → one row per (batter, bowler) with balls / runs / SR /
  dot% / bowler-credited dismissals. The export slices it per player into
  `matchups/<cid>.json` (`as_batter` = rows where batter==P, `as_bowler` = rows
  where bowler==P).
- `pace_spin_splits(collection, bowler_category)` → per batter, SR + dismissal
  rate vs seam vs spin (bowler type from the Gemini taxonomy, joined by name).

No new columns — `balls_<collection>` already carries batter/bowler/runs/
extras_type/wicket_kind/player_out.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

# Dismissals credited to the bowler (run-outs etc. are not the matchup's).
_BOWLER_OUTS = ("bowled", "caught", "lbw", "stumped", "caught and bowled", "hit wicket")


def _connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def pairwise(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 6,
) -> list[dict]:
    """One row per (batter, bowler) meeting `min_balls` legal deliveries."""
    safe = collection.replace("-", "_")
    outs = " OR ".join(f"wicket_kind = '{k}'" for k in _BOWLER_OUTS)
    sql = f"""
    WITH agg AS (
        SELECT
            batter, bowler,
            SUM(CASE WHEN extras_type IS DISTINCT FROM 'wides' THEN 1 ELSE 0 END) AS balls,
            SUM(runs_batter) AS runs,
            SUM(CASE WHEN runs_total = 0 AND extras_type IS DISTINCT FROM 'wides'
                     THEN 1 ELSE 0 END) AS dots,
            SUM(CASE WHEN player_out = batter AND ({outs}) THEN 1 ELSE 0 END) AS outs
        FROM balls_{safe}
        WHERE batter IS NOT NULL AND bowler IS NOT NULL
        GROUP BY batter, bowler
    )
    SELECT batter, bowler, balls, runs, outs,
           CAST(ROUND(100.0 * runs / NULLIF(balls, 0), 1) AS DOUBLE) AS sr,
           CAST(ROUND(100.0 * dots / NULLIF(balls, 0), 1) AS DOUBLE) AS dot_pct
    FROM agg
    WHERE balls >= {min_balls}
    ORDER BY balls DESC
    """
    with _connect(db_path) as con:
        cols = ["batter", "bowler", "balls", "runs", "outs", "sr", "dot_pct"]
        return [dict(zip(cols, r, strict=True)) for r in con.execute(sql).fetchall()]


def pace_spin_splits(
    collection: str = "ipl",
    bowler_category: dict[str, str] | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    min_balls: int = 60,
) -> dict[str, dict]:
    """{batter -> {vs_seam:{balls,runs,sr,outs,out_rate}, vs_spin:{…}}}.

    `bowler_category` maps bowler scorecard-name → 'seam' | 'spin' (from the
    taxonomy); deliveries by uncategorised bowlers are ignored.
    """
    if not bowler_category:
        return {}
    safe = collection.replace("-", "_")
    outs = " OR ".join(f"wicket_kind = '{k}'" for k in _BOWLER_OUTS)
    pairs = [{"bowler": n, "cat": c} for n, c in bowler_category.items() if c in ("seam", "spin")]
    if not pairs:
        return {}
    with _connect(db_path) as con:
        import polars as pl

        con.register("bcat", pl.DataFrame(pairs))
        rows = con.execute(
            f"""
            SELECT b.batter AS batter, bc.cat AS cat,
                   SUM(CASE WHEN b.extras_type IS DISTINCT FROM 'wides' THEN 1 ELSE 0 END) AS balls,
                   SUM(b.runs_batter) AS runs,
                   SUM(CASE WHEN b.player_out = b.batter AND ({outs}) THEN 1 ELSE 0 END) AS outs
            FROM balls_{safe} b
            JOIN bcat bc ON b.bowler = bc.bowler
            WHERE b.batter IS NOT NULL
            GROUP BY b.batter, bc.cat
            """
        ).fetchall()
    out: dict[str, dict] = {}
    for batter, cat, balls, runs, dis in rows:
        if not balls:
            continue
        rec = {
            "balls": int(balls),
            "runs": int(runs or 0),
            "sr": round(100.0 * (runs or 0) / balls, 1),
            "outs": int(dis or 0),
            "out_rate": round((dis or 0) / balls * 100, 2),  # dismissals per 100 balls
        }
        out.setdefault(batter, {})[f"vs_{cat}"] = rec
    # keep only batters with a decent sample on at least one side
    return {
        b: v
        for b, v in out.items()
        if max((s.get("balls", 0) for s in v.values()), default=0) >= min_balls
    }


__all__ = ["pace_spin_splits", "pairwise"]
