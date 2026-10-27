"""Net Game Impact (NGI) — flagship player-impact metric.

Inspiration: WPA (Win Probability Added) from baseball. Each ball is
worth `ΔWP = WP_after − WP_before`. A batter who scores 4 in a tight
chase-finish gets credited a much larger ΔWP than the same 4 in a
dead opening over. Wickets, dot balls, boundaries all flow through
the same currency.

Pipeline
--------
1. **Win-probability model.** A gradient-boosted classifier (XGBoost) on
   Cricsheet ball-by-ball: per-ball state features → P(batting team wins).
   Only T20 matches and the two main innings are used (super overs are
   left out). Labels: 1 if the batting side won, 0 if it lost, **0.5 for a
   tie** (the two main innings level, whoever won the super over); no-results
   are dropped. Every feature is known *before* the delivery — balls left come
   from the scheduled overs minus legal balls bowled, the target only exists
   in the chase. The chase's target and its ball count come from the innings
   `target` Cricsheet records (`innings_<col>`), so a rain-hit chase is scored
   against its revised DLS target and shortened overs; a DB ingested before
   that table existed falls back to first-innings total + 1 and the scheduled
   overs. One feature tracks the scoring **era**: the league's average
   first-innings run rate over the 60 matches before this one, so a 180 in
   2009 and a 180 in 2026 aren't read as the same total.

   The trees carry **monotone constraints** where the direction is known:
   more balls left, wickets left, runs scored or current run rate never lower
   the batting side's chance; a higher target, more runs needed or a higher
   required rate never raise it. So a wicket can never *raise* the batting
   side's win probability, even in a sparse state.

   **Calibration is smooth** (beta calibration: a three-parameter logistic map
   of the raw probability, monotone), not isotonic: an isotonic step function
   gives a small swing exactly 0 and jumps at its step edges, which matters
   when every number downstream is a *difference* of two predictions.

2. **Out-of-fold scoring.** Every ball is scored by a model that never saw its
   match: matches are split into 5 folds, and each fold is scored by a model
   trained (early-stopped and calibrated on an inner hold-out) on the other
   four. Separately, a reporting model trained on 70% of matches, early-stopped
   and calibrated on 15%, is tested on the last 15% it never saw — the accuracy,
   Brier score, log loss, ECE and reliability table come from that test split.

3. **Score every ball.** WP_before is the prediction at the state just before
   the delivery; WP_after the prediction after applying its runs and wicket.
   The swing is split into three parts with two intermediate states:

       play    = WP(+ runs off the bat, one legal ball used) − WP_before
       wicket  = WP(… + the wicket)                        − WP(+ runs off the bat …)
       extras  = WP_after                                   − WP(… + the wicket)

   The last ball of the chase resolves to the result (1, 0 or 0.5 for a tie);
   the last ball of the first innings hands over to the chase's opening
   position (1 − WP of the chasing side), so no player is credited with the
   other innings. That end-of-innings resolution joins whichever of the three
   parts moved the needle most on that ball.

4. **Credit** (from the batting side's view; the fielding side gets the
   opposite sign):

   - **striker**: `play` — runs off the bat and the ball he used. A wide isn't
     a ball faced, so it moves nothing here.
   - **dismissed batter** (`player_out`, the non-striker in a run out at his end):
     `wicket`.
   - **bowler**: −`play`, minus his share of `extras` (wides and no-ball runs are
     his; byes, leg-byes and penalty runs are the team's, so nobody's), and the
     wicket: all of it for bowled / lbw / hit wicket / caught and bowled;
     80% for caught and stumped; none for a run out, retirement or obstruction.
   - **fielders** named on the dismissal: 20% of the wicket for a catch or a
     stumping (`FIELDER_SHARE`, catch difficulty is unknowable without tracking
     data), all of the run-out swing for a run out — split equally between them.

5. **Aggregate** per `(player, match)` and per `(player, career)`. NGI per match
   divides the career total by **appearances**: matches in the playing XI
   (Cricsheet `info.players`, `match_players_<col>`), plus any match he took part
   in without being listed (a fielding substitute), so a lower-order batter who
   didn't bat still counts the game.

Why not just SR / Avg / wickets
-------------------------------
- A 30* finisher beats a 100* against a beaten side.
- A wicket at 200/3 chasing 220 beats one at 50/3 chasing 250.
- One currency for batters + bowlers — directly comparable.

Players are keyed by their Cricsheet registry id resolved per match
(`common.sql.keyed_balls`), so two players who share a scorecard name are two
rows.

Output
------
`compute(collection)` returns a dict whose `career` is a polars DataFrame with
columns: `name`, `cricsheet_id`, `display_name`, `matches`, `ngi_total`,
`ngi_batting`, `ngi_bowling`, `ngi_fielding`, `ngi_per_match`.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
from loguru import logger

from cricdex.common.sql import (
    UNRESOLVED,
    _columns,
    _tables,
    balls_per_over,
    base_suffix,
    chase_targets,
    keyed_balls,
    relabel,
    table_suffix,
)
from cricdex.config import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "cricsheet" / "cricsheet.duckdb"
CACHE_DIR = DATA_DIR / "metrics" / ".ngi_cache"
MODEL_VERSION = "ngi-6"  # bump when the model or the credit rules change (invalidates the cache)

FEATURES = [
    "innings_idx",  # 0 = first innings, 1 = chase
    "balls_remaining",  # scheduled legal balls minus legal balls bowled
    "wickets_left",
    "score_before",
    "target",  # 0 in the first innings; the chase's (DLS-revised) target, else first-innings total + 1
    "runs_needed",  # 0 in the first innings
    "required_rr",  # 0 in the first innings
    "current_rr",
    "current_rr_minus_venue",  # RR vs the ground's first-innings average (training matches only)
    # the scoring era, as numbers relative to it (trees can't extrapolate a raw scoring level to a
    # new high, but "8 an over above this era's par" carries over): `league_rr_recent` is the
    # league's first-innings run rate over the 60 matches before this one
    "rr_vs_league",  # current run rate minus the era's
    "target_vs_par",  # chase target minus the era's par for these overs (0 in the first innings)
    "rrr_vs_league",  # required rate minus the era's run rate (0 in the first innings)
]
ERA_FEATURES = ("rr_vs_league", "target_vs_par", "rrr_vs_league")

# Direction of each feature's effect on the batting side's win chance where it's known (+1 never
# lowers it, −1 never raises it, 0 = learnt freely). XGBoost enforces these.
MONOTONE: dict[str, int] = {
    "balls_remaining": 1,
    "wickets_left": 1,
    "score_before": 1,
    "target": -1,
    "runs_needed": -1,
    "required_rr": -1,
    "current_rr": 1,
    "current_rr_minus_venue": 1,
    "rr_vs_league": 1,
    "target_vs_par": -1,
    "rrr_vs_league": -1,
}

ERA_WINDOW = 60  # matches the league scoring-era feature averages over
N_FOLDS = 5  # out-of-fold scoring folds
FIELDER_SHARE = 0.2  # a catcher's / stumper's share of a caught or stumped wicket's swing

# Dismissals that end an innings slot; "retired hurt" doesn't (the batter can come back).
_NOT_A_WICKET = ("retired hurt", "retired not out")
_ILLEGAL = ("wides", "noballs")
DEFAULT_VENUE_RR = 8.0  # fallback for a ground with no training-set first innings
_BOWLER_ALL = ("bowled", "lbw", "hit wicket", "caught and bowled")
_FIELDED = ("caught", "stumped")
_RUN_OUT = "run out"


def _extras_sql(con, collection: str) -> str:
    """Per-delivery extras split (wides+no-balls vs byes+leg-byes+penalty), from the per-type
    columns schema 2 stores, else from the single `extras_type` of an older DB."""
    cols = _columns(con, f"balls_{table_suffix(collection)}")
    if {"extras_wides", "extras_noballs", "extras_byes", "extras_legbyes"} <= cols:
        pen = "COALESCE(extras_penalty, 0)" if "extras_penalty" in cols else "0"
        return (
            "COALESCE(extras_wides, 0) + COALESCE(extras_noballs, 0) AS extras_bowler, "
            f"COALESCE(extras_byes, 0) + COALESCE(extras_legbyes, 0) + {pen} AS extras_team"
        )
    return (
        "CASE WHEN extras_type IN ('wides', 'noballs') THEN COALESCE(runs_extras, 0) ELSE 0 END "
        "AS extras_bowler, "
        "CASE WHEN extras_type IN ('wides', 'noballs') THEN 0 ELSE COALESCE(runs_extras, 0) END "
        "AS extras_team"
    )


def _build_state_table(con: duckdb.DuckDBPyConnection, collection: str) -> pl.DataFrame:
    """One row per delivery of the two main innings of every decided (or tied) T20 match, with the
    state *before* the delivery and what the delivery did. Player columns are registry ids."""
    safe = table_suffix(collection)
    not_wicket = ", ".join(f"'{w}'" for w in _NOT_A_WICKET)
    illegal = ", ".join(f"'{e}'" for e in _ILLEGAL)
    bpo = balls_per_over(con, collection, "m.")
    targets = chase_targets(con, collection)
    kb = keyed_balls(con, collection)
    extras = _extras_sql(con, collection)
    return con.execute(
        f"""
        WITH b AS (
            SELECT *,
                   CASE WHEN extras_type IN ({illegal}) THEN 0 ELSE 1 END AS legal,
                   CASE WHEN wicket_kind IS NOT NULL AND wicket_kind NOT IN ({not_wicket})
                        THEN 1 ELSE 0 END AS is_wicket,
                   {extras}
            FROM {kb}
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
        ),
        -- the scoring era: the league's first-innings run rate over the matches just before this one
        era AS (
            SELECT f.match_id,
                   AVG(f.first_total * 6.0 / GREATEST(f.first_legal, 1)) OVER (
                       ORDER BY m.match_date, f.match_id
                       ROWS BETWEEN {ERA_WINDOW} PRECEDING AND 1 PRECEDING
                   ) AS league_rr_recent
            FROM first_innings f JOIN matches_{safe} m ON m.match_id = f.match_id
            WHERE f.first_legal >= 30
        )
        SELECT
            s.match_id, s.match_date, s.innings_idx, s.batting_team, s.bowling_team, s.over,
            s.ball_in_over, s.ball_id, s.batter, s.non_striker, s.bowler, s.player_out, s.fielders,
            s.runs_total, s.runs_batter, s.extras_bowler, s.extras_team, s.wicket_kind, s.legal,
            s.is_wicket, s.is_last_ball, s.score_before, s.wickets_before, s.legal_before,
            -- the chase uses the recorded (DLS-revised) target and overs when Cricsheet has them
            GREATEST(0, CASE WHEN s.innings_idx = 1 AND t.target_balls IS NOT NULL THEN t.target_balls
                             ELSE COALESCE(m.overs, 20) * {bpo} END - s.legal_before) AS balls_remaining,
            (10 - s.wickets_before)                                        AS wickets_left,
            CASE WHEN s.innings_idx = 1
                 THEN COALESCE(t.target_runs, f.first_total + 1) ELSE 0 END AS target,
            CASE WHEN s.innings_idx = 1
                 THEN GREATEST(0, COALESCE(t.target_runs, f.first_total + 1) - s.score_before)
                 ELSE 0 END                                                AS runs_needed,
            f.first_total, f.first_legal, e.league_rr_recent,
            m.venue, m.outcome_winner, m.result,
            CASE WHEN m.result = 'tie' THEN 0.5
                 WHEN s.batting_team = m.outcome_winner THEN 1.0 ELSE 0.0 END AS batting_won
        FROM seq s
        JOIN first_innings f ON f.match_id = s.match_id
        JOIN matches_{safe} m ON m.match_id = s.match_id
        LEFT JOIN era e ON e.match_id = s.match_id
        LEFT JOIN {targets} t ON t.match_id = s.match_id AND t.innings_idx = s.innings_idx
        -- decided matches, and ties (labelled 0.5); no-results are dropped
        WHERE m.result = 'tie'
           OR (COALESCE(m.result, '') <> 'no result' AND m.outcome_winner IS NOT NULL)
        -- a fixed row order, so the fitted model (and every number from it) is reproducible
        ORDER BY s.match_id, s.innings_idx, s.over, s.ball_in_over, s.ball_id
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
    ).with_columns(
        (pl.col("current_rr") - pl.col("venue_avg_rr")).alias("current_rr_minus_venue"),
        (pl.col("current_rr") - pl.col("league_rr_recent")).alias("rr_vs_league"),
        pl.when(pl.col("innings_idx") == 1)
        .then(
            pl.col("target")
            - pl.col("league_rr_recent")
            * (pl.col("balls_remaining") + pl.col("legal_before"))
            / 6.0
        )
        .otherwise(0.0)
        .alias("target_vs_par"),
        pl.when(pl.col("innings_idx") == 1)
        .then(pl.col("required_rr") - pl.col("league_rr_recent"))
        .otherwise(0.0)
        .alias("rrr_vs_league"),
    )


