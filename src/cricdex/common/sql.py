"""Shared SQL pieces for the ball-by-ball tables (`balls_<collection>` / `matches_<collection>`)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import duckdb

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


# A league's eras (config/leagues.toml `[[league.era]]`, e.g. the IPL's Impact Player era) are windows
# too: `<col>_era_<key>` tables cut from the collection's matches since the era began.
ERA_PREFIX = "era_"
_ERA_SUFFIX = re.compile(r"_era_[a-z][a-z0-9]*$")


def base_suffix(collection: str) -> str:
    """`ipl_last1y` / `ipl_era_impact` → `ipl`: the collection a time window was cut from
    (players/wickets aren't windowed)."""
    safe = table_suffix(collection)
    for suf in WINDOW_SUFFIXES:
        if safe.endswith(suf):
            return safe[: -len(suf)]
    m = _ERA_SUFFIX.search(safe)
    return safe[: m.start()] if m else safe


def is_window(name: str) -> bool:
    """Is this collection key (or `balls_<key>` / `matches_<key>` table name) a time-window copy?"""
    return name.endswith(WINDOW_SUFFIXES) or bool(_ERA_SUFFIX.search(name))


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
    spelling they bat or bowl under most often). Resolved per match (`keyed_balls`), so two players who
    share a name each get their own row. None when `player_ids` has nothing to map with."""
    if player_ids(con, collection) is None and match_name_map(con, collection) is None:
        return None
    labels = player_labels(con, collection)
    return f"(SELECT pid AS identifier, name FROM {labels} WHERE pid NOT LIKE '{UNRESOLVED}%')"


# ---- player identity: every stat is keyed by the Cricsheet registry id, never the scorecard name ----
#
# Cricsheet's ball data names players by their scorecard name, and two different players can share one
# ("Mandeep Singh", "Muhammad Usman" ×4 in men's T20Is). Each match's registry (`players_<col>`) maps
# that match's names to ids, so the mapping is made per MATCH: `keyed_balls` swaps every player column
# for the id (`batter`, `non_striker`, `bowler`, `player_out`, `fielders`) and keeps the scorecard
# spelling next to it (`<col>_name`, `fielder_names`). Every metric groups by the id columns and
# `relabel` turns the ids back into `name` / `cricsheet_id` / `display_name` for display.

UNRESOLVED = (
    "unresolved:"  # key prefix for a name neither the match registry nor the register knows
)
_PLAYER_COLS = ("batter", "non_striker", "bowler", "player_out")


def match_name_map(con, collection: str) -> str | None:
    """A `(match_id, name, pid)` relation from each match's own registry, or None for a DB ingested
    before `players_<col>` existed."""
    reg = f"players_{base_suffix(collection)}"
    if reg not in _tables(con):
        return None
    return (
        f"(SELECT match_id, name, MIN(identifier) AS pid FROM {reg} "
        f"WHERE name IS NOT NULL AND identifier IS NOT NULL GROUP BY 1, 2)"
    )


def _key_expr(col: str, m_alias: str | None, p_alias: str | None) -> str:
    parts = [f"{a}.{c}" for a, c in ((m_alias, "pid"), (p_alias, "identifier")) if a]
    parts.append(f"'{UNRESOLVED}' || b.{col}")
    return f"CASE WHEN b.{col} IS NULL THEN NULL ELSE COALESCE({', '.join(parts)}) END"


def keyed_balls(con, collection: str) -> str:
    """`balls_<col>` with every player column holding the player's registry id instead of his name.

    Same columns as the balls table (so any SQL written against it runs unchanged), plus the scorecard
    spellings: `batter_name`, `non_striker_name`, `bowler_name`, `player_out_name`, `fielder_names`.
    An id comes from that match's registry, else the collection-wide name map (`player_ids`), else the
    name itself prefixed `unresolved:` (never merged with a real id). After `materialize_keyed` on the
    same connection this is a temp table, so per-player queries don't redo the joins."""
    safe = table_suffix(collection)
    tmp = f"_keyed_balls_{safe}"
    if tmp in _temp_tables(con):
        return tmp
    have = _columns(con, f"balls_{safe}")
    m = match_name_map(con, collection) if "match_id" in have else None
    ids = player_ids(con, collection)
    pcols = [c for c in _PLAYER_COLS if c in have]
    joins, repl = [], []
    for i, col in enumerate(pcols):
        ma = f"m{i}" if m else None
        pa = f"p{i}" if ids else None
        if m:
            joins.append(
                f"LEFT JOIN {m} {ma} ON {ma}.match_id = b.match_id AND {ma}.name = b.{col}"
            )
        if ids:
            joins.append(f"LEFT JOIN {ids} {pa} ON {pa}.name = b.{col}")
        repl.append(f"{_key_expr(col, ma, pa)} AS {col}")
    names = [f"b.{c} AS {c}_name" for c in pcols]
    if {"fielders", "ball_id"} <= have:
        # fielders: one row per (delivery, fielder) mapped like the rest, folded back in list order
        f_parts = [x for x in ("fm.pid" if m else None, "fp.identifier" if ids else None) if x]
        f_key = f"COALESCE({', '.join([*f_parts, f"'{UNRESOLVED}' || u.f"])})"
        f_joins = (
            f"LEFT JOIN {m} fm ON fm.match_id = u.match_id AND fm.name = u.f " if m else ""
        ) + (f"LEFT JOIN {ids} fp ON fp.name = u.f " if ids else "")
        mid = "match_id" if "match_id" in have else "NULL AS match_id"
        fielder_ids = (
            f"(SELECT u.ball_id, LIST({f_key} ORDER BY u.i) AS fids FROM ("
            f"SELECT ball_id, {mid}, UNNEST(fielders) AS f, GENERATE_SUBSCRIPTS(fielders, 1) AS i "
            f"FROM balls_{safe} WHERE len(fielders) > 0) u {f_joins}GROUP BY u.ball_id)"
        )
        repl.append(
            "CASE WHEN b.fielders IS NULL THEN NULL WHEN len(b.fielders) = 0 THEN b.fielders "
            "ELSE fl.fids END AS fielders"
        )
        names.append("b.fielders AS fielder_names")
        joins.append(f"LEFT JOIN {fielder_ids} fl ON fl.ball_id = b.ball_id")
    if not repl:
        return f"balls_{safe}"
    return (
        f"(SELECT b.* REPLACE ({', '.join(repl)}), {', '.join(names)} "
        f"FROM balls_{safe} b {' '.join(joins)})"
    )


