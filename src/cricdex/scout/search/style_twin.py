"""Style-twin search via k-NN over per-player metric vectors.

We build a feature vector for every batter / bowler from the JSON
outputs of the metrics pipeline (data/metrics/*.json) and the scout
Bayesian ratings, then offer a "find players who play like X" k-NN
query. The vector axes are deliberately the metrics CricDex publishes —
this keeps the twin notion grounded in what we'll show on a player
card, rather than a black-box embedding.

Input feature axes (today)
--------------------------
batter:
    pressure_runs / chase_balls_faced       (chase clutch density)
    pressure_sr_per_100_balls               (chase clutch efficiency)
    pct_balls_under_pressure                (chase pressure exposure)
    runs_per_6_after_dot                    (dot_ball_recovery)
    counter_attack_sr                       (partner-wicket survival SR)
    bdr_pct                                 (boundary dependency)
    intent_curve sr by bucket (6 axes)      (early-vs-late aggression)
    bayes_skill                             (latent batter skill)
bowler:
    sticky wicket_rate_pct                  (pressure-to-wicket rate)
    pressure_balls                          (pressure-spell volume)
    bayes_skill                             (latent bowler skill)

A missing (or non-finite) axis is filled with that axis's mean across
players before scaling, so after z-scoring it sits at 0 — neutral, not an
extreme low. An axis nobody has is dropped.

Players are keyed by registry id (`pid`: the `cricsheet_id` the metric rows carry, else
`unresolved:<name>`), so two players sharing a scorecard name are two vectors.

Output: `style_twin(name, role, k=10)` returns top-k closest rows (`name`, `cricsheet_id`,
`distance`).
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from loguru import logger
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from cricdex.config import DATA_DIR

METRIC_DIR = DATA_DIR / "metrics"
DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"


# ---------- vector assembly ----------


def _load_json(name: str) -> pl.DataFrame:
    path = METRIC_DIR / name
    if not path.exists():
        logger.warning(f"{path} missing — skipping")
        return pl.DataFrame()
    with open(path) as f:
        rows = json.load(f)
    # infer_schema_length=None — ratings JSON mixes batter-only and
    # bowler-only columns, so a truncated scan trips on the first
    # bowler row.
    return pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()


def _people_index(db_path: Path | str) -> pl.DataFrame:
    if not Path(db_path).exists():
        return pl.DataFrame()
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "people" not in tables:
            return pl.DataFrame()
        return con.execute("SELECT identifier AS cricsheet_id, unique_name FROM people").pl()
    finally:
        con.close()


def _pid(df: pl.DataFrame, name_col: str) -> pl.Expr:
    """A row's player key: `cricsheet_id`, else `unresolved:<scorecard name>` (older files)."""
    unresolved = pl.lit("unresolved:") + pl.col(name_col).cast(pl.String)
    if "cricsheet_id" not in df.columns:
        return unresolved.alias("pid")
    return pl.coalesce(pl.col("cricsheet_id"), unresolved).alias("pid")


def _batter_intent_curve(intent: pl.DataFrame) -> pl.DataFrame:
    """Spread the long-format batter intent_curve into one SR column per bucket."""
    if intent.is_empty():
        return pl.DataFrame()
    return (
        intent.with_columns(_pid(intent, "batter"))
        .pivot(
            on="ball_bucket",
            index="pid",
            values="sr",
            aggregate_function="first",
        )
        .rename({c: f"intent_sr_{c}" for c in intent["ball_bucket"].unique().to_list()})
    )


