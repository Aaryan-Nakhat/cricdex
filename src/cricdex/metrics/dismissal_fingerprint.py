"""Dismissal fingerprint — *how* a player gets out / takes wickets.

This is pure descriptive metadata, deliberately kept OUT of the
Bayesian skill model (the survival / strike skills only care about
the *rate* of dismissals, not the *mode*). The mode mix is a scouting
signal instead — it tells you the shape of a player's dismissals, not
their magnitude.

Three granularities:

- `batter_modes(name)` — how this batter gets out, across every kind
  (includes run-out, since running is a genuine batter trait).
  Rate-grade: top players have hundreds of dismissals.
- `bowler_modes(name)` — how this bowler takes wickets, bowler-credited
  kinds only (excludes run-out / retired / obstructing). Rate-grade.
- `matchup_log(batter, bowler)` — the raw rivalry record, e.g.
  "Bumrah has dismissed Kohli 5×: 3 caught, 2 lbw". Count-grade —
  matchups are sparse, so these are counts, NOT percentages.

Reading the mix (rule of thumb):
- batter, high bowled+lbw → beaten at the stumps (technique / line)
- batter, high caught     → falls to false / aerial shots (aggression)
- batter, high stumped    → footwork lapse vs spin
- bowler, high bowled+lbw → attacks the stumps (yorkers / darts)
- bowler, high caught     → induces false shots (bowls for the mistake)
- bowler, high stumped    → flights it, beats batters in the air
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

# Kinds credited to the bowler (the bat-vs-ball contest). Run-out,
# retired-hurt, retired-out and obstructing-the-field are excluded for
# bowlers because they aren't the bowler's doing.
BOWLER_CREDITED = (
    "bowled",
    "caught",
    "lbw",
    "caught and bowled",
    "stumped",
    "hit wicket",
)


def _safe(collection: str) -> str:
    return collection.replace("-", "_")


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return table in {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def batter_modes(name: str, collection: str = "ipl", db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    """How `name` gets out. Returns {total, rows:[{kind,count,pct}], read}."""
    safe = _safe(collection)
    with duckdb.connect(str(db_path), read_only=True) as con:
        if not _table_exists(con, f"balls_{safe}"):
            return {"total": 0, "rows": [], "read": ""}
        rows = con.execute(
            f"""
            SELECT wicket_kind AS kind, COUNT(*) AS count
            FROM balls_{safe}
            WHERE player_out = ? AND wicket_kind IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC
            """,
            [name],
        ).fetchall()
    return _assemble(rows, role="batter")


def bowler_modes(name: str, collection: str = "ipl", db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    """How `name` takes wickets (bowler-credited kinds only)."""
    safe = _safe(collection)
    kinds_sql = ", ".join(f"'{k}'" for k in BOWLER_CREDITED)
    with duckdb.connect(str(db_path), read_only=True) as con:
        if not _table_exists(con, f"balls_{safe}"):
            return {"total": 0, "rows": [], "read": ""}
        rows = con.execute(
            f"""
            SELECT wicket_kind AS kind, COUNT(*) AS count
            FROM balls_{safe}
            WHERE bowler = ? AND player_out IS NOT NULL
              AND wicket_kind IN ({kinds_sql})
            GROUP BY 1 ORDER BY 2 DESC
            """,
            [name],
        ).fetchall()
    return _assemble(rows, role="bowler")


def matchup_log(
    batter: str,
    bowler: str,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict:
    """Raw rivalry record — how often `bowler` dismissed `batter`, by
    kind. Counts, not percentages (matchups are sparse)."""
    safe = _safe(collection)
    kinds_sql = ", ".join(f"'{k}'" for k in BOWLER_CREDITED)
    with duckdb.connect(str(db_path), read_only=True) as con:
        if not _table_exists(con, f"balls_{safe}"):
            return {"batter": batter, "bowler": bowler, "total": 0, "rows": [], "balls": 0}
        rows = con.execute(
            f"""
            SELECT wicket_kind AS kind, COUNT(*) AS count
            FROM balls_{safe}
            WHERE batter = ? AND bowler = ? AND player_out = ?
              AND wicket_kind IN ({kinds_sql})
            GROUP BY 1 ORDER BY 2 DESC
            """,
            [batter, bowler, batter],
        ).fetchall()
        balls = con.execute(
            f"""
            SELECT COUNT(*) FROM balls_{safe}
            WHERE batter = ? AND bowler = ?
              AND COALESCE(extras_type,'') NOT IN ('wides')
            """,
            [batter, bowler],
        ).fetchone()[0]
    total = sum(c for _, c in rows)
    return {
        "batter": batter,
        "bowler": bowler,
        "balls": int(balls or 0),
        "total": total,
        "rows": [{"kind": k, "count": c} for k, c in rows],
    }


def _assemble(rows: list[tuple], role: str) -> dict:
    total = sum(c for _, c in rows)
    if total == 0:
        return {"total": 0, "rows": [], "read": ""}
    out = [{"kind": k, "count": c, "pct": round(100 * c / total, 1)} for k, c in rows]
    return {"total": total, "rows": out, "read": _read(out, role)}


def _read(rows: list[dict], role: str) -> str:
    """One-line scouting interpretation of the dominant mode mix."""
    pct = {r["kind"]: r["pct"] for r in rows}
    stumps = pct.get("bowled", 0) + pct.get("lbw", 0)
    caught = pct.get("caught", 0) + pct.get("caught and bowled", 0)
    stumped = pct.get("stumped", 0)
    if role == "batter":
        if stumps >= 40:
            return "often beaten at the stumps — technique / line vulnerability"
        if stumped >= 12:
            return "footwork lapses vs spin (high stumped rate)"
        if caught >= 60:
            return "falls mostly to false / aerial shots — aggression risk"
        return "balanced dismissal mix"
    # bowler
    if stumps >= 40:
        return "attacks the stumps — bowls full / straight for bowled + lbw"
    if stumped >= 10:
        return "flights it — beats batters in the air (stumpings)"
    if caught >= 65:
        return "induces false shots — bowls for the catch"
    return "balanced wicket-taking mix"