def _features_and_label(
    state: pl.DataFrame, venue_rates: pl.DataFrame
) -> tuple[np.ndarray, np.ndarray, pl.DataFrame]:
    if "batting_won" not in state.columns:  # a state table built without the label column
        state = state.with_columns(
            pl.when(pl.col("result") == "tie")
            .then(0.5)
            .otherwise((pl.col("batting_team") == pl.col("outcome_winner")).cast(pl.Float64))
            .alias("batting_won")
        )
    era_fill = state["league_rr_recent"].mean() if "league_rr_recent" in state.columns else None
    df = state.join(venue_rates, on="venue", how="left").with_columns(
        pl.col("venue_avg_rr").fill_null(DEFAULT_VENUE_RR),
        pl.col("batting_won").cast(pl.Float64),
    )
    if "league_rr_recent" not in df.columns:
        df = df.with_columns(pl.lit(None, pl.Float64).alias("league_rr_recent"))
    df = df.with_columns(
        pl.col("league_rr_recent").fill_null(era_fill if era_fill is not None else DEFAULT_VENUE_RR)
    )
    df = _rates(df)
    X = _matrix(df)
    y = df["batting_won"].to_numpy().astype(np.float64)
    return X, y, df


def _matrix(df: pl.DataFrame) -> np.ndarray:
    return df.select(FEATURES).with_columns(pl.all().cast(pl.Float32)).to_numpy()


