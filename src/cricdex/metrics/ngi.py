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
   P(batting team wins). Labels come from `matches.outcome_winner`.
   Only T20 matches and the two main innings are used (super overs
   decide ties, which are dropped along with no-results). Every
   feature is known *before* the delivery — balls left come from the
   scheduled overs minus legal balls bowled, the target only exists
   in the chase. Rain-reduced (D/L) matches aren't marked in the data,
   so they stay in.

2. **Score every ball.** WP_before is the model's prediction at the
   state just before the delivery; WP_after is the prediction after
   applying the delivery's runs / wicket. ΔWP = WP_after − WP_before
   (always from the batting team's perspective). The last ball of the
   chase resolves to the result (1 or 0); the last ball of the first
   innings hands over to the chase's opening state (1 − WP of the
   chasing side), so no player is credited with the other innings.

3. **Attribute ΔWP per player.**

       batter   → +ΔWP   (batter's actions raised / lowered batting
                          team's WP — credit them either way)
       bowler   → −ΔWP   (sign-flip: a wicket lowers batting WP, so
                          a *positive* outcome for the bowler)

   (Fielder credit + non-striker running attribution stay deferred —
   first cut is bat/bowl only.)

4. **Aggregate** per `(player, match)` and per `(player, career)`.

The model is fit on 70 % of matches, early-stopped and calibrated
(isotonic) on another 15 %, and its accuracy / Brier / log-loss /
reliability are reported on the last 15 % it never saw.

Why not just SR / Avg / wickets
-------------------------------
- A 30* finisher beats a 100* against a beaten side.
- A wicket at 200/3 chasing 220 beats one at 50/3 chasing 250.
- One currency for batters + bowlers — directly comparable.

Output
------
`compute(collection)` returns a dict whose `career` is a polars
DataFrame with columns: `name`, `matches`, `ngi_total`, `ngi_batting`,
`ngi_bowling`, `ngi_per_match`, `cricsheet_id`.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from loguru import logger

from cricdex.common.sql import player_ids, table_suffix
from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"

FEATURES = [
    "innings_idx",  # 0 = first innings, 1 = chase
    "balls_remaining",  # scheduled legal balls minus legal balls bowled
    "wickets_left",
    "score_before",
    "target",  # 0 in the first innings, first-innings total + 1 in the chase
    "runs_needed",  # 0 in the first innings
    "required_rr",  # 0 in the first innings
    "current_rr",
    "current_rr_minus_venue",  # RR vs the ground's first-innings average (training matches only)
]

# Dismissals that end an innings slot; "retired hurt" doesn't (the batter can come back).
_NOT_A_WICKET = ("retired hurt",)
_ILLEGAL = ("wides", "noballs")
DEFAULT_VENUE_RR = 8.0  # fallback for a ground with no training-set first innings


def _build_state_table(con: duckdb.DuckDBPyConnection, collection: str) -> pl.DataFrame:
    """One row per delivery of the two main innings of every decided T20 match, with the state *before* the
    delivery. Nothing here depends on how the innings actually ended."""
    safe = table_suffix(collection)
    not_wicket = ", ".join(f"'{w}'" for w in _NOT_A_WICKET)
    illegal = ", ".join(f"'{e}'" for e in _ILLEGAL)
    return con.execute(
        f"""
        WITH b AS (
            SELECT *,
                   CASE WHEN extras_type IN ({illegal}) THEN 0 ELSE 1 END AS legal,
                   CASE WHEN wicket_kind IS NOT NULL AND wicket_kind NOT IN ({not_wicket})
                        THEN 1 ELSE 0 END AS is_wicket
            FROM balls_{safe}
            WHERE match_type = 'T20' AND innings_idx IN (0, 1) AND batter IS NOT NULL
        ),
        seq AS (
            SELECT
                b.*,
                COALESCE(SUM(b.legal) OVER prev, 0)      AS legal_before,
                COALESCE(SUM(b.runs_total) OVER prev, 0) AS score_before,
                COALESCE(SUM(b.is_wicket) OVER prev, 0)  AS wickets_before,
                ROW_NUMBER() OVER (
                    PARTITION BY b.match_id, b.innings_idx
                    ORDER BY b.over DESC, b.ball_in_over DESC, b.ball_id DESC
                ) = 1                                    AS is_last_ball
            FROM b
            WINDOW prev AS (
                PARTITION BY b.match_id, b.innings_idx
                ORDER BY b.over, b.ball_in_over, b.ball_id
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            )
        ),
        first_innings AS (
            SELECT match_id, SUM(runs_total) AS first_total, SUM(legal) AS first_legal
            FROM b WHERE innings_idx = 0 GROUP BY match_id
        )
        SELECT
            s.match_id, s.innings_idx, s.batting_team, s.bowling_team, s.over, s.ball_in_over, s.ball_id,
            s.batter, s.bowler, s.runs_total, s.wicket_kind, s.legal, s.is_wicket, s.is_last_ball,
            s.score_before, s.wickets_before, s.legal_before,
            GREATEST(0, COALESCE(m.overs, 20) * 6 - s.legal_before)       AS balls_remaining,
            (10 - s.wickets_before)                                        AS wickets_left,
            CASE WHEN s.innings_idx = 1 THEN f.first_total + 1 ELSE 0 END  AS target,
            CASE WHEN s.innings_idx = 1
                 THEN GREATEST(0, f.first_total + 1 - s.score_before)
                 ELSE 0 END                                                AS runs_needed,
            f.first_total, f.first_legal,
            m.venue, m.outcome_winner, m.result
        FROM seq s
        JOIN first_innings f ON f.match_id = s.match_id
        JOIN matches_{safe} m ON m.match_id = s.match_id
        WHERE COALESCE(m.result, '') NOT IN ('no result', 'tie')
          AND m.outcome_winner IS NOT NULL
        """
    ).pl()


def _venue_rates(state: pl.DataFrame, matches: set) -> pl.DataFrame:
    """Each ground's average first-innings run rate (runs × 6 / legal balls), from the given matches only."""
    first = (
        state.filter(pl.col("match_id").is_in(list(matches)))
        .select(["match_id", "venue", "first_total", "first_legal"])
        .unique("match_id")
    )
    return first.group_by("venue").agg(
        (pl.col("first_total").sum() * 6.0 / pl.col("first_legal").sum().clip(lower_bound=1)).alias(
            "venue_avg_rr"
        )
    )


def _rates(df: pl.DataFrame) -> pl.DataFrame:
    """current_rr / required_rr / current_rr_minus_venue from the state columns."""
    return df.with_columns(
        pl.when(pl.col("legal_before") > 0)
        .then(pl.col("score_before") * 6.0 / pl.col("legal_before").cast(pl.Float64))
        .otherwise(0.0)
        .alias("current_rr"),
        pl.when((pl.col("innings_idx") == 1) & (pl.col("balls_remaining") > 0))
        .then(pl.col("runs_needed").cast(pl.Float64) * 6.0 / pl.col("balls_remaining"))
        .otherwise(0.0)
        .alias("required_rr"),
    ).with_columns((pl.col("current_rr") - pl.col("venue_avg_rr")).alias("current_rr_minus_venue"))


def _features_and_label(
    state: pl.DataFrame, venue_rates: pl.DataFrame
) -> tuple[np.ndarray, np.ndarray, pl.DataFrame]:
    df = state.join(venue_rates, on="venue", how="left").with_columns(
        pl.col("venue_avg_rr").fill_null(DEFAULT_VENUE_RR),
        (pl.col("batting_team") == pl.col("outcome_winner")).alias("batting_won"),
    )
    df = _rates(df)
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


def _split_matches(match_ids: np.ndarray, seed: int = 42) -> tuple[set, set, set]:
    """Match-level 70 / 15 / 15 split: train · calibration (early stopping + isotonic) · test (reporting only)."""
    rng = np.random.default_rng(seed)
    unique = np.unique(match_ids)
    rng.shuffle(unique)
    a, b = int(0.70 * len(unique)), int(0.85 * len(unique))
    return set(unique[:a].tolist()), set(unique[a:b].tolist()), set(unique[b:].tolist())


def _train_wp(
    X: np.ndarray,
    y: np.ndarray,
    match_ids: np.ndarray,
    seed: int = 42,
    split: tuple[set, set, set] | None = None,
):
    """XGBoost on the train matches, early-stopped + isotonic-calibrated on the calibration matches, scored on the
    test matches it never saw.

    Returns the calibrated model plus a metrics dict (val_acc, brier, log_loss, reliability buckets — all on the
    test matches).
    """
    import xgboost as xgb
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss, log_loss

    train_m, cal_m, test_m = split or _split_matches(match_ids, seed)
    tr = np.isin(match_ids, list(train_m))
    ca = np.isin(match_ids, list(cal_m))
    te = np.isin(match_ids, list(test_m))

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
    base.fit(X[tr], y[tr], eval_set=[(X[ca], y[ca])], verbose=False)

    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(base.predict_proba(X[ca])[:, 1], y[ca])
    test_cal = calibrator.transform(base.predict_proba(X[te])[:, 1])
    y_te = y[te]

    val_acc = float(((test_cal >= 0.5).astype(np.int64) == y_te).mean())
    brier = float(brier_score_loss(y_te, test_cal))
    ll = float(log_loss(y_te, np.clip(test_cal, 1e-6, 1 - 1e-6), labels=[0, 1]))

    # 10-bucket reliability table: predicted_bin → (count, mean_pred, mean_actual)
    bins = np.linspace(0.0, 1.0, 11)
    reliability = []
    for i in range(10):
        mask = (test_cal >= bins[i]) & (test_cal < bins[i + 1])
        if i == 9:  # include 1.0 in last bucket
            mask = (test_cal >= bins[i]) & (test_cal <= bins[i + 1])
        if mask.any():
            reliability.append(
                {
                    "bucket": f"[{bins[i]:.1f}, {bins[i + 1]:.1f})",
                    "count": int(mask.sum()),
                    "mean_predicted": float(test_cal[mask].mean()),
                    "mean_actual": float(y_te[mask].mean()),
                }
            )

    logger.info(
        f"WP v3: test acc={val_acc:.3f} brier={brier:.4f} log_loss={ll:.4f} "
        f"on {te.sum()} balls from {len(test_m)} unseen matches "
        f"(train {len(train_m)}, calibration {len(cal_m)} matches)"
    )
    metrics = {
        "val_acc": val_acc,
        "brier": brier,
        "log_loss": ll,
        "n_train_matches": len(train_m),
        "n_cal_matches": len(cal_m),
        "n_val_matches": len(test_m),
        "n_val_balls": int(te.sum()),
        "reliability": reliability,
    }
    return _CalibratedWP(base, calibrator), metrics


def _delta_wp(model, state: pl.DataFrame) -> pl.DataFrame:
    """Predict WP_before for every ball, then WP_after by applying the
    delivery's runs + wicket to the state. ΔWP is from the batting
    team's perspective."""
    df = state
    wp_before = model.predict_proba(
        df.select(FEATURES).with_columns(pl.all().cast(pl.Float32)).to_numpy()
    )[:, 1]

    after = df.with_columns(
        (pl.col("score_before") + pl.col("runs_total")).alias("score_before"),
        (pl.col("wickets_before") + pl.col("is_wicket")).alias("wickets_before"),
        (pl.col("legal_before") + pl.col("legal")).alias("legal_before"),
        (pl.col("balls_remaining") - pl.col("legal")).clip(lower_bound=0).alias("balls_remaining"),
    ).with_columns(
        (10 - pl.col("wickets_before")).alias("wickets_left"),
        pl.when(pl.col("innings_idx") == 1)
        .then((pl.col("target") - pl.col("score_before")).clip(lower_bound=0))
        .otherwise(0)
        .alias("runs_needed"),
    )
    after = _rates(after)
    wp_after = model.predict_proba(
        after.select(FEATURES).with_columns(pl.all().cast(pl.Float32)).to_numpy()
    )[:, 1]
    wp_after = wp_after.copy()

    last = df["is_last_ball"].to_numpy()
    chase = df["innings_idx"].to_numpy() == 1
    # Last ball of the chase: the match is decided.
    end_chase = last & chase
    wp_after[end_chase] = df["batting_won"].cast(pl.Int8).to_numpy()[end_chase].astype(float)
    # Last ball of the first innings: hand over to the chase's opening state, from the first-innings side's view.
    end_first = last & ~chase
    if end_first.any():
        opening = (
            df.with_columns(pl.Series("_wp", wp_before))
            .filter(
                (pl.col("innings_idx") == 1)
                & (pl.col("legal_before") == 0)
                & (pl.col("score_before") == 0)
            )
            .group_by("match_id")
            .agg(pl.col("_wp").first())
        )
        handover = (
            df.select("match_id")
            .with_row_index("_i")
            .filter(pl.Series(end_first))
            .join(opening, on="match_id", how="left")
        )
        idx = handover["_i"].to_numpy()
        chase_wp = handover["_wp"].to_numpy()
        ok = ~np.isnan(chase_wp.astype(float))
        wp_after[idx[ok]] = 1.0 - chase_wp[ok]

    return df.with_columns(
        pl.Series("wp_before", wp_before),
        pl.Series("wp_after", wp_after),
        pl.Series("delta_wp", wp_after - wp_before),
    )


def _per_player(
    df: pl.DataFrame, con: duckdb.DuckDBPyConnection, collection: str = "ipl"
) -> pl.DataFrame:
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
    # Resolve to cricsheet_id (match registry first, then the people register) so the table is
    # joinable with all the other scout / metrics outputs.
    ids = player_ids(con, collection)
    if ids is None:
        return career.with_columns(pl.lit(None, pl.String).alias("cricsheet_id")).sort(
            "ngi_per_match", descending=True
        )
    people = con.execute(f"SELECT name, identifier AS cricsheet_id FROM {ids}").pl()
    career = career.join(people, on="name", how="left")
    return career.sort("ngi_per_match", descending=True)


WINDOW_SUFFIXES = ("_last1y", "_last3y")


def _base_collection(collection: str) -> str:
    """`ipl_last1y` → `ipl`: a time window is scored with the model trained on its whole collection."""
    for suf in WINDOW_SUFFIXES:
        if collection.endswith(suf):
            return collection[: -len(suf)]
    return collection


def compute(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    seed: int = 42,
) -> dict:
    """Fit WP, compute ΔWP per ball, aggregate to a career NGI table.

    A windowed collection (`<col>_last1y` / `_last3y`) is scored with the win-probability model trained on the
    whole `<col>` — a year of matches is far too few to fit one — and the reported metrics are that model's.

    Returns:
        career     polars DataFrame keyed by `cricsheet_id` / `name`.
        val_acc    accuracy on the test matches (never used for fitting or calibration).
        brier      Brier score on the test matches (lower = better).
        log_loss   cross-entropy on the test matches.
        reliability  list of 10 buckets {bucket, count, mean_predicted,
                     mean_actual} for a calibration plot.
        n_balls    total balls scored.
        n_val_balls / n_val_matches / n_cal_matches / n_train_matches  split shape.
    """
    base = _base_collection(collection)
    with duckdb.connect(str(db_path), read_only=True) as con:
        train_state = _build_state_table(con, base)
        state = train_state if base == collection else _build_state_table(con, collection)
        if train_state.is_empty() or state.is_empty():
            logger.warning(f"no usable balls for {collection}")
            return {"career": pl.DataFrame(), "val_acc": None}

        split = _split_matches(train_state["match_id"].to_numpy(), seed)
        venues = _venue_rates(train_state, split[0])
        X, y, train_state = _features_and_label(train_state, venues)
        model, metrics = _train_wp(
            X, y, match_ids=train_state["match_id"].to_numpy(), seed=seed, split=split
        )
        if base != collection:
            _, _, state = _features_and_label(state, venues)
        else:
            state = train_state
        scored = _delta_wp(model, state)
        career = _per_player(scored, con, collection)

    return {
        "career": career,
        "n_balls": state.height,
        **metrics,
    }