def build_batter_features(collection: str, db_path: Path | str) -> pl.DataFrame:
    pr = _load_json(f"pressure_runs_{collection}.json")
    rec = _load_json(f"dot_ball_recovery_{collection}.json")
    ca = _load_json(f"counter_attack_{collection}.json")
    bdr = _load_json(f"boundary_dependency_{collection}.json")
    intent = _load_json(f"intent_curve_{collection}.json")
    ratings = _load_json(f"scout_ratings_{collection}.json")

    if pr.is_empty():
        return pl.DataFrame()

    pr = (
        pr.with_columns(
            pl.col("pressure_runs").cast(pl.Float64, strict=False),
            pl.col("chase_balls_faced").cast(pl.Float64, strict=False),
            pl.col("pressure_sr_per_100_balls").cast(pl.Float64, strict=False),
            pl.col("pct_balls_under_pressure").cast(pl.Float64, strict=False),
        )
        .with_columns(
            (pl.col("pressure_runs") / pl.col("chase_balls_faced")).alias("pressure_density"),
        )
        .select(
            _pid(pr, "batter"),
            pl.col("batter").alias("name"),
            "pressure_density",
            "pressure_sr_per_100_balls",
            "pct_balls_under_pressure",
        )
    )
    df = pr

    if not rec.is_empty():
        df = df.join(
            rec.select(_pid(rec, "batter"), "runs_per_6_after_dot"),
            on="pid",
            how="left",
        )
    if not ca.is_empty():
        df = df.join(
            ca.select(_pid(ca, "batter"), "counter_attack_sr"),
            on="pid",
            how="left",
        )
    if not bdr.is_empty():
        df = df.join(
            bdr.select(_pid(bdr, "batter"), "bdr_pct"),
            on="pid",
            how="left",
        )
    if not intent.is_empty():
        wide = _batter_intent_curve(intent)
        if not wide.is_empty():
            df = df.join(wide, on="pid", how="left")
    if not ratings.is_empty():
        r_batter = _rated(ratings, "batter", db_path)
        if r_batter is not None:
            df = df.join(r_batter, on="pid", how="left")
    return df.with_columns(pl.lit("batter").alias("role"))


# A player is only indexed in a role he has this many balls in (rated balls): a bowler's handful of
# innings at No. 10 made him a "batting twin" of top-order batters (roadmap 25).
MIN_ROLE_BALLS = 120


def _role_volume(ratings: pl.DataFrame, role: str) -> pl.DataFrame | None:
    """(pid, balls) for one role from the ratings, or None when the file can't say."""
    if (
        ratings.is_empty()
        or "cricsheet_id" not in ratings.columns
        or "balls" not in ratings.columns
    ):
        return None
    return ratings.filter(pl.col("role") == role).select(
        pl.col("cricsheet_id").alias("pid"), pl.col("balls").cast(pl.Float64, strict=False)
    )


def _rated(ratings: pl.DataFrame, role: str, db_path: Path | str) -> pl.DataFrame | None:
    """(pid, bayes_skill) for one role. Ratings are keyed by the player key (`cricsheet_id`: the
    registry id, or `unresolved:<name>`) — the same key the metric rows carry."""
    r = ratings.filter(pl.col("role") == role)
    if "cricsheet_id" not in r.columns:
        return None
    return r.select(pl.col("cricsheet_id").alias("pid"), pl.col("skill").alias("bayes_skill"))


def build_bowler_features(collection: str, db_path: Path | str) -> pl.DataFrame:
    sticky = _load_json(f"pressure_conversion_{collection}.json")
    ratings = _load_json(f"scout_ratings_{collection}.json")
    if sticky.is_empty() and ratings.is_empty():
        return pl.DataFrame()
    df = (
        sticky.select(
            _pid(sticky, "bowler"),
            pl.col("bowler").alias("name"),
            "wicket_rate_pct",
            "pressure_balls",
        )
        if not sticky.is_empty()
        else pl.DataFrame()
    )
    if not ratings.is_empty():
        r_bowler = _rated(ratings, "bowler", db_path)
        if r_bowler is not None:
            df = df.join(r_bowler, on="pid", how="left") if not df.is_empty() else r_bowler
    return df.with_columns(pl.lit("bowler").alias("role"))


# ---------- search ----------