# ---- calibration ------------------------------------------------------------------------------


def _xent(y: np.ndarray, p: np.ndarray) -> float:
    """Mean cross-entropy (log loss); works for fractional (tie = 0.5) labels."""
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


class _BetaCalibrator:
    """Beta calibration (Kull, Silva Filho & Flach 2017): `logit(p_cal) = a·ln p − b·ln(1−p) + c`,
    fitted by Newton's method on cross-entropy (fractional labels allowed). Smooth and, with
    a, b ≥ 0, monotone — so a difference of two calibrated probabilities is never quantised. Falls
    back to Platt scaling (a = b) if the free fit isn't monotone."""

    def __init__(self) -> None:
        self.coef = np.array([1.0, 1.0, 0.0])

    @staticmethod
    def _design(p: np.ndarray, platt: bool) -> np.ndarray:
        p = np.clip(np.asarray(p, dtype=np.float64), 1e-6, 1 - 1e-6)
        if platt:
            return np.stack([np.log(p) - np.log1p(-p), np.ones_like(p)], axis=1)
        return np.stack([np.log(p), -np.log1p(-p), np.ones_like(p)], axis=1)

    @staticmethod
    def _newton(Z: np.ndarray, y: np.ndarray, iters: int = 50) -> np.ndarray:
        w = np.zeros(Z.shape[1])
        w[: Z.shape[1] - 1] = 1.0
        for _ in range(iters):
            q = 1.0 / (1.0 + np.exp(-np.clip(Z @ w, -30, 30)))
            g = Z.T @ (q - y) / len(y)
            h = (Z * (q * (1 - q))[:, None]).T @ Z / len(y) + 1e-8 * np.eye(Z.shape[1])
            step = np.linalg.solve(h, g)
            w -= step
            if np.abs(step).max() < 1e-9:
                break
        return w

    def fit(self, p: np.ndarray, y: np.ndarray) -> _BetaCalibrator:
        w = self._newton(self._design(p, platt=False), y)
        if w[0] < 0 or w[1] < 0:
            a, c = self._newton(self._design(p, platt=True), y)
            w = np.array([a, a, c])
        self.coef = w
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        z = self._design(p, platt=False) @ self.coef
        return 1.0 / (1.0 + np.exp(-z))


