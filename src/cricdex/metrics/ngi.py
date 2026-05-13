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
    X = df.select(FEATURES).with_columns(pl.all().cast(pl.Float32)).to_numpy()
    y = df["batting_won"].cast(pl.Int8).to_numpy()
    return X, y, df


def _train_wp(X: np.ndarray, y: np.ndarray, seed: int = 42):
    import xgboost as xgb

    # Train/val split by row (fast — full cross-match split is overkill
    # for the first ship; v2 can do a match-id holdout).
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    cut = int(0.85 * len(y))
    tr, va = idx[:cut], idx[cut:]
    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="binary:logistic",
        tree_method="hist",
        n_jobs=-1,
        random_state=seed,
    )
    model.fit(X[tr], y[tr], eval_set=[(X[va], y[va])], verbose=False)
    val_acc = float((model.predict(X[va]) == y[va]).mean())
    logger.info(f"WP model val accuracy: {val_acc:.3f} on {len(va)} balls")
    return model, val_acc


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
    """Fit WP, compute ΔWP per ball, aggregate to a career NGI table."""
    with duckdb.connect(str(db_path), read_only=True) as con:
        state = _build_state_table(con, collection)
        if state.is_empty():
            logger.warning(f"no usable balls for {collection}")
            return {"career": pl.DataFrame(), "val_acc": None}

        X, y, state = _features_and_label(state)
        model, val_acc = _train_wp(X, y, seed=seed)
        scored = _delta_wp(model, state)
        career = _per_player(scored, con)

    return {"career": career, "val_acc": val_acc, "n_balls": state.height}
