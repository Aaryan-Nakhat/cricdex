"""Net Game Impact (NGI) — flagship player-impact metric.

Inspiration: WPA (Win Probability Added) from baseball. Each ball is
worth `ΔWP = WP_after − WP_before`. A batter who scores 4 in a tight
chase-finish gets credited a much larger ΔWP than the same 4 in a
dead opening over. Wickets, dot balls, boundaries all flow through
the same currency.

Pipeline
--------
1. **Win-probability model.** Train a gradient-boosted binary
   classifier on Cricsheet ball-by-ball: per-ball state features →
   P(batting team wins). Labels come from
   `matches.outcome_winner`. Drop tied / no-result / D/L-adjusted
   matches from training.

2. **Score every ball.** WP_before is the model's prediction at the
   state just before the delivery; WP_after is the prediction after
   applying the delivery's runs / wicket. ΔWP = WP_after − WP_before
   (always from the batting team's perspective).

3. **Attribute ΔWP per player.**

       batter   → +ΔWP   (batter's actions raised / lowered batting
                          team's WP — credit them either way)
       bowler   → −ΔWP   (sign-flip: a wicket lowers batting WP, so
                          a *positive* outcome for the bowler)

   (Fielder credit + non-striker running attribution stay deferred —
   first cut is bat/bowl only.)

4. **Aggregate** per `(player, match)` and per `(player, career)`.

Why not just SR / Avg / wickets
-------------------------------
- A 30* finisher beats a 100* against a beaten side.
- A wicket at 200/3 chasing 220 beats one at 50/3 chasing 250.
- One currency for batters + bowlers — directly comparable.

Output
------
`compute(collection)` returns a polars DataFrame keyed by
`cricsheet_id` with columns: `name`, `role` (batter | bowler |
all_rounder), `matches`, `ngi_total`, `ngi_per_match`, `ngi_batting`,
`ngi_bowling`.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from loguru import logger

from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

FEATURES = [
    "innings_idx",
    "balls_remaining",
    "wickets_left",
    "score_before",
    "target",  # 0 in innings 1, real target in innings 2
    "runs_needed",  # 0 in innings 1
    "required_rr",  # 0 in innings 1
    "current_rr",
    "innings1_total",  # final total of innings 1 (helps innings 2 calibration)
    "current_rr_minus_venue",  # RR vs venue avg — Bengaluru high-scoring ≠ Chennai slow
]


def _build_state_table(con: duckdb.DuckDBPyConnection, collection: str) -> pl.DataFrame:
    """One row per ball with the win-probability features and the
    binary label (batting team won the match)."""
    safe = collection.replace("-", "_")
    return con.execute(
        f"""
        WITH balls_seq AS (
            SELECT
                b.match_id,
                b.innings_idx,
                b.batting_team,
                b.bowling_team,
                b.over,
                b.ball_in_over,
                b.batter,
                b.bowler,
                b.runs_total,
                b.wicket_kind,
                ROW_NUMBER() OVER (
                    PARTITION BY b.match_id, b.innings_idx
                    ORDER BY b.over, b.ball_in_over
                ) AS ball_idx_in_innings,
                COUNT(*) OVER (
                    PARTITION BY b.match_id, b.innings_idx
                ) AS total_balls_in_innings,
                SUM(b.runs_total) OVER (
                    PARTITION BY b.match_id, b.innings_idx
                    ORDER BY b.over, b.ball_in_over
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) AS score_before,
                SUM(CASE WHEN b.wicket_kind IS NOT NULL THEN 1 ELSE 0 END) OVER (
                    PARTITION BY b.match_id, b.innings_idx
                    ORDER BY b.over, b.ball_in_over
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) AS wickets_before
            FROM balls_{safe} b
            WHERE b.batter IS NOT NULL
        ),
        innings1 AS (
            SELECT match_id, SUM(runs_total) AS innings1_total
            FROM balls_{safe}
            WHERE innings_idx = 1
            GROUP BY match_id
        )
        SELECT
            s.match_id,
            s.innings_idx,
            s.batting_team,
            s.bowling_team,
            s.over,
            s.ball_in_over,
            s.batter,
            s.bowler,
            s.runs_total,
            s.wicket_kind,
            COALESCE(s.score_before, 0)                 AS score_before,
            COALESCE(s.wickets_before, 0)               AS wickets_before,
            s.ball_idx_in_innings,
            s.total_balls_in_innings,
            (s.total_balls_in_innings - s.ball_idx_in_innings + 1) AS balls_remaining,
            (10 - COALESCE(s.wickets_before, 0))        AS wickets_left,
            CASE WHEN s.innings_idx = 2
                 THEN COALESCE(i1.innings1_total, 0) + 1
                 ELSE 0 END                             AS target,
            CASE WHEN s.innings_idx = 2
                 THEN GREATEST(
                     0,
                     COALESCE(i1.innings1_total, 0) + 1 - COALESCE(s.score_before, 0)
                 )
                 ELSE 0 END                             AS runs_needed,
            COALESCE(i1.innings1_total, 0)              AS innings1_total,
            m.venue,
            m.outcome_winner,
            m.outcome_by_runs,
            m.outcome_by_wickets,
            m.result
        FROM balls_seq s
        LEFT JOIN innings1 i1 ON i1.match_id = s.match_id
        LEFT JOIN matches_{safe} m ON m.match_id = s.match_id
        WHERE COALESCE(m.result, '') NOT IN ('no result', 'tie')
          AND m.outcome_winner IS NOT NULL
        """
    ).pl()


def _features_and_label(state: pl.DataFrame) -> tuple[np.ndarray, np.ndarray, pl.DataFrame]:
    df = state.with_columns(
        pl.when(pl.col("ball_idx_in_innings") > 1)
        .then(pl.col("score_before") * 6.0 / (pl.col("ball_idx_in_innings") - 1).cast(pl.Float64))
        .otherwise(0.0)
        .alias("current_rr"),
        pl.when((pl.col("innings_idx") == 2) & (pl.col("balls_remaining") > 0))
        .then(pl.col("runs_needed").cast(pl.Float64) * 6.0 / pl.col("balls_remaining"))
        .otherwise(0.0)
        .alias("required_rr"),
        (pl.col("batting_team") == pl.col("outcome_winner")).alias("batting_won"),
    )
    # Venue average run rate: mean of (final innings total × 6 / total balls)
    # per venue, computed across all observations. Subtracted from current_rr
    # to give the model "this RR is fast / slow for THIS ground".
    venue_avg = (
        df.group_by("venue")
        .agg(
            (pl.col("score_before").max() + pl.col("runs_total").sum()).alias("_total_runs"),
            pl.col("total_balls_in_innings").max().alias("_total_balls"),
        )
        .with_columns(
            (
                pl.col("_total_runs") * 6.0 / pl.max_horizontal([pl.lit(1), pl.col("_total_balls")])
            ).alias("venue_avg_rr")
        )
        .select(["venue", "venue_avg_rr"])
    )
    df = df.join(venue_avg, on="venue", how="left").with_columns(
        (pl.col("current_rr") - pl.col("venue_avg_rr").fill_null(7.5)).alias(
            "current_rr_minus_venue"
        )
    )

    X = df.select(FEATURES).with_columns(pl.all().cast(pl.Float32)).to_numpy()
    y = df["batting_won"].cast(pl.Int8).to_numpy()
    return X, y, df


class _CalibratedWP:
    """XGBoost classifier + isotonic calibrator over its raw probabilities."""

    def __init__(self, xgb_model, calibrator):
        self.xgb_model = xgb_model
        self.calibrator = calibrator

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raw = self.xgb_model.predict_proba(X)[:, 1]
        cal = self.calibrator.transform(raw)
        return np.stack([1.0 - cal, cal], axis=1)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(np.int64)


def _train_wp(
    X: np.ndarray,
    y: np.ndarray,
    match_ids: np.ndarray,
    seed: int = 42,
):
    """Match-id holdout split + XGBoost + isotonic calibration.

    Returns the calibrated model plus a metrics dict (val_acc, brier,
    log_loss, reliability buckets).
    """
    import xgboost as xgb
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss, log_loss

    rng = np.random.default_rng(seed)
    unique_matches = np.unique(match_ids)
    rng.shuffle(unique_matches)
    cut = int(0.85 * len(unique_matches))
    train_matches = set(unique_matches[:cut].tolist())
    tr_mask = np.array([m in train_matches for m in match_ids])
    va_mask = ~tr_mask

    base = xgb.XGBClassifier(
        n_estimators=600,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="binary:logistic",
        tree_method="hist",
        early_stopping_rounds=30,
        eval_metric="logloss",
        n_jobs=-1,
        random_state=seed,
    )
    base.fit(
        X[tr_mask],
        y[tr_mask],
        eval_set=[(X[va_mask], y[va_mask])],
        verbose=False,
    )

    val_raw = base.predict_proba(X[va_mask])[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(val_raw, y[va_mask])
    val_cal = calibrator.transform(val_raw)

    val_pred = (val_cal >= 0.5).astype(np.int64)
    val_acc = float((val_pred == y[va_mask]).mean())
    brier = float(brier_score_loss(y[va_mask], val_cal))
    ll = float(log_loss(y[va_mask], np.clip(val_cal, 1e-6, 1 - 1e-6)))

    # 10-bucket reliability table: predicted_bin → (count, mean_pred, mean_actual)
    bins = np.linspace(0.0, 1.0, 11)
    reliability = []
    for i in range(10):
        mask = (val_cal >= bins[i]) & (val_cal < bins[i + 1])
        if i == 9:  # include 1.0 in last bucket
            mask = (val_cal >= bins[i]) & (val_cal <= bins[i + 1])
        if mask.any():
            reliability.append(
                {
                    "bucket": f"[{bins[i]:.1f}, {bins[i + 1]:.1f})",
                    "count": int(mask.sum()),
                    "mean_predicted": float(val_cal[mask].mean()),
                    "mean_actual": float(y[va_mask][mask].mean()),
                }
            )

    n_train_matches = len(train_matches)
    n_val_matches = len(unique_matches) - n_train_matches
    logger.info(
        f"WP v2: val_acc={val_acc:.3f} brier={brier:.4f} log_loss={ll:.4f} "
        f"on {va_mask.sum()} balls from {n_val_matches} held-out matches "
        f"(train {n_train_matches} matches)"
    )
    metrics = {
        "val_acc": val_acc,
        "brier": brier,
        "log_loss": ll,
        "n_train_matches": n_train_matches,
        "n_val_matches": n_val_matches,
        "n_val_balls": int(va_mask.sum()),
        "reliability": reliability,
    }
    return _CalibratedWP(base, calibrator), metrics


def _delta_wp(model, state: pl.DataFrame) -> pl.DataFrame:
    """Predict WP_before for every ball, then WP_after by applying the
    delivery's runs + wicket to the state. ΔWP is from the batting
    team's perspective."""
    df = state
    wp_before_features = df.select(FEATURES).with_columns(pl.all().cast(pl.Float32)).to_numpy()
    wp_before = model.predict_proba(wp_before_features)[:, 1]

    after = df.with_columns(
        (pl.col("score_before") + pl.col("runs_total")).alias("score_before"),
        (
            pl.col("wickets_before")
            + pl.when(pl.col("wicket_kind").is_not_null()).then(1).otherwise(0)
        ).alias("wickets_before"),
        (pl.col("ball_idx_in_innings") + 1).alias("ball_idx_in_innings"),
        (pl.col("balls_remaining") - 1).alias("balls_remaining"),
    )
    after = after.with_columns(
        (10 - pl.col("wickets_before")).alias("wickets_left"),
        pl.when(pl.col("innings_idx") == 2)
        .then(pl.max_horizontal([pl.lit(0), pl.col("target") - pl.col("score_before")]))
        .otherwise(0)
        .alias("runs_needed"),
        pl.when(pl.col("ball_idx_in_innings") > 1)
        .then(
            pl.col("score_before")
            * 6.0
            / pl.max_horizontal([pl.lit(1), pl.col("ball_idx_in_innings") - 1]).cast(pl.Float64)
        )
        .otherwise(0.0)
        .alias("current_rr"),
        pl.when((pl.col("innings_idx") == 2) & (pl.col("balls_remaining") > 0))
        .then(pl.col("runs_needed").cast(pl.Float64) * 6.0 / pl.col("balls_remaining"))
        .otherwise(0.0)
        .alias("required_rr"),
    )
    # Recompute the venue-relative RR after the delivery; innings1_total
    # stays unchanged across the ball so it's preserved by the prior
    # with_columns calls.
    after = after.with_columns(
        (pl.col("current_rr") - pl.col("venue_avg_rr").fill_null(7.5)).alias(
            "current_rr_minus_venue"
        )
    )

    wp_after_features = after.select(FEATURES).with_columns(pl.all().cast(pl.Float32)).to_numpy()
    wp_after = model.predict_proba(wp_after_features)[:, 1]
    # End-of-innings: WP collapses to 1 if batting team won
    end_of_innings = df["balls_remaining"].to_numpy() == 1
    if end_of_innings.any():
        wp_after = wp_after.copy()
        won = df["batting_won"].cast(pl.Int8).to_numpy().astype(bool)
        wp_after[end_of_innings] = won[end_of_innings].astype(float)

    df = df.with_columns(
        pl.Series("wp_before", wp_before),
        pl.Series("wp_after", wp_after),
        pl.Series("delta_wp", wp_after - wp_before),
    )
    return df