class _IsotonicCalibrator:
    """The old isotonic step function — kept only to report what smooth calibration changed."""

    def __init__(self) -> None:
        from sklearn.isotonic import IsotonicRegression

        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)

    def fit(self, p: np.ndarray, y: np.ndarray) -> _IsotonicCalibrator:
        self.iso.fit(p, y)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return self.iso.transform(p)


class _CalibratedWP:
    """XGBoost booster + calibrator over its raw probabilities."""

    def __init__(self, booster, calibrator):
        self.booster = booster
        self.calibrator = calibrator

    def raw(self, X: np.ndarray) -> np.ndarray:
        import xgboost as xgb

        return self.booster.predict(
            xgb.DMatrix(X, feature_names=FEATURES),
            iteration_range=(0, self.booster.best_iteration + 1),
        )

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        cal = self.calibrator.transform(self.raw(X))
        return np.stack([1.0 - cal, cal], axis=1)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(np.int64)


# ---- training ---------------------------------------------------------------------------------


def _split_matches(match_ids: np.ndarray, seed: int = 42) -> tuple[set, set, set]:
    """Match-level 70 / 15 / 15 split: train · calibration (early stopping + calibration) · test
    (reporting only)."""
    rng = np.random.default_rng(seed)
    unique = np.unique(match_ids)
    rng.shuffle(unique)
    a, b = int(0.70 * len(unique)), int(0.85 * len(unique))
    return set(unique[:a].tolist()), set(unique[a:b].tolist()), set(unique[b:].tolist())


def _fit(
    X: np.ndarray,
    y: np.ndarray,
    tr: np.ndarray,
    ca: np.ndarray,
    seed: int,
    monotone: bool = True,
    calibration: str = "beta",
) -> _CalibratedWP:
    """Boost on rows `tr`, early-stop and calibrate on rows `ca`."""
    import xgboost as xgb

    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 6,
        "eta": 0.05,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "tree_method": "hist",
        "seed": seed,
        "nthread": -1,
    }
    if monotone:
        params["monotone_constraints"] = (
            "(" + ",".join(str(MONOTONE.get(f, 0)) for f in FEATURES) + ")"
        )
    dtr = xgb.DMatrix(X[tr], label=y[tr], feature_names=FEATURES)
    dca = xgb.DMatrix(X[ca], label=y[ca], feature_names=FEATURES)
    booster = xgb.train(
        params,
        dtr,
        num_boost_round=600,
        evals=[(dca, "cal")],
        early_stopping_rounds=30,
        verbose_eval=False,
    )
    model = _CalibratedWP(booster, None)
    raw = model.raw(X[ca])
    model.calibrator = (
        _IsotonicCalibrator() if calibration == "isotonic" else _BetaCalibrator()
    ).fit(raw, y[ca])
    return model


def _report(p: np.ndarray, y: np.ndarray) -> dict:
    """Accuracy (decided matches only), Brier, log loss, ECE and a 10-bucket reliability table."""
    decided = y != 0.5
    val_acc = (
        float(((p[decided] >= 0.5).astype(float) == y[decided]).mean()) if decided.any() else 0.0
    )
    bins = np.linspace(0.0, 1.0, 11)
    reliability = []
    ece = 0.0
    for i in range(10):
        mask = (p >= bins[i]) & ((p < bins[i + 1]) if i < 9 else (p <= bins[i + 1]))
        if mask.any():
            mp, ma = float(p[mask].mean()), float(y[mask].mean())
            ece += mask.sum() * abs(mp - ma)
            reliability.append(
                {
                    "bucket": f"[{bins[i]:.1f}, {bins[i + 1]:.1f})",
                    "count": int(mask.sum()),
                    "mean_predicted": mp,
                    "mean_actual": ma,
                }
            )
    return {
        "val_acc": val_acc,
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": _xent(y, p),
        "ece": float(ece / max(len(p), 1)),
        "reliability": reliability,
    }


def _train_wp(
    X: np.ndarray,
    y: np.ndarray,
    match_ids: np.ndarray,
    seed: int = 42,
    split: tuple[set, set, set] | None = None,
    monotone: bool = True,
    calibration: str = "beta",
):
    """The reporting model: XGBoost on the train matches, early-stopped + calibrated on the
    calibration matches, scored on the test matches it never saw.

    Returns the calibrated model plus a metrics dict (val_acc, brier, log_loss, ece, reliability —
    all on the test matches)."""
    train_m, cal_m, test_m = split or _split_matches(match_ids, seed)
    tr = np.isin(match_ids, list(train_m))
    ca = np.isin(match_ids, list(cal_m))
    te = np.isin(match_ids, list(test_m))
    model = _fit(X, y, tr, ca, seed, monotone=monotone, calibration=calibration)
    test_cal = model.predict_proba(X[te])[:, 1]
    metrics = _report(test_cal, y[te])
    logger.info(
        f"WP: test acc={metrics['val_acc']:.3f} brier={metrics['brier']:.4f} "
        f"log_loss={metrics['log_loss']:.4f} ece={metrics['ece']:.4f} "
        f"on {te.sum()} balls from {len(test_m)} unseen matches "
        f"(train {len(train_m)}, calibration {len(cal_m)} matches)"
    )
    metrics.update(
        {
            "n_train_matches": len(train_m),
            "n_cal_matches": len(cal_m),
            "n_val_matches": len(test_m),
            "n_val_balls": int(te.sum()),
        }
    )
    return model, metrics


# ---- states and scoring -----------------------------------------------------------------------