def keyed_wickets(con, collection: str) -> str:
    """`wickets_rel` keyed like `keyed_balls`: one row per wicket (every wicket on a delivery), its
    delivery's columns as ids, `player_out` / `fielders` the id of that wicket's batter / fielders and
    `player_out_name` / `fielder_names` their scorecard spellings."""
    tmp = f"_keyed_wickets_{table_suffix(collection)}"
    if tmp in _temp_tables(con):
        return tmp
    kb = keyed_balls(con, collection)
    wk = f"wickets_{base_suffix(collection)}"
    if wk not in _tables(con):
        return f"(SELECT * FROM {kb} WHERE player_out IS NOT NULL)"
    m = match_name_map(con, collection)
    ids = player_ids(con, collection)
    out_parts = [x for x in ("mo.pid" if m else None, "po.identifier" if ids else None) if x]
    out_key = f"COALESCE({', '.join([*out_parts, f"'{UNRESOLVED}' || w.player_out"])})"
    f_parts = [x for x in ("fm.pid" if m else None, "fp.identifier" if ids else None) if x]
    f_key = f"COALESCE({', '.join([*f_parts, f"'{UNRESOLVED}' || u.f"])})"
    joins = (
        f"LEFT JOIN {m} mo ON mo.match_id = w.match_id AND mo.name = w.player_out " if m else ""
    ) + (f"LEFT JOIN {ids} po ON po.name = w.player_out " if ids else "")
    f_joins = (f"LEFT JOIN {m} fm ON fm.match_id = u.match_id AND fm.name = u.f " if m else "") + (
        f"LEFT JOIN {ids} fp ON fp.name = u.f " if ids else ""
    )
    # one wicket of a delivery: its index when the table has one, else its batter (who is out once)
    wi = "wicket_idx" if "wicket_idx" in _columns(con, wk) else "player_out"
    fielder_ids = (
        f"(SELECT u.ball_id, u.wi, LIST({f_key} ORDER BY u.i) AS fids FROM ("
        f"SELECT ball_id, {wi} AS wi, match_id, UNNEST(fielders) AS f, "
        f"GENERATE_SUBSCRIPTS(fielders, 1) AS i FROM {wk} WHERE len(fielders) > 0) u "
        f"{f_joins}GROUP BY u.ball_id, u.wi)"
    )
    return (
        f"(SELECT b.* REPLACE ("
        f"CASE WHEN w.player_out IS NULL THEN NULL ELSE {out_key} END AS player_out, "
        f"w.wicket_kind AS wicket_kind, "
        f"CASE WHEN w.fielders IS NULL THEN NULL WHEN len(w.fielders) = 0 THEN w.fielders "
        f"ELSE fl.fids END AS fielders, w.player_out AS player_out_name, w.fielders AS fielder_names) "
        f"FROM {kb} b JOIN {wk} w ON w.ball_id = b.ball_id {joins}"
        f"LEFT JOIN {fielder_ids} fl ON fl.ball_id = w.ball_id AND fl.wi = w.{wi})"
    )