def _per_player(df: pl.DataFrame, con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Aggregate ΔWP per (player, match), then per (player, career)."""
    batter_match = (
        df.group_by(["match_id", "batter"])
        .agg(pl.col("delta_wp").sum().alias("ngi_batting"))
        .rename({"batter": "name"})
    )
    bowler_match = (
        df.group_by(["match_id", "bowler"])
        .agg((-pl.col("delta_wp")).sum().alias("ngi_bowling"))
        .rename({"bowler": "name"})
    )
    per_match = (
        batter_match.join(bowler_match, on=["match_id", "name"], how="full", coalesce=True)
        .with_columns(
            pl.col("ngi_batting").fill_null(0.0),
            pl.col("ngi_bowling").fill_null(0.0),
        )
        .with_columns((pl.col("ngi_batting") + pl.col("ngi_bowling")).alias("ngi_total"))
    )

    career = (
        per_match.group_by("name")
        .agg(
            pl.col("match_id").n_unique().alias("matches"),
            pl.col("ngi_total").sum().alias("ngi_total"),
            pl.col("ngi_batting").sum().alias("ngi_batting"),
            pl.col("ngi_bowling").sum().alias("ngi_bowling"),
        )
        .with_columns((pl.col("ngi_total") / pl.col("matches")).alias("ngi_per_match"))
    )
    # Resolve to cricsheet_id via the people register so the table is
    # joinable with all the other scout / metrics outputs.
    people = con.execute("SELECT unique_name, identifier AS cricsheet_id FROM people").pl()
    career = career.join(people, left_on="name", right_on="unique_name", how="left")
    return career.sort("ngi_per_match", descending=True)


def compute(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    seed: int = 42,
) -> dict:
    """Fit WP, compute ΔWP per ball, aggregate to a career NGI table.

    Returns:
        career     polars DataFrame keyed by `cricsheet_id` / `name`.
        val_acc    accuracy on the match-id holdout val set.
        brier      Brier score on the val set (lower = better).
        log_loss   cross-entropy on the val set.
        reliability  list of 10 buckets {bucket, count, mean_predicted,
                     mean_actual} for a calibration plot.
        n_balls    total balls scored.
        n_val_balls / n_val_matches / n_train_matches  holdout shape.
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        state = _build_state_table(con, collection)
        if state.is_empty():
            logger.warning(f"no usable balls for {collection}")
            return {"career": pl.DataFrame(), "val_acc": None}

        X, y, state = _features_and_label(state)
        match_ids = state["match_id"].to_numpy()
        model, metrics = _train_wp(X, y, match_ids=match_ids, seed=seed)
        scored = _delta_wp(model, state)
        career = _per_player(scored, con)

    return {
        "career": career,
        "n_balls": state.height,
        **metrics,
    }
