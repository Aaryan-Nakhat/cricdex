"""Shared SQL pieces for the ball-by-ball tables (`balls_<collection>` / `matches_<collection>`)."""

from __future__ import annotations

import re

_SAFE_NAME = re.compile(r"^[a-z0-9_]+$")


def table_suffix(collection: str) -> str:
    """The `<collection>` part of a table name. Only lowercase letters, digits and `_` get through, so a name that
    reaches here from the API or the CLI can't inject SQL (DuckDB can read local files)."""
    suffix = collection.strip().replace("-", "_")
    if not _SAFE_NAME.match(suffix):
        raise ValueError(f"not a collection name: {collection!r}")
    return suffix


# Runs charged to the bowler: off the bat plus wides and no-balls. Byes and leg-byes aren't the bowler's.
BOWLER_RUNS = "(runs_batter + CASE WHEN extras_type IN ('wides', 'noballs') THEN COALESCE(runs_extras, 0) ELSE 0 END)"

# Every innings of a multi-day match, but only the two main innings of a limited-overs one (super overs decide a
# tie; they aren't part of anyone's batting or bowling record).
MAIN_INNINGS = "(innings_idx <= 1 OR match_type IN ('Test', 'MDM'))"

# Dismissals credited to the bowler.
BOWLER_WICKET = (
    "(wicket_kind IS NOT NULL AND wicket_kind NOT IN "
    "('run out', 'retired hurt', 'retired out', 'retired not out', 'obstructing the field'))"
)

# A batter's innings ended (everything but retired hurt / not out, which let them come back).
DISMISSAL = "(wicket_kind IS NOT NULL AND wicket_kind NOT IN ('retired hurt', 'retired not out'))"


# `<col>_last1y` / `<col>_last3y` are time-window copies of a collection's balls/matches tables. The one
# definition: the league registry, NGI, venue names, Wikidata and the exporter all import it.
WINDOWS: dict[str, int] = {"last3y": 1095, "last1y": 365}  # window → days before the latest match
WINDOW_SUFFIXES = tuple(f"_{w}" for w in sorted(WINDOWS, key=WINDOWS.get))  # ("_last1y", "_last3y")


def base_suffix(collection: str) -> str:
    """`ipl_last1y` → `ipl`: the collection a time window was cut from (players/wickets aren't windowed)."""
    safe = table_suffix(collection)
    for suf in WINDOW_SUFFIXES:
        if safe.endswith(suf):
            return safe[: -len(suf)]
    return safe


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def _columns(con, table: str) -> set[str]:
    return {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}


def balls_per_over(con, collection: str, alias: str = "") -> str:
    """SQL for a match's balls per over (`matches_<col>.balls_per_over`, 5 in The Hundred); `6` for a
    DB ingested before the column existed. `alias` prefixes the column (e.g. `m.`)."""
    safe = table_suffix(collection)
    if "balls_per_over" in _columns(con, f"matches_{safe}"):
        return f"COALESCE({alias}balls_per_over, 6)"
    return "6"


def chase_targets(con, collection: str) -> str:
    """A `(match_id, innings_idx, target_runs, target_balls)` relation: the target each innings chased as
    Cricsheet records it (`innings_<col>.target`), which is the revised DLS target and over count when rain
    shortened the chase. `target_balls` is in legal balls. Empty when the innings table hasn't been built
    (a DB ingested before schema 2) — callers then fall back to first-innings total + 1 and scheduled overs."""
    base = base_suffix(collection)
    table = f"innings_{base}"
    if table not in _tables(con) or not {"target_runs", "target_balls"} <= _columns(con, table):
        return (
            "(SELECT CAST(NULL AS VARCHAR) AS match_id, CAST(NULL AS BIGINT) AS innings_idx, "
            "CAST(NULL AS BIGINT) AS target_runs, CAST(NULL AS BIGINT) AS target_balls WHERE FALSE)"
        )
    return (
        f"(SELECT match_id, innings_idx, target_runs, target_balls FROM {table} "
        f"WHERE target_runs IS NOT NULL)"
    )


def player_ids(con, collection: str) -> str | None:
    """A `(name, identifier)` relation that maps this collection's scorecard names to Cricsheet ids.

    Names come from each match's own registry (`players_<col>`), which is authoritative: the ball data
    can spell a player differently from the People Register's `unique_name` ("Navdeep Saini" vs
    "NA Saini") or name someone the register doesn't have yet. A name with two ids across the
    collection takes the one it carries in most matches. Names the registry doesn't cover (DBs ingested
    before the table existed) fall back to `people.unique_name`. None when neither table exists.
    """
    tables = _tables(con)
    reg = f"players_{base_suffix(collection)}"
    has_reg, has_people = reg in tables, "people" in tables
    by_people = "SELECT unique_name AS name, identifier FROM people WHERE unique_name IS NOT NULL"
    if not has_reg:
        return f"({by_people})" if has_people else None
    by_reg = (
        f"SELECT name, FIRST(identifier ORDER BY n DESC, identifier) AS identifier FROM ("
        f"SELECT name, identifier, COUNT(*) AS n FROM {reg} GROUP BY ALL) GROUP BY name"
    )
    if not has_people:
        return f"({by_reg})"
    return f"({by_reg} UNION ALL {by_people} AND unique_name NOT IN (SELECT name FROM {reg}))"


def wickets_rel(con, collection: str) -> str:
    """One row per wicket, carrying its delivery's columns from `balls_<col>`.

    `balls_<col>` keeps only the first wicket of a delivery, so a second one (a run out off a no-ball
    that also had a stumping, say) is lost; `wickets_<col>` has them all. Falls back to the balls table
    when the wickets table hasn't been built.
    """
    safe = table_suffix(collection)
    wk = f"wickets_{base_suffix(collection)}"
    if wk not in _tables(con):
        return f"(SELECT * FROM balls_{safe} WHERE player_out IS NOT NULL)"
    return (
        f"(SELECT b.* REPLACE (w.player_out AS player_out, w.wicket_kind AS wicket_kind, "
        f"w.fielders AS fielders) FROM balls_{safe} b JOIN {wk} w ON w.ball_id = b.ball_id)"
    )


def scorecard_names(con, collection: str) -> str | None:
    """An `(identifier, name)` relation: the name each player goes by in this collection's ball data (the
    spelling they bat or bowl under most often). None when `player_ids` has nothing to map with."""
    ids = player_ids(con, collection)
    if ids is None:
        return None
    safe = table_suffix(collection)
    return (
        f"(SELECT i.identifier, FIRST(c.name ORDER BY c.n DESC, c.name) AS name FROM ("
        f"SELECT name, COUNT(*) AS n FROM (SELECT batter AS name FROM balls_{safe} "
        f"UNION ALL SELECT bowler FROM balls_{safe}) WHERE name IS NOT NULL GROUP BY name) c "
        f"JOIN {ids} i ON i.name = c.name GROUP BY i.identifier)"
    )