def _temp_tables(con) -> set[str]:
    return {
        r[0]
        for r in con.execute("SELECT table_name FROM duckdb_tables() WHERE temporary").fetchall()
    }


def materialize_keyed(con, collection: str) -> None:
    """Build `keyed_balls` / `keyed_wickets` once as temp tables on this connection (a read-only one
    is fine), so the many per-player queries of a profile export read them instead of re-joining."""
    safe = table_suffix(collection)
    builders = (
        (f"_keyed_balls_{safe}", keyed_balls),
        (f"_keyed_wickets_{safe}", keyed_wickets),
        (f"_player_labels_{safe}", player_labels),
    )
    for tmp, build in builders:  # in order: the later ones read the earlier temp tables
        if tmp not in _temp_tables(con):
            try:
                con.execute(f"CREATE TEMP TABLE {tmp} AS SELECT * FROM {build(con, collection)}")
            except duckdb.Error:
                # a slim table without the columns this one needs (a test fixture, an old DB):
                # callers fall back to the inline relation
                continue


def player_labels(con, collection: str) -> str:
    """A `(pid, name)` relation: each player key of this collection and the scorecard spelling he
    appears under most often (batting, bowling, at the other end, out or in the field)."""
    tmp = f"_player_labels_{table_suffix(collection)}"
    if tmp in _temp_tables(con):
        return tmp
    kb = keyed_balls(con, collection)
    have = _columns(con, f"balls_{table_suffix(collection)}")
    pairs = [
        f"SELECT {c} AS pid, {c}_name AS name FROM kb WHERE {c} IS NOT NULL"
        for c in _PLAYER_COLS
        if c in have
    ]
    if {"fielders", "ball_id"} <= have:
        pairs.append(
            "SELECT UNNEST(fielders) AS pid, UNNEST(fielder_names) AS name FROM kb "
            "WHERE len(fielders) > 0"
        )
    keep = ", ".join(
        [c for x in _PLAYER_COLS if x in have for c in (x, f"{x}_name")]
        + (["fielders", "fielder_names"] if {"fielders", "ball_id"} <= have else [])
    )
    return (
        f"(WITH kb AS (SELECT {keep} FROM {kb}) SELECT pid, FIRST(name ORDER BY n DESC, name) AS name "
        f"FROM (SELECT pid, name, COUNT(*) AS n FROM ({' UNION ALL '.join(pairs)}) "
        f"WHERE pid IS NOT NULL AND name IS NOT NULL GROUP BY 1, 2) GROUP BY pid)"
    )


def label_map(con, collection: str) -> dict[str, str]:
    """pid → scorecard name for this collection (see `player_labels`)."""
    return dict(con.execute(f"SELECT pid, name FROM {player_labels(con, collection)}").fetchall())


def cid_of(key: str | None) -> str | None:
    """The Cricsheet id behind a player key (None for an unresolved name)."""
    if key is None or str(key).startswith(UNRESOLVED):
        return None
    return str(key)