def _states(df: pl.DataFrame) -> dict[str, np.ndarray]:
    """Feature matrices for the four states of every delivery: before it, after the runs off the
    bat (and the legal ball used), after the wicket too, and after everything (extras included)."""

    def advance(runs: pl.Expr, wicket: bool) -> pl.DataFrame:
        out = df.with_columns(
            (pl.col("score_before") + runs).alias("score_before"),
            (pl.col("wickets_before") + (pl.col("is_wicket") if wicket else 0)).alias(
                "wickets_before"
            ),
            (pl.col("legal_before") + pl.col("legal")).alias("legal_before"),
            (pl.col("balls_remaining") - pl.col("legal"))
            .clip(lower_bound=0)
            .alias("balls_remaining"),
        ).with_columns(
            (10 - pl.col("wickets_before")).clip(lower_bound=0).alias("wickets_left"),
            pl.when(pl.col("innings_idx") == 1)
            .then((pl.col("target") - pl.col("score_before")).clip(lower_bound=0))
            .otherwise(0)
            .alias("runs_needed"),
        )
        return _rates(out)

    return {
        "before": _matrix(df),
        "bat": _matrix(advance(pl.col("runs_batter"), wicket=False)),
        "mid": _matrix(advance(pl.col("runs_batter"), wicket=True)),
        "after": _matrix(advance(pl.col("runs_total"), wicket=True)),
    }