def _vectorise(df: pl.DataFrame) -> tuple[np.ndarray, list[str], list[str]]:
    if df.is_empty():
        return np.empty((0, 0)), [], []
    names = df["pid" if "pid" in df.columns else "name"].to_list()
    feature_cols = [c for c in df.columns if c not in ("pid", "name", "role")]
    X = df.select(pl.col(c).cast(pl.Float64, strict=False) for c in feature_cols).to_numpy()
    X = np.where(np.isfinite(X), X, np.nan)  # nulls and x/0 alike are "missing"
    keep = ~np.isnan(X).all(axis=0)
    X, feature_cols = X[:, keep], [c for c, k in zip(feature_cols, keep, strict=True) if k]
    # Mean-impute in raw units: a missing SR filled with 0 would be an extreme outlier.
    X = np.where(np.isnan(X), np.nanmean(X, axis=0), X)
    return X, names, feature_cols


class TwinIndex:
    """The k-NN for one role's feature table, fitted once. Build it once per
    collection and `query` it per player (the profile export does this —
    `style_twin` refits the whole table on every call)."""

    def __init__(
        self,
        role: str = "batter",
        collection: str = "ipl",
        db_path: Path | str = DEFAULT_DB_PATH,
    ) -> None:
        if role == "batter":
            df = build_batter_features(collection, db_path)
        elif role == "bowler":
            df = build_bowler_features(collection, db_path)
        else:
            raise ValueError(f"role must be 'batter' or 'bowler', got {role!r}")
        self.role = role
        self.names: list[str] = []  # player keys (pid), one per vector
        self.labels: dict[str, str] = {}  # pid -> scorecard name
        self._nn: NearestNeighbors | None = None
        if df.is_empty():
            return
        # per-role pool: only players with real volume in this role
        ratings = _load_json(f"scout_ratings_{collection}.json")
        vol = _role_volume(ratings, role)
        if vol is not None and not vol.is_empty():
            keep = set(vol.filter(pl.col("balls") >= MIN_ROLE_BALLS)["pid"].to_list())
            df = df.filter(pl.col("pid").is_in(list(keep)))
            if df.is_empty():
                return
        # pid -> scorecard name: the metric rows' names, else the ratings' (a rated-only bowler)
        if {"cricsheet_id", "unique_name"} <= set(ratings.columns):
            for k, n in ratings.select("cricsheet_id", "unique_name").iter_rows():
                if k and n:
                    self.labels.setdefault(k, n)
        if "name" in df.columns:
            for k, n in zip(df["pid"].to_list(), df["name"].to_list(), strict=True):
                if n:
                    self.labels[k] = n
        X, self.names, _ = _vectorise(df)
        # every axis z-scored first (StandardScaler), then cosine distance (0 = same shape; the
        # CLI / TUI / web read 1 - distance as "% alike")
        self._X = StandardScaler().fit_transform(X)
        self._nn = NearestNeighbors(metric="cosine").fit(self._X)
        self._idx = {n: i for i, n in enumerate(self.names)}

    def _find(self, who: str) -> int:
        """A vector by player key, else by scorecard name (the first player with that name)."""
        if who in self._idx:
            return self._idx[who]
        for key, nm in self.labels.items():
            if nm == who and key in self._idx:
                return self._idx[key]
        raise KeyError(f"{who!r} not in {self.role} feature table; sample: {self.names[:5]}")

    def query(self, name: str, k: int = 10) -> pl.DataFrame:
        """The `k` nearest players to one (by registry id, or scorecard name)."""
        if self._nn is None:
            return pl.DataFrame()
        idx = self._find(name)
        dists, ids = self._nn.kneighbors(
            self._X[idx : idx + 1], n_neighbors=min(k + 1, len(self.names))
        )
        out_rows = []
        for d, j in zip(dists[0], ids[0], strict=True):
            if j == idx:
                continue
            key = self.names[j]
            out_rows.append(
                {
                    "name": self.labels.get(key) or key.removeprefix("unresolved:"),
                    "cricsheet_id": None if key.startswith("unresolved:") else key,
                    "distance": float(d),
                }
            )
        return pl.DataFrame(out_rows).head(k)


def style_twin(
    name: str,
    role: str = "batter",
    k: int = 10,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pl.DataFrame:
    return TwinIndex(role, collection, db_path).query(name, k)
