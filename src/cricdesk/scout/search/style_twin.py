"""Style twins: the players who play like this one.

A fan describes a batter's style by where he bats, how fast he scores in each phase, whether he lives
on boundaries or on rotation, how he handles spin against pace and how much risk he takes. He describes
a bowler by what he bowls (pace or spin; wrist or finger), when his captain bowls him, and what he does
in each phase. The twins are built from exactly those things, straight from the ball-by-ball, so a
twin is someone a fan would recognise as "the same kind of player" (roadmap item 25 / I12).

Batter axes (weight in brackets; see `BATTER_AXES`)
---------------------------------------------------
    slot            balls-weighted mean batting position                          (3.0)
    pp_share        share of his balls faced in the powerplay                     (1.0)
    death_share     share of his balls faced at the death                         (1.0)
    tempo_pp/mid/death  runs vs par for that season and phase                     (1.5 each)
    boundary        boundaries hit vs par                                         (1.0)
    dot             dot balls vs par                                              (1.0)
    rotation        balls turned over for 1-3 vs par                              (0.75)
    six_share       sixes / boundaries (power vs placement)                       (0.75)
    spin_vs_pace    log(tempo vs spin / tempo vs pace)                            (0.75)
    risk            log balls per dismissal                                       (1.0)
    left_hand       batting hand (player master), a fixed 2-SD gap when it differs (0.5)

Bowler axes (see `BOWLER_AXES`)
-------------------------------
    pp_share, death_share   share of his balls bowled in the powerplay / at the death   (1.5 each)
    econ_pp/mid/death       runs conceded vs par for that season and phase                (1.0 each)
    strike                  log balls per wicket                                          (1.0)
    dot, boundary           dots / boundaries conceded vs par                            (0.75 each)
    bowled_lbw, stumped     share of his wickets bowled or lbw / stumped                  (0.5 each)
    pace, left_arm          fast / fast-medium / medium and arm (player master), fixed gaps (1.0 each)

"Par" is the whole collection's rate in the same season and phase, so a 2010 opener and a 2024 opener
are compared on how far each was above his own era, and an index of 1.0 is exactly par.

Thin samples are shrunk before scaling: an index toward par (1.0) with a prior of 60 balls in that
phase, a share toward the pool mean (15 boundaries, 8 wickets), balls per dismissal / per wicket toward
the pool mean (4 dismissals / wickets). Every axis is then put on a robust z-scale (median and MAD over
the pool, clipped at +/-3) so no single axis or outlier dominates.

Gates (applied before distance, so "the obvious fits reality")
    evidence  at least `MIN_ROLE_BALLS` balls (faced / bowled) and `MIN_INNINGS` innings in the role;
    batters   twins come from within `SLOT_GAP` batting positions first (an opener's twins are openers);
    bowlers   seamers' twins are seamers and spinners' are spinners (hard); a wrist spinner's twins are
              wrist spinners first and a finger spinner's finger spinners first. A bowler whose style
              the player master doesn't know is only matched with other unknowns and never offered as
              a twin of a known one.

Distance and "% alike"
    D = sqrt(sum w * dz^2 / sum w): the weighted root-mean-square gap in robust SDs per axis.
    alike = 1 - D / 2, clipped to [0, 1]: identical players are 100%, an average gap of half an SD per
    axis is 75%, one full SD is 50%; two random players from the pool sit around 30%. `distance` is
    1 - alike, so every surface that shows `1 - distance` as "% alike" reads this scale.

Players are keyed by registry id (`pid`: the Cricsheet id, else `unresolved:<name>`), so two players
sharing a scorecard name are two vectors.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from loguru import logger

from cricdesk.common.sql import (
    BOWLER_RUNS,
    BOWLER_WICKET,
    DISMISSAL,
    MAIN_INNINGS,
    keyed_balls,
    label_map,
)
from cricdesk.config import DATA_DIR
from cricdesk.scout.identity.sources import STYLE_ARM

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

# Minimum evidence in a role: a bowler's handful of innings at No. 10 made him a "batting twin" of
# top-order batters (roadmap 25).
MIN_ROLE_BALLS = 120
MIN_INNINGS = 6
SLOT_GAP = 1.5  # batting positions: twins within this gap rank first

PHASE_PRIOR = 60.0  # balls: an index is shrunk toward par (1.0) by this many balls of evidence
SHARE_PRIOR_BDY = 15.0  # boundaries: six share shrunk toward the pool mean
SHARE_PRIOR_WKT = 8.0  # wickets: wicket-type shares shrunk toward the pool mean
EVENT_PRIOR = 4.0  # dismissals / wickets: balls-per-event shrunk toward the pool mean
CATEGORICAL_GAP = 2.0  # z-units a categorical difference (hand, arm, pace) counts as

# (axis, weight). Weights are the order a fan describes a style in: slot first (3.0), tempo by phase
# next (1.5 each), then how the runs come (boundaries, dots, risk: 1.0), then the finer grain (0.75).
BATTER_AXES: tuple[tuple[str, float], ...] = (
    ("slot", 3.0),
    ("pp_share", 1.0),
    ("death_share", 1.0),
    ("tempo_pp", 1.5),
    ("tempo_mid", 1.5),
    ("tempo_death", 1.5),
    ("boundary", 1.0),
    ("dot", 1.0),
    ("rotation", 0.75),
    ("six_share", 0.75),
    ("spin_vs_pace", 0.75),
    ("risk", 1.0),
    ("left_hand", 0.5),
)
# For a bowler, when he bowls is his role (1.5 each), then what it costs and what it takes (1.0),
# then how (0.75 / 0.5); pace and arm separate a left-arm quick from a right-arm medium-pacer.
BOWLER_AXES: tuple[tuple[str, float], ...] = (
    ("pp_share", 1.5),
    ("death_share", 1.5),
    ("econ_pp", 1.0),
    ("econ_mid", 1.0),
    ("econ_death", 1.0),
    ("strike", 1.0),
    ("dot", 0.75),
    ("boundary", 0.75),
    ("bowled_lbw", 0.5),
    ("stumped", 0.5),
    ("pace", 1.0),
    ("left_arm", 1.0),
)
CATEGORICAL = {"left_hand", "pace", "left_arm"}  # already in z-units; not rescaled

WRIST = {"leg-spin", "left-arm-wrist-spin"}
FINGER = {"off-spin", "left-arm-orthodox"}
PACE_LEVEL = {
    "right-arm-fast": 1.0,
    "left-arm-fast": 1.0,
    "right-arm-fast-medium": 0.5,
    "right-arm-medium": 0.0,
    "left-arm-medium": 0.0,
}


# ---------- player master: what he bowls, which hand he bats ----------


def _styles() -> pl.DataFrame:
    """(pid, family, pace, left_arm, left_hand) from the player master; empty when it isn't built.
    family: 'seam', 'wrist', 'finger' or None (unknown)."""
    from cricdesk.scout.identity import master

    recs = master.load()  # {} when it isn't built
    rows = []
    for cid, r in recs.items():
        style = r.get("bowling_style")
        cat = r.get("bowling_category")
        if style in WRIST:
            family = "wrist"
        elif style in FINGER or cat == "spin":
            family = "finger" if style in FINGER else "spin"
        elif cat == "seam" or style in PACE_LEVEL:
            family = "seam"
        else:
            family = None
        arm = r.get("bowling_arm") or STYLE_ARM.get(style or "")
        hand = r.get("batting_hand")
        rows.append(
            {
                "pid": cid,
                "family": family,
                "pace": PACE_LEVEL.get(style) if family == "seam" else None,
                "left_arm": None if arm not in ("left", "right") else float(arm == "left"),
                "left_hand": (None if not hand else float(str(hand).lower().startswith("left"))),
            }
        )
    schema = {
        "pid": pl.String,
        "family": pl.String,
        "pace": pl.Float64,
        "left_arm": pl.Float64,
        "left_hand": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema)


def _category(family: str | None) -> str | None:
    """seam / spin from a family."""
    if family is None:
        return None
    return "seam" if family == "seam" else "spin"


# ---------- ball-by-ball aggregates ----------


def _aggregates(
    con: duckdb.DuckDBPyConnection, collection: str, styles: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Per-player batting and bowling aggregates for one collection (raw counts and par sums)."""
    kb = keyed_balls(con, collection)
    con.register("_tw_styles", styles.select("pid", "family").to_arrow())
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _tw AS
        SELECT match_id, innings_idx, over, ball_in_over, phase,
               CAST(substr(CAST(match_date AS VARCHAR), 1, 4) AS INTEGER) AS season,
               batter, non_striker, bowler, player_out, wicket_kind,
               COALESCE(runs_batter, 0) AS rb,
               {BOWLER_RUNS} AS br,
               (extras_type IS NULL OR extras_type <> 'wides') AS faced,
               (extras_type IS NULL OR extras_type NOT IN ('wides', 'noballs')) AS legal,
               COALESCE(runs_batter IN (4, 6) AND NOT COALESCE(runs_non_boundary, FALSE), FALSE) AS bdy,
               COALESCE(runs_batter = 6 AND NOT COALESCE(runs_non_boundary, FALSE), FALSE) AS six,
               {BOWLER_WICKET} AS bwkt,
               {DISMISSAL} AS dis
        FROM {kb}
        WHERE {MAIN_INNINGS} AND phase IN ('powerplay', 'middle', 'death')
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _tw_par AS
        SELECT season, phase,
               SUM(rb) / SUM(faced::INT)::DOUBLE                                 AS p_runs,
               SUM((faced AND bdy)::INT) / SUM(faced::INT)::DOUBLE               AS p_bdy,
               SUM((faced AND rb = 0)::INT) / SUM(faced::INT)::DOUBLE            AS p_dot,
               SUM((faced AND rb BETWEEN 1 AND 3)::INT) / SUM(faced::INT)::DOUBLE AS p_rot,
               SUM(br) / NULLIF(SUM(legal::INT), 0)::DOUBLE                      AS p_econ,
               SUM((legal AND br = 0)::INT) / NULLIF(SUM(legal::INT), 0)::DOUBLE AS p_bdot,
               SUM(bdy::INT) / NULLIF(SUM(legal::INT), 0)::DOUBLE                AS p_bbdy
        FROM _tw GROUP BY 1, 2 HAVING SUM(faced::INT) > 0
        """
    )

    def ph(col: str, phase: str, cond: str = "TRUE") -> str:
        return f"SUM(CASE WHEN phase = '{phase}' AND {cond} THEN {col} ELSE 0 END)"

    bat = con.execute(
        f"""
        WITH t AS (
            SELECT t.*, p.*, s.family AS bfam
            FROM _tw t JOIN _tw_par p USING (season, phase)
            LEFT JOIN _tw_styles s ON s.pid = t.bowler
            WHERE t.faced
        ),
        agg AS (
            SELECT batter AS pid,
                   COUNT(*) AS balls, COUNT(DISTINCT match_id || '/' || innings_idx) AS innings,
                   {ph("1", "powerplay")} AS b_pp, {ph("1", "middle")} AS b_mid,
                   {ph("1", "death")} AS b_death,
                   {ph("rb", "powerplay")} AS r_pp, {ph("rb", "middle")} AS r_mid,
                   {ph("rb", "death")} AS r_death,
                   {ph("p_runs", "powerplay")} AS x_pp, {ph("p_runs", "middle")} AS x_mid,
                   {ph("p_runs", "death")} AS x_death,
                   SUM(bdy::INT) AS bdy, SUM(six::INT) AS six, SUM(p_bdy) AS x_bdy,
                   SUM((rb = 0)::INT) AS dot, SUM(p_dot) AS x_dot,
                   SUM((rb BETWEEN 1 AND 3)::INT) AS rot, SUM(p_rot) AS x_rot,
                   SUM(rb) AS runs, SUM(p_runs) AS x_runs,
                   SUM(CASE WHEN bfam IN ('wrist', 'finger', 'spin') THEN 1 ELSE 0 END) AS b_spin,
                   SUM(CASE WHEN bfam IN ('wrist', 'finger', 'spin') THEN rb ELSE 0 END) AS r_spin,
                   SUM(CASE WHEN bfam IN ('wrist', 'finger', 'spin') THEN p_runs ELSE 0 END) AS x_spin,
                   SUM(CASE WHEN bfam = 'seam' THEN 1 ELSE 0 END) AS b_seam,
                   SUM(CASE WHEN bfam = 'seam' THEN rb ELSE 0 END) AS r_seam,
                   SUM(CASE WHEN bfam = 'seam' THEN p_runs ELSE 0 END) AS x_seam
            FROM t GROUP BY 1
        ),
        outs AS (SELECT player_out AS pid, COUNT(*) AS outs FROM _tw WHERE dis GROUP BY 1),
        app AS (
            SELECT match_id, innings_idx, pid, MIN(seq) AS seq FROM (
                SELECT match_id, innings_idx, batter AS pid,
                       over * 100000 + ball_in_over * 10 AS seq FROM _tw
                UNION ALL
                SELECT match_id, innings_idx, non_striker AS pid,
                       over * 100000 + ball_in_over * 10 + 1 AS seq FROM _tw
            ) WHERE pid IS NOT NULL GROUP BY 1, 2, 3
        ),
        pos AS (
            SELECT a.pid,
                   ROW_NUMBER() OVER (PARTITION BY a.match_id, a.innings_idx ORDER BY a.seq) AS pos,
                   COALESCE(f.bf, 0) AS bf
            FROM app a LEFT JOIN (
                SELECT match_id, innings_idx, batter AS pid, COUNT(*) AS bf
                FROM _tw WHERE faced GROUP BY 1, 2, 3
            ) f USING (match_id, innings_idx, pid)
        ),
        slot AS (
            -- balls-weighted: where he did most of his batting (+1 so a duck still counts)
            SELECT pid, SUM(pos * (bf + 1)) / SUM(bf + 1)::DOUBLE AS slot FROM pos GROUP BY 1
        )
        SELECT agg.*, COALESCE(outs.outs, 0) AS outs, slot.slot
        FROM agg LEFT JOIN outs USING (pid) LEFT JOIN slot USING (pid)
        """
    ).pl()

    bowl = con.execute(
        f"""
        WITH t AS (SELECT * FROM _tw JOIN _tw_par USING (season, phase) WHERE bowler IS NOT NULL)
        SELECT bowler AS pid,
               SUM(legal::INT) AS balls, COUNT(DISTINCT match_id || '/' || innings_idx) AS innings,
               {ph("legal::INT", "powerplay")} AS b_pp, {ph("legal::INT", "middle")} AS b_mid,
               {ph("legal::INT", "death")} AS b_death,
               {ph("br", "powerplay")} AS r_pp, {ph("br", "middle")} AS r_mid,
               {ph("br", "death")} AS r_death,
               {ph("p_econ", "powerplay", "legal")} AS x_pp,
               {ph("p_econ", "middle", "legal")} AS x_mid,
               {ph("p_econ", "death", "legal")} AS x_death,
               SUM((legal AND br = 0)::INT) AS dot,
               SUM(CASE WHEN legal THEN p_bdot ELSE 0 END) AS x_dot,
               SUM(bdy::INT) AS bdy, SUM(CASE WHEN legal THEN p_bbdy ELSE 0 END) AS x_bdy,
               SUM(bwkt::INT) AS wkts,
               SUM(COALESCE(wicket_kind IN ('bowled', 'lbw'), FALSE)::INT) AS w_bl,
               SUM(COALESCE(wicket_kind = 'stumped', FALSE)::INT) AS w_st
        FROM t GROUP BY 1
        """
    ).pl()

    def floats(df: pl.DataFrame) -> pl.DataFrame:  # DuckDB sums come back as decimals / int128
        return df.with_columns(pl.exclude("pid").cast(pl.Float64))

    return floats(bat), floats(bowl)


# ---------- features ----------


def _index(actual: pl.Expr, expected: pl.Expr, balls: pl.Expr) -> pl.Expr:
    """actual / expected (1.0 = par), shrunk toward par by `PHASE_PRIOR` balls."""
    raw = pl.when(expected > 0).then(actual / expected).otherwise(1.0)
    return (balls * raw + PHASE_PRIOR) / (balls + PHASE_PRIOR)


def _shrunk_share(num: str, den: str, prior: float, df: pl.DataFrame) -> pl.Expr:
    mean = float(df[num].sum() / df[den].sum()) if df[den].sum() else 0.0
    return (pl.col(num) + prior * mean) / (pl.col(den) + prior)


def _per_event(balls: str, events: str, df: pl.DataFrame) -> pl.Expr:
    """log balls per event, shrunk toward the pool rate by `EVENT_PRIOR` events."""
    rate = float(df[balls].sum() / max(df[events].sum(), 1))
    return ((pl.col(balls) + EVENT_PRIOR * rate) / (pl.col(events) + EVENT_PRIOR)).log()


def batter_features(bat: pl.DataFrame, styles: pl.DataFrame) -> pl.DataFrame:
    """One row per batter with enough evidence: pid + the `BATTER_AXES` columns."""
    if bat.is_empty():
        return pl.DataFrame()
    df = bat.filter((pl.col("balls") >= MIN_ROLE_BALLS) & (pl.col("innings") >= MIN_INNINGS))
    if df.is_empty():
        return pl.DataFrame()
    b = pl.col("balls")
    overall = _index(pl.col("runs"), pl.col("x_runs"), b)
    df = df.with_columns(
        (pl.col("b_pp") / b).alias("pp_share"),
        (pl.col("b_death") / b).alias("death_share"),
        _index(pl.col("r_pp"), pl.col("x_pp"), pl.col("b_pp")).alias("tempo_pp"),
        _index(pl.col("r_mid"), pl.col("x_mid"), pl.col("b_mid")).alias("tempo_mid"),
        _index(pl.col("r_death"), pl.col("x_death"), pl.col("b_death")).alias("tempo_death"),
        _index(pl.col("bdy"), pl.col("x_bdy"), b).alias("boundary"),
        _index(pl.col("dot"), pl.col("x_dot"), b).alias("dot"),
        _index(pl.col("rot"), pl.col("x_rot"), b).alias("rotation"),
        _shrunk_share("six", "bdy", SHARE_PRIOR_BDY, df).alias("six_share"),
        _per_event("balls", "outs", df).alias("risk"),
        overall.alias("_overall"),
    )
    # spin vs pace: each side shrunk toward his own overall tempo, not toward par
    spin = pl.when(pl.col("x_spin") > 0).then(pl.col("r_spin") / pl.col("x_spin"))
    seam = pl.when(pl.col("x_seam") > 0).then(pl.col("r_seam") / pl.col("x_seam"))
    df = df.with_columns(
        (
            (
                (
                    pl.col("b_spin") * spin.fill_null(pl.col("_overall"))
                    + PHASE_PRIOR * pl.col("_overall")
                )
                / (pl.col("b_spin") + PHASE_PRIOR)
            )
            / (
                (
                    pl.col("b_seam") * seam.fill_null(pl.col("_overall"))
                    + PHASE_PRIOR * pl.col("_overall")
                )
                / (pl.col("b_seam") + PHASE_PRIOR)
            )
        )
        .log()
        .alias("spin_vs_pace")
    )
    df = df.join(styles.select("pid", "left_hand"), on="pid", how="left")
    return df.select("pid", *[a for a, _ in BATTER_AXES])


def bowler_features(bowl: pl.DataFrame, styles: pl.DataFrame) -> pl.DataFrame:
    """One row per bowler with enough evidence: pid, family + the `BOWLER_AXES` columns."""
    if bowl.is_empty():
        return pl.DataFrame()
    df = bowl.filter((pl.col("balls") >= MIN_ROLE_BALLS) & (pl.col("innings") >= MIN_INNINGS))
    if df.is_empty():
        return pl.DataFrame()
    b = pl.col("balls")
    df = df.with_columns(
        (pl.col("b_pp") / b).alias("pp_share"),
        (pl.col("b_death") / b).alias("death_share"),
        _index(pl.col("r_pp"), pl.col("x_pp"), pl.col("b_pp")).alias("econ_pp"),
        _index(pl.col("r_mid"), pl.col("x_mid"), pl.col("b_mid")).alias("econ_mid"),
        _index(pl.col("r_death"), pl.col("x_death"), pl.col("b_death")).alias("econ_death"),
        _per_event("balls", "wkts", df).alias("strike"),
        _index(pl.col("dot"), pl.col("x_dot"), b).alias("dot"),
        _index(pl.col("bdy"), pl.col("x_bdy"), b).alias("boundary"),
        _shrunk_share("w_bl", "wkts", SHARE_PRIOR_WKT, df).alias("bowled_lbw"),
        _shrunk_share("w_st", "wkts", SHARE_PRIOR_WKT, df).alias("stumped"),
    )
    df = df.join(styles.select("pid", "family", "pace", "left_arm"), on="pid", how="left")
    return df.select("pid", "family", *[a for a, _ in BOWLER_AXES])


@lru_cache(maxsize=4)
def _features_cached(collection: str, db_path: str, stamp: float) -> dict[str, pl.DataFrame]:
    empty = {"batter": pl.DataFrame(), "bowler": pl.DataFrame(), "labels": pl.DataFrame()}
    con = duckdb.connect(db_path, read_only=True)
    try:
        styles = _styles()
        try:
            bat, bowl = _aggregates(con, collection, styles)
        except duckdb.Error as e:  # a slim DB (test fixture, old ingest) without the columns
            logger.warning(f"style twins: no ball-by-ball features for {collection}: {e}")
            return empty
        try:
            labels = pl.DataFrame(
                list(label_map(con, collection).items()),
                schema={"pid": pl.String, "name": pl.String},
                orient="row",
            )
        except duckdb.Error:
            labels = pl.DataFrame(schema={"pid": pl.String, "name": pl.String})
    finally:
        con.close()
    return {
        "batter": batter_features(bat, styles),
        "bowler": bowler_features(bowl, styles),
        "labels": labels,
    }


def features(collection: str, db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, pl.DataFrame]:
    """{'batter', 'bowler', 'labels'} feature tables for a collection (computed once per DB file)."""
    p = Path(db_path)
    if not p.exists():
        return {"batter": pl.DataFrame(), "bowler": pl.DataFrame(), "labels": pl.DataFrame()}
    return _features_cached(collection, str(p), p.stat().st_mtime)


# ---------- scaling + search ----------


def robust_z(X: np.ndarray) -> np.ndarray:
    """Column-wise (x - median) / (1.4826 * MAD), falling back to the SD when the MAD is 0, clipped
    at +/-3; a missing value lands on 0 (the pool median: neutral, not an extreme)."""
    X = np.where(np.isfinite(X), X, np.nan)
    med = np.nanmedian(X, axis=0)
    mad = 1.4826 * np.nanmedian(np.abs(X - med), axis=0)
    sd = np.nanstd(X, axis=0)
    scale = np.where(mad > 1e-9, mad, np.where(sd > 1e-9, sd, 1.0))
    Z = np.clip((X - med) / scale, -3.0, 3.0)
    return np.where(np.isnan(Z), 0.0, Z)


def _scaled(df: pl.DataFrame, axes: tuple[tuple[str, float], ...]) -> tuple[np.ndarray, np.ndarray]:
    cols = [a for a, _ in axes]
    X = df.select(pl.col(c).cast(pl.Float64) for c in cols).to_numpy()
    Z = np.empty_like(X)
    for j, c in enumerate(cols):
        col = X[:, [j]]
        if c in CATEGORICAL:
            # 0/1 (or 0 / 0.5 / 1 for pace) -> a fixed gap; unknown sits in the middle
            v = np.where(np.isfinite(col), col, 0.5)
            Z[:, [j]] = (v - 0.5) * CATEGORICAL_GAP
        else:
            Z[:, [j]] = robust_z(col)
    w = np.array([wt for _, wt in axes], dtype=float)
    return Z, w


@dataclass
class _Pool:
    Z: np.ndarray
    w: np.ndarray
    keys: list[str]
    group: list  # batters: slot; bowlers: family


class TwinIndex:
    """The style-twin search for one role in one collection. Build it once per collection and
    `query` it per player (the profile export does this)."""

    def __init__(
        self,
        role: str = "batter",
        collection: str = "ipl",
        db_path: Path | str = DEFAULT_DB_PATH,
    ) -> None:
        if role not in ("batter", "bowler"):
            raise ValueError(f"role must be 'batter' or 'bowler', got {role!r}")
        self.role = role
        self.names: list[str] = []  # player keys (pid), one per vector
        self.labels: dict[str, str] = {}  # pid -> scorecard name
        self._pool: _Pool | None = None
        feats = features(collection, db_path)
        df = feats[role]
        lab = feats["labels"]
        if not lab.is_empty():
            self.labels = dict(zip(lab["pid"].to_list(), lab["name"].to_list(), strict=True))
        if df.is_empty():
            return
        axes = BATTER_AXES if role == "batter" else BOWLER_AXES
        Z, w = _scaled(df, axes)
        self.names = df["pid"].to_list()
        group = df["slot"].to_list() if role == "batter" else df["family"].to_list()
        self._pool = _Pool(Z, w, self.names, group)
        self._idx = {n: i for i, n in enumerate(self.names)}
        self.table = df  # the unscaled features, for inspection

    def _find(self, who: str) -> int:
        """A vector by player key, else by scorecard name (the first player with that name)."""
        if who in self._idx:
            return self._idx[who]
        for key, nm in self.labels.items():
            if nm == who and key in self._idx:
                return self._idx[key]
        raise KeyError(f"{who!r} not in {self.role} feature table; sample: {self.names[:5]}")

    def _tiers(self, i: int) -> np.ndarray:
        """0 = first choice, 1 = allowed after, inf = never (a hard category gate)."""
        g = self._pool.group
        n = len(g)
        if self.role == "batter":
            me = g[i]
            return np.array(
                [0.0 if (me is None or x is None or abs(x - me) <= SLOT_GAP) else 1.0 for x in g]
            )
        me = g[i]
        out = np.empty(n)
        for j, x in enumerate(g):
            if me is None or x is None:
                out[j] = 0.0 if (me is None and x is None) else np.inf
            elif _category(me) != _category(x):
                out[j] = np.inf
            elif me == x or me == "spin" or x == "spin":
                out[j] = 0.0
            else:
                out[j] = 1.0  # wrist vs finger
        return out

    def query(self, name: str, k: int = 10) -> pl.DataFrame:
        """The `k` closest players to one (by registry id, or scorecard name): `name`,
        `cricsheet_id`, `distance` (1 - alike) and `alike` (0-100)."""
        if self._pool is None:
            return pl.DataFrame()
        i = self._find(name)
        P = self._pool
        d2 = ((P.Z - P.Z[i]) ** 2 * P.w).sum(axis=1) / P.w.sum()
        alike = np.clip(1.0 - np.sqrt(d2) / 2.0, 0.0, 1.0)
        tiers = self._tiers(i)
        tiers[i] = np.inf  # never his own twin
        order = np.lexsort((-alike, tiers))
        rows = []
        for j in order:
            if not np.isfinite(tiers[j]) or len(rows) >= k:
                break
            key = self.names[j]
            rows.append(
                {
                    "name": self.labels.get(key) or key.removeprefix("unresolved:"),
                    "cricsheet_id": None if key.startswith("unresolved:") else key,
                    "distance": round(float(1.0 - alike[j]), 4),
                    "alike": round(float(100.0 * alike[j]), 1),
                }
            )
        return pl.DataFrame(rows)


def style_twin(
    name: str,
    role: str = "batter",
    k: int = 10,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pl.DataFrame:
    return TwinIndex(role, collection, db_path).query(name, k)