def _components(df: pl.DataFrame, preds: dict[str, np.ndarray]) -> pl.DataFrame:
    """ΔWP and its play / wicket / extras parts from the four state predictions, with the
    end-of-innings resolution (the result, or the hand-over to the chase) folded in."""
    wp_before, wp_bat, wp_mid = preds["before"], preds["bat"], preds["mid"]
    wp_after = preds["after"].copy()
    model_after = preds["after"]

    last = df["is_last_ball"].to_numpy()
    chase = df["innings_idx"].to_numpy() == 1
    # Last ball of the chase: the match is decided (a tie resolves to 0.5).
    end_chase = last & chase
    wp_after[end_chase] = df["batting_won"].to_numpy()[end_chase].astype(float)
    # Last ball of the first innings: hand over to the chase's opening state, from the first side's view.
    end_first = last & ~chase
    if end_first.any():
        opening = (
            df.select("match_id", "innings_idx", "legal_before", "score_before")
            .with_columns(pl.Series("_wp", wp_before))
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
        chase_wp = handover["_wp"].to_numpy().astype(float)
        ok = ~np.isnan(chase_wp)
        wp_after[idx[ok]] = 1.0 - chase_wp[ok]

    play = wp_bat - wp_before
    wicket = wp_mid - wp_bat
    extras = model_after - wp_mid
    # the resolution joins whichever part moved the needle most on that ball
    resolution = wp_after - model_after
    parts = np.stack([np.abs(play), np.abs(wicket), np.abs(extras)], axis=1)
    biggest = parts.argmax(axis=1)
    play = play + np.where(biggest == 0, resolution, 0.0)
    wicket = wicket + np.where(biggest == 1, resolution, 0.0)
    extras = extras + np.where(biggest == 2, resolution, 0.0)

    return df.with_columns(
        pl.Series("wp_before", wp_before),
        pl.Series("wp_after", wp_after),
        pl.Series("delta_wp", wp_after - wp_before),
        pl.Series("d_play", play),
        pl.Series("d_wicket", wicket),
        pl.Series("d_extras", extras),
    )


def _predict_states(model, states: dict[str, np.ndarray], rows: np.ndarray | None = None):
    sel = (lambda a: a) if rows is None else (lambda a: a[rows])
    return {k: model.predict_proba(sel(v))[:, 1] for k, v in states.items()}


def _delta_wp(model, state: pl.DataFrame) -> pl.DataFrame:
    """Score every ball with one model: WP before / after, ΔWP (batting side's view) and its
    play / wicket / extras parts."""
    return _components(state, _predict_states(model, _states(state)))


def _oof_scores(
    X: np.ndarray, y: np.ndarray, df: pl.DataFrame, seed: int, monotone: bool = True
) -> pl.DataFrame:
    """Score every ball out of fold: 5 folds by match, each scored by a model that never saw it
    (trained on the other folds, early-stopped and calibrated on an inner 15% of their matches)."""
    match_ids = df["match_id"].to_numpy()
    unique = np.unique(match_ids)
    rng = np.random.default_rng(seed + 1)
    rng.shuffle(unique)
    fold_of = {m: i % N_FOLDS for i, m in enumerate(unique)}
    fold = np.array([fold_of[m] for m in match_ids])
    states = _states(df)
    preds = {k: np.zeros(len(df)) for k in states}
    for k in range(N_FOLDS):
        others = unique[[fold_of[m] != k for m in unique]]
        inner = rng.permutation(others)
        cut = int(0.85 * len(inner))
        tr = np.isin(match_ids, inner[:cut])
        ca = np.isin(match_ids, inner[cut:])
        model = _fit(X, y, tr, ca, seed + k, monotone=monotone)
        rows = fold == k
        for name, p in _predict_states(model, states, rows).items():
            preds[name][rows] = p
    return _components(df, preds)


# ---- credit -----------------------------------------------------------------------------------


def _credit(scored: pl.DataFrame) -> pl.DataFrame:
    """One row per (match, player, ball role) with that ball's credit (batting side's ΔWP parts
    turned into each player's share — see the module docstring for the rule)."""
    kind = pl.col("wicket_kind")
    nf = pl.col("fielders").list.len().fill_null(0)
    is_wkt = pl.col("is_wicket") == 1
    bowler_wk_share = (
        pl.when(~is_wkt)
        .then(0.0)
        .when(kind.is_in(list(_BOWLER_ALL)))
        .then(1.0)
        .when(kind.is_in(list(_FIELDED)) & (nf > 0))
        .then(1.0 - FIELDER_SHARE)
        .when(kind.is_in(list(_FIELDED)))
        .then(1.0)
        .otherwise(0.0)
    )
    fielder_share = (
        pl.when(~is_wkt | (nf == 0))
        .then(0.0)
        .when(kind.is_in(list(_FIELDED)))
        .then(FIELDER_SHARE)
        .when(kind == _RUN_OUT)
        .then(1.0)
        .otherwise(0.0)
    )
    extras_runs = pl.col("extras_bowler") + pl.col("extras_team")
    bowler_extras_share = (
        pl.when(extras_runs > 0).then(pl.col("extras_bowler") / extras_runs).otherwise(0.0)
    )
    base = scored.select(
        "match_id",
        "batter",
        "bowler",
        "player_out",
        "fielders",
        "d_play",
        (pl.col("d_wicket") * is_wkt.cast(pl.Float64)).alias("d_wicket"),
        "d_extras",
        bowler_wk_share.alias("bw"),
        fielder_share.alias("fs"),
        bowler_extras_share.alias("be"),
        nf.alias("nf"),
    )
    striker = base.select(
        "match_id", pl.col("batter").alias("player"), pl.col("d_play").alias("bat")
    )
    out = base.filter(pl.col("player_out").is_not_null()).select(
        "match_id", pl.col("player_out").alias("player"), pl.col("d_wicket").alias("bat")
    )
    bowler = base.select(
        "match_id",
        pl.col("bowler").alias("player"),
        (
            -(
                pl.col("d_play")
                + pl.col("be") * pl.col("d_extras")
                + pl.col("bw") * pl.col("d_wicket")
            )
        ).alias("bowl"),
    )
    field = (
        base.filter((pl.col("fs") > 0) & (pl.col("nf") > 0))
        .with_columns((-pl.col("fs") * pl.col("d_wicket") / pl.col("nf")).alias("field"))
        .explode("fielders")
        .select("match_id", pl.col("fielders").alias("player"), "field")
    )
    return pl.concat(
        [
            striker.with_columns(pl.lit(0.0).alias("bowl"), pl.lit(0.0).alias("field")),
            out.with_columns(pl.lit(0.0).alias("bowl"), pl.lit(0.0).alias("field")),
            bowler.with_columns(pl.lit(0.0).alias("bat"), pl.lit(0.0).alias("field")).select(
                "match_id", "player", "bat", "bowl", "field"
            ),
            field.with_columns(pl.lit(0.0).alias("bat"), pl.lit(0.0).alias("bowl")).select(
                "match_id", "player", "bat", "bowl", "field"
            ),
        ],
        how="vertical_relaxed",
    ).filter(pl.col("player").is_not_null())


def appearances(
    con: duckdb.DuckDBPyConnection, collection: str, match_ids: list[str] | None = None
) -> dict[str, int]:
    """player key -> matches played in this collection (or time window): a place in the XI
    (Cricsheet `info.players`, `match_players_<col>`), plus any match he batted, bowled, ran or
    fielded in without being listed (a substitute fielder; every match on a DB ingested before the
    XI table). `match_ids` narrows it to those matches (the ones NGI scored)."""
    safe = table_suffix(collection)
    kb = keyed_balls(con, collection)
    xi = f"match_players_{base_suffix(collection)}"
    parts = [
        f"SELECT {c} AS k, match_id FROM {kb} WHERE {c} IS NOT NULL"
        for c in ("batter", "non_striker", "bowler")
    ]
    parts.append(f"SELECT UNNEST(fielders) AS k, match_id FROM {kb} WHERE len(fielders) > 0")
    if xi in _tables(con):
        parts.append(
            f"SELECT COALESCE(x.identifier, '{UNRESOLVED}' || x.name) AS k, x.match_id FROM {xi} x "
            f"JOIN matches_{safe} m ON m.match_id = x.match_id"
        )
    filt = ""
    if match_ids is not None:
        con.register(
            "_ngi_matches",
            pl.DataFrame({"match_id": list(match_ids)}, schema={"match_id": pl.String}),
        )
        filt = "WHERE match_id IN (SELECT match_id FROM _ngi_matches)"
    rows = con.execute(
        f"SELECT k, COUNT(DISTINCT match_id) FROM ({' UNION ALL '.join(parts)}) {filt} GROUP BY k"
    ).fetchall()
    if match_ids is not None:
        con.unregister("_ngi_matches")
    return {k: int(n) for k, n in rows if k is not None}


def _per_player(
    scored: pl.DataFrame, con: duckdb.DuckDBPyConnection, collection: str = "ipl"
) -> pl.DataFrame:
    """Credit every ball, sum per (player, match) and per career, divide by appearances."""
    credit = _credit(scored)
    career = (
        credit.group_by("player")
        .agg(
            pl.col("bat").sum().alias("ngi_batting"),
            pl.col("bowl").sum().alias("ngi_bowling"),
            pl.col("field").sum().alias("ngi_fielding"),
        )
        .with_columns(
            (pl.col("ngi_batting") + pl.col("ngi_bowling") + pl.col("ngi_fielding")).alias(
                "ngi_total"
            )
        )
    )
    apps = appearances(con, collection, scored["match_id"].unique().to_list())
    career = career.with_columns(
        pl.col("player")
        .replace_strict(apps, default=None, return_dtype=pl.Int64)
        .fill_null(0)
        .alias("matches")
    )
    # anyone credited in a match counts it, even if no table lists him (defensive: never divide by 0)
    involved = credit.group_by("player").agg(pl.col("match_id").n_unique().alias("_inv"))
    career = (
        career.join(involved, on="player", how="left")
        .with_columns(pl.max_horizontal("matches", "_inv").alias("matches"))
        .drop("_inv")
        .with_columns((pl.col("ngi_total") / pl.col("matches")).alias("ngi_per_match"))
        .rename({"player": "name"})
    )
    career = relabel(career, con, collection, ("name",))
    cols = ["name", "cricsheet_id", "display_name", "matches", "ngi_total", "ngi_batting"]
    cols += ["ngi_bowling", "ngi_fielding", "ngi_per_match"]
    return career.select(cols).sort(["ngi_per_match", "cricsheet_id"], descending=[True, False])


def _base_collection(collection: str) -> str:
    """`ipl_last1y` / `ipl_era_impact` → `ipl`: a time window is scored with the models trained on
    its whole collection."""
    return base_suffix(collection)


def _is_window(collection: str) -> bool:
    return base_suffix(collection) != table_suffix(collection)


# ---- scoring cache (a time window reuses its league's out-of-fold scores) ----------------------

_SCORED_COLS = [
    "match_id", "innings_idx", "batter", "bowler", "player_out", "fielders", "wicket_kind",
    "is_wicket", "runs_total", "is_last_ball", "extras_bowler", "extras_team", "wp_before", "wp_after", "delta_wp",
    "d_play", "d_wicket", "d_extras",
]  # fmt: skip


def _fingerprint(state: pl.DataFrame, seed: int) -> dict:
    return {
        "version": MODEL_VERSION,
        "seed": seed,
        "n_balls": int(state.height),
        "n_matches": int(state["match_id"].n_unique()),
        "max_date": str(state["match_date"].max()),
    }


def _cache_load(base: str, fp: dict) -> pl.DataFrame | None:
    meta, data = CACHE_DIR / f"{base}.json", CACHE_DIR / f"{base}.parquet"
    try:
        if meta.exists() and data.exists() and json.loads(meta.read_text())["fingerprint"] == fp:
            return pl.read_parquet(data)
    except (OSError, ValueError, KeyError, pl.exceptions.PolarsError) as e:
        logger.warning(f"NGI cache {base} unreadable, recomputing ({e})")
        return None
    return None


def _cache_save(base: str, fp: dict, scored: pl.DataFrame, metrics: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        scored.select(_SCORED_COLS).write_parquet(CACHE_DIR / f"{base}.parquet")
        (CACHE_DIR / f"{base}.json").write_text(json.dumps({"fingerprint": fp, "metrics": metrics}))
    except OSError as e:
        logger.warning(f"NGI cache not written ({e})")


def score(
    collection: str, db_path: Path | str = DEFAULT_DB_PATH, seed: int = 42
) -> tuple[pl.DataFrame, dict]:
    """Out-of-fold scored deliveries of a whole collection plus the reporting model's test metrics
    (cached per collection; recomputed when the data, the seed or the model version change)."""
    base = _base_collection(collection)
    with duckdb.connect(str(db_path), read_only=True) as con:
        state = _build_state_table(con, base)
    if state.is_empty():
        return state, {}
    fp = _fingerprint(state, seed)
    cached = _cache_load(base, fp)
    if cached is not None:
        meta = json.loads((CACHE_DIR / f"{base}.json").read_text())
        return cached, meta["metrics"]
    split = _split_matches(state["match_id"].to_numpy(), seed)
    venues = _venue_rates(state, split[0])
    X, y, df = _features_and_label(state, venues)
    _, metrics = _train_wp(X, y, match_ids=df["match_id"].to_numpy(), seed=seed, split=split)
    scored = _oof_scores(X, y, df, seed)
    oof = _report(scored["wp_before"].to_numpy(), y)
    metrics["oof"] = {k: oof[k] for k in ("brier", "log_loss", "ece")}
    metrics["wrong_sign_share"] = wrong_sign_share(scored)
    metrics["zero_delta_share"] = float((scored["delta_wp"] == 0).mean())
    logger.info(
        f"NGI {base}: out-of-fold brier={oof['brier']:.4f} log_loss={oof['log_loss']:.4f} "
        f"ece={oof['ece']:.4f}; wicket balls raising batting WP: {metrics['wrong_sign_share']:.2%}"
    )
    _cache_save(base, fp, scored, metrics)
    return scored.select(_SCORED_COLS), metrics


def wrong_sign_share(scored: pl.DataFrame) -> float:
    """Share of wicket balls (no runs, not an innings' last ball) that *raised* the batting side's
    win probability — impossible in cricket terms, so a model-quality check."""
    w = scored.filter(
        (pl.col("is_wicket") == 1) & (pl.col("runs_total") == 0) & ~pl.col("is_last_ball")
    )
    return float((w["delta_wp"] > 1e-12).mean()) if w.height else 0.0


def compute(
    collection: str = "ipl",
    db_path: Path | str = DEFAULT_DB_PATH,
    seed: int = 42,
) -> dict:
    """Fit WP, score every ball out of fold, credit it and aggregate to a career NGI table.

    A windowed collection (`<col>_last1y` / `_last3y` / an era window) is scored with the models
    trained on the whole `<col>` — a year of matches is far too few to fit one — and the reported
    metrics are those models'.

    Returns:
        career     polars DataFrame keyed by `cricsheet_id` (plus `name` / `display_name`).
        val_acc    accuracy on the test matches (decided ones; never used for fitting or calibration).
        brier      Brier score on the test matches (lower = better).
        log_loss   cross-entropy on the test matches.
        ece        expected calibration error on the test matches.
        reliability  list of 10 buckets {bucket, count, mean_predicted, mean_actual}.
        oof        Brier / log loss / ECE of the out-of-fold scores over every ball.
        n_balls    total balls scored.
        n_val_balls / n_val_matches / n_cal_matches / n_train_matches  split shape.
    """
    scored, metrics = score(collection, db_path, seed)
    if scored.is_empty():
        logger.warning(f"no usable balls for {collection}")
        return {"career": pl.DataFrame(), "val_acc": None}
    with duckdb.connect(str(db_path), read_only=True) as con:
        if _is_window(collection):
            safe = table_suffix(collection)
            if f"matches_{safe}" not in _tables(con):
                return {"career": pl.DataFrame(), "val_acc": None}
            keep = [r[0] for r in con.execute(f"SELECT match_id FROM matches_{safe}").fetchall()]
            scored = scored.filter(pl.col("match_id").is_in(keep))
            if scored.is_empty():
                return {"career": pl.DataFrame(), "val_acc": None}
        career = _per_player(scored, con, collection)
    return {"career": career, "n_balls": scored.height, **metrics}


# ---- diagnostics (before / after numbers for the methodology) ---------------------------------


def diagnose(
    collection: str = "ipl", db_path: Path | str = DEFAULT_DB_PATH, seed: int = 42
) -> dict:
    """What each WP change did, on one collection's held-out test matches:

    - calibration: isotonic vs beta (ECE, Brier, log loss) and the share of balls whose ΔWP is
      exactly 0 under each;
    - monotone constraints: the share of wicket balls that raised batting WP with and without;
    - the era features: temporal tests (train on every earlier season, test on one of the last
      three) with and without them;
    - in-sample vs out-of-fold: how far the old score-everything-with-one-model NGI moves."""
    global FEATURES
    with duckdb.connect(str(db_path), read_only=True) as con:
        state = _build_state_table(con, collection)
    split = _split_matches(state["match_id"].to_numpy(), seed)
    X, y, df = _features_and_label(state, _venue_rates(state, split[0]))
    mids = df["match_id"].to_numpy()
    te = np.isin(mids, list(split[2]))
    out: dict = {"collection": collection, "n_balls": int(df.height)}

    def scored_with(model) -> pl.DataFrame:
        return _delta_wp(model, df)

    cal = {}
    for how in ("isotonic", "beta"):
        model, m = _train_wp(X, y, mids, seed, split, monotone=True, calibration=how)
        sc = scored_with(model)
        cal[how] = {
            "ece": m["ece"],
            "brier": m["brier"],
            "log_loss": m["log_loss"],
            "zero_delta_share": float((sc["delta_wp"] == 0).mean()),
        }
    out["calibration"] = cal

    mono = {}
    for flag in (False, True):
        model, m = _train_wp(X, y, mids, seed, split, monotone=flag)
        sc = scored_with(model)
        mono["monotone" if flag else "unconstrained"] = {
            "wrong_sign_share": wrong_sign_share(sc),
            "log_loss": m["log_loss"],
            "brier": m["brier"],
        }
    out["monotone"] = mono

    # temporal tests: train on every earlier season, test on each of the last three
    seasons = df["match_date"].str.slice(0, 4)
    era: dict = {}
    feats_all = list(FEATURES)
    for last in sorted(set(seasons.to_list()))[-3:]:
        later = (seasons == last).to_numpy()
        earlier = (seasons < last).to_numpy()
        for with_era in (False, True):
            FEATURES = feats_all if with_era else [f for f in feats_all if f not in ERA_FEATURES]
            try:
                Xe = _matrix(df)
                rng = np.random.default_rng(seed)
                em = np.unique(mids[earlier])
                rng.shuffle(em)
                cut = int(0.85 * len(em))
                tr = np.isin(mids, em[:cut]) & earlier
                ca = np.isin(mids, em[cut:]) & earlier
                model = _fit(Xe, y, tr, ca, seed)
                r = _report(model.predict_proba(Xe[later])[:, 1], y[later])
                era.setdefault(str(last), {})["with_era" if with_era else "without_era"] = {
                    k: r[k] for k in ("brier", "log_loss", "ece")
                } | {"n_balls": int(later.sum())}
            finally:
                FEATURES = feats_all
    out["era_temporal_test"] = era

    # in-sample (old) vs out-of-fold NGI: correlation of per-player NGI per match
    model, _ = _train_wp(X, y, mids, seed, split)
    insample = scored_with(model)
    oof = _oof_scores(X, y, df, seed)
    with duckdb.connect(str(db_path), read_only=True) as con:
        a = _per_player(insample, con, collection).select(
            "cricsheet_id", "name", "matches", pl.col("ngi_per_match").alias("ins")
        )
        b = _per_player(oof, con, collection).select(
            "cricsheet_id", pl.col("ngi_per_match").alias("oof")
        )
    j = a.join(b, on="cricsheet_id").filter(pl.col("matches") >= 25)
    out["in_sample_vs_oof"] = {
        "players": int(j.height),
        "pearson": float(np.corrcoef(j["ins"], j["oof"])[0, 1]) if j.height > 2 else None,
        "mean_abs_change": float((j["ins"] - j["oof"]).abs().mean()) if j.height else None,
        "test_balls_in_sample_log_loss": _xent(y[te], insample["wp_before"].to_numpy()[te]),
    }
    return out
