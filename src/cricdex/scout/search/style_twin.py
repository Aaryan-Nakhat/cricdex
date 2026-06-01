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
    runs_per_6_after_dot                    (recoverability)
    counter_attack_sr                       (partner-wicket survival SR)
    bdr_pct                                 (boundary dependency)
    intent_curve sr by bucket (6 axes)      (early-vs-late aggression)
    bayes_skill                             (latent batter skill)
bowler:
    sticky wicket_rate_pct                  (pressure-to-wicket rate)
    bayes_skill                             (latent bowler skill)

Missing axes → 0 (centered later via z-score).

Output: `style_twin(name, role, k=10)` returns top-k closest rows.
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


def _bowler_intent_curve(intent: pl.DataFrame) -> pl.DataFrame:
    """Spread the long-format intent_curve into one SR column per bucket."""
    if intent.is_empty():
        return pl.DataFrame()
    return (
        intent.pivot(
            on="ball_bucket",
            index="batter",
            values="sr",
            aggregate_function="first",
        )
        .rename({c: f"intent_sr_{c}" for c in intent["ball_bucket"].unique().to_list()})
        .rename({"batter": "name"})
    )


def build_batter_features(collection: str, db_path: Path | str) -> pl.DataFrame:
    pr = _load_json(f"pressure_runs_{collection}.json")
    rec = _load_json(f"recoverability_{collection}.json")
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
            pl.col("batter").alias("name"),
            "pressure_density",
            "pressure_sr_per_100_balls",
            "pct_balls_under_pressure",
        )
    )
    df = pr

    if not rec.is_empty():
        df = df.join(
            rec.select(pl.col("batter").alias("name"), "runs_per_6_after_dot"),
            on="name",
            how="left",
        )
    if not ca.is_empty():
        df = df.join(
            ca.select(pl.col("batter").alias("name"), "counter_attack_sr"),
            on="name",
            how="left",
        )
    if not bdr.is_empty():
        df = df.join(
            bdr.select(pl.col("batter").alias("name"), "bdr_pct"),
            on="name",
            how="left",
        )
    if not intent.is_empty():
        wide = _bowler_intent_curve(intent)
        if not wide.is_empty():
            df = df.join(wide, on="name", how="left")
    if not ratings.is_empty():
        # ratings is keyed by cricsheet_id; bridge via people register
        people = _people_index(db_path)
        if not people.is_empty():
            r_batter = (
                ratings.filter(pl.col("role") == "batter")
                .select("cricsheet_id", pl.col("skill").alias("bayes_skill"))
                .join(people, on="cricsheet_id", how="left")
                .select(pl.col("unique_name").alias("name"), "bayes_skill")
            )
            df = df.join(r_batter, on="name", how="left")
    return df.with_columns(pl.lit("batter").alias("role"))


def build_bowler_features(collection: str, db_path: Path | str) -> pl.DataFrame:
    sticky = _load_json(f"sticky_dot_pressure_{collection}.json")
    ratings = _load_json(f"scout_ratings_{collection}.json")
    if sticky.is_empty() and ratings.is_empty():
        return pl.DataFrame()
    df = (
        sticky.select(
            pl.col("bowler").alias("name"),
            "wicket_rate_pct",
            "pressure_balls",
        )
        if not sticky.is_empty()
        else pl.DataFrame()
    )
    if not ratings.is_empty():
        people = _people_index(db_path)
        if not people.is_empty():
            r_bowler = (
                ratings.filter(pl.col("role") == "bowler")
                .select("cricsheet_id", pl.col("skill").alias("bayes_skill"))
                .join(people, on="cricsheet_id", how="left")
                .select(pl.col("unique_name").alias("name"), "bayes_skill")
            )
            df = df.join(r_bowler, on="name", how="left") if not df.is_empty() else r_bowler
    return df.with_columns(pl.lit("bowler").alias("role"))


# ---------- search ----------


def _vectorise(df: pl.DataFrame) -> tuple[np.ndarray, list[str], list[str]]:
    if df.is_empty():
        return np.empty((0, 0)), [], []
    df = df.fill_null(0.0)
    names = df["name"].to_list()
    feature_cols = [c for c in df.columns if c not in ("name", "role")]
    X = df.select(feature_cols).to_numpy(allow_copy=True).astype(float)
    return X, names, feature_cols


def style_twin(
    name: str,
    role: str = "batter",
    k: int = 10,
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pl.DataFrame:
    if role == "batter":
        df = build_batter_features(collection, db_path)
    elif role == "bowler":
        df = build_bowler_features(collection, db_path)
    else:
        raise ValueError(f"role must be 'batter' or 'bowler', got {role!r}")
    if df.is_empty():
        return pl.DataFrame()

    X, names, _ = _vectorise(df)
    if name not in names:
        raise KeyError(f"{name!r} not in {role} feature table; sample: {names[:5]}")
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)
    nn = NearestNeighbors(n_neighbors=min(k + 1, len(names)), metric="cosine")
    nn.fit(X_s)
    idx = names.index(name)
    dists, ids = nn.kneighbors(X_s[idx : idx + 1])
    out_rows = []
    for d, j in zip(dists[0], ids[0], strict=True):
        if j == idx:
            continue
        out_rows.append({"name": names[j], "distance": float(d)})
    return pl.DataFrame(out_rows).head(k)