def name_of_key(key: str | None, labels: dict[str, str]) -> str | None:
    """The scorecard name for a player key."""
    if key is None:
        return None
    return labels.get(key) or str(key).removeprefix(UNRESOLVED)


def resolve_key(con, collection: str, who: str) -> str:
    """A player key for `who`, given either a registry id of this collection or a scorecard name. A
    name two players share resolves to the one with more matches here (ask by id to be exact)."""
    m = match_name_map(con, collection)
    if m is not None:
        hit = con.execute(
            f"SELECT pid FROM {m} WHERE pid = ? OR name = ? "
            f"GROUP BY pid ORDER BY MAX(CASE WHEN pid = ? THEN 1 ELSE 0 END) DESC, COUNT(*) DESC, pid "
            f"LIMIT 1",
            [who, who, who],
        ).fetchone()
        if hit:
            return hit[0]
    ids = player_ids(con, collection)
    if ids is not None:
        hit = con.execute(
            f"SELECT identifier FROM {ids} WHERE identifier = ? OR name = ? LIMIT 1", [who, who]
        ).fetchone()
        if hit:
            return hit[0]
    return who if str(who).startswith(UNRESOLVED) else f"{UNRESOLVED}{who}"


def relabel(df, con, collection: str, cols: tuple[str, ...] | list[str], labels=None):
    """Turn the player-key columns of a polars result back into names: each column in `cols` gets the
    scorecard name, the first one also `cricsheet_id` (+ `display_name` from the player master), the
    others `<col>_id`. Rows stay one per player key, so two players sharing a name stay two rows."""
    import polars as pl

    if df is None or df.is_empty() or not cols:
        return df
    labels = labels if labels is not None else label_map(con, collection)
    display = _display_names()
    out = df
    for i, col in enumerate(cols):
        if col not in out.columns:
            continue
        keys = out[col].to_list()
        id_col = "cricsheet_id" if i == 0 else f"{col}_id"
        out = out.with_columns(
            pl.Series(col, [name_of_key(k, labels) for k in keys], dtype=pl.String),
            pl.Series(id_col, [cid_of(k) for k in keys], dtype=pl.String),
        )
        if i == 0:
            out = out.with_columns(
                pl.Series(
                    "display_name",
                    [display.get(cid_of(k) or "") or name_of_key(k, labels) for k in keys],
                    dtype=pl.String,
                )
            )
    return out


def _display_names() -> dict[str, str]:
    """cid → fan display name from the player master (empty when it isn't built). Re-read only when
    the master file changes."""
    try:
        from cricdex.scout.identity import master

        path = master.MASTER_PATH
        stamp = path.stat().st_mtime if path.exists() else None
    except Exception:  # noqa: BLE001 — display only
        return {}
    return _display_cache(str(path), stamp)


@lru_cache(maxsize=2)
def _display_cache(path: str, stamp: float | None) -> dict[str, str]:
    if stamp is None:
        return {}
    from cricdex.scout.identity import master

    return {
        cid: r["display_name"]
        for cid, r in master.load(Path(path)).items()
        if r.get("display_name")
    }


BALLS_TOKEN = "__BALLS__"  # stands for `keyed_balls(...)` in SQL handed to `keyed_query`
WICKETS_TOKEN = "__WICKETS__"  # stands for `keyed_wickets(...)`


def keyed_sql(con, collection: str, sql: str) -> str:
    """`sql` with the `__BALLS__` / `__WICKETS__` placeholders swapped for the id-keyed relations."""
    if BALLS_TOKEN in sql:
        sql = sql.replace(BALLS_TOKEN, keyed_balls(con, collection))
    if WICKETS_TOKEN in sql:
        sql = sql.replace(WICKETS_TOKEN, keyed_wickets(con, collection))
    return sql


def keyed_query(con, collection: str, sql: str, cols: tuple[str, ...], params=None):
    """Run SQL written against `__BALLS__` / `__WICKETS__` (player columns = ids) and `relabel` the
    player-key columns `cols` of the result."""
    df = con.execute(keyed_sql(con, collection, sql), params or []).pl()
    return relabel(df, con, collection, cols)
