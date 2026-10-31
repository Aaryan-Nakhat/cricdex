"""A player's complete value in runs: runs per 100 balls above the league's average ball.

The rating model gives every player two skills per role on two different scales: a log runs-per-ball
effect (scoring / economy) and a log-odds dismissal effect (survival / strike). This module turns them
into one currency, **runs**, by pricing a wicket at what it actually costs where the player plays.

Wicket cost (a value function over the innings)
-----------------------------------------------
From every first innings of a full-length, non-rain-affected match in the league (the second innings is
shaped by its target, so it isn't used), count per state (over bucket o = 0..19 of the scheduled
innings, wickets down w = 0..9) the legal balls, the runs (all runs, extras included) and the wickets
(any dismissal except retired hurt / not out). Smooth with a multiplicative model

    runs per ball   (o, w) = A_o · C_{phase(o), w}
    wicket per ball (o, w) = A'_o · C'_{phase(o), w}

(over levels × a wickets-down factor per phase, each phase's factor shrunk toward the all-overs factor
with a few hundred balls' pseudo-count), so a thin state (8 down in the 3rd over) borrows from its
neighbours. Then a backward recursion over the 120 balls of an innings gives the expected runs still to
come from each state,

    V(b, w) = r(b, w) + p(b, w) · V(b+1, w+1) + (1 − p(b, w)) · V(b+1, w),   V(120, ·) = V(·, 10) = 0,

and the run cost of losing a wicket on ball b with w down is

    λ(b, w) = V(b+1, w) − V(b+1, w+1)      (clipped at 0).

This is the dynamic-programming wicket price of Duckworth–Lewis-style resource tables and of
"dismissal-adjusted runs" (Bandyopadhyay 2026, arXiv:2608.18020). On the IPL a wicket in the powerplay
with nobody out costs about 14 runs, one in the 19th over about 3: why a finisher's survival is worth far
less than an opener's.

A player's wicket cost is the average λ over the states he actually played in, each ball weighted by
the chance of a wicket in that state (a better survivor saves wickets in proportion to how often they
fall), kept per phase × innings. A chase uses the first-innings λ of the same state (an approximation:
a chase's wicket cost also depends on the target).

The value
---------
With league baselines per phase p and innings c — runs off the bat per legal ball r_pc, all runs a
bowler is charged (bat + wides + no-balls) per legal ball R_pc and bowler-credited dismissals per trial
q_pc — and the player's share of balls π_pc in each, per posterior draw:

    batter:  100 · Σ π_pc [ r_pc (m − 1)  −  λ_pc (σ(logit q_pc − Δs) − q_pc) ]
    bowler:  100 · Σ π_pc [ R_pc (1 − m)  +  λ_pc (σ(logit q_pc + Δt) − q_pc) ]

where m = e^skill / (ball-weighted league mean of e^skill) is his run-rate multiplier against the average
ball (for a bowler from his economy skill, e^−economy), and Δs / Δt is his survival / strike skill minus
the ball-weighted league mean. The result is re-centred so the league's balls average 0: **runs per 100
balls above the average ball, wickets priced in runs where he plays**. Baselines and λ are pooled over
every season in the window, so a 2009 player and a 2026 one are converted at the same rate (their skills
are already judged against their own season). Computing it per draw keeps `value_sd` honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

from cricdesk.common.sql import _columns, _tables, keyed_balls, table_suffix

PHASES = ("powerplay", "middle", "death")
INNINGS = (0, 1)  # setting, chasing
N_BUCKETS = 20  # over buckets of the scheduled innings (5-ball overs in The Hundred included)
N_BALLS = 120  # balls of the value function (6 per bucket)
MAX_W = 10
# Pseudo-counts that shrink each phase's wickets-down factor toward the all-overs one.
_SHRINK_RUNS = 300.0  # ≈ 250 balls of runs
_SHRINK_WKTS = 15.0  # ≈ 300 balls of wickets
MIN_INNINGS = 20  # fewer qualifying first innings than this → the default table below
# The IPL's fitted wicket cost by phase (runs), used only when a collection has too few full first
# innings (or lacks the columns) to fit its own table — e.g. a tiny test fixture.
DEFAULT_LAMBDA = {"powerplay": 13.0, "middle": 9.0, "death": 3.5}

# Wicket kinds that don't cost the batting side a wicket.
_NOT_A_WICKET = ("retired hurt", "retired not out")
# Wicket kinds credited to the bowler (as in bayesian._BOWLER_WICKET_KINDS).
_BOWLER_KINDS = ("bowled", "caught", "lbw", "caught and bowled", "stumped", "hit wicket")


@dataclass
class LeagueTables:
    """The league's wicket-cost function and per-phase baselines, plus every player's mix."""

    lam: np.ndarray  # (N_BALLS, MAX_W) run cost of a wicket on ball b with w down
    pout: np.ndarray  # (N_BUCKETS, MAX_W) smoothed chance of a wicket per ball
    par: float  # expected first-innings total, V(0, 0)
    r: np.ndarray  # (3, 2) runs off the bat per legal ball, by phase × innings
    rtot: np.ndarray  # (3, 2) bat + wides + no-ball runs per legal ball
    q: np.ndarray  # (3, 2) bowler-credited dismissals per trial
    n_innings: int  # first innings the table was fitted on (0 = default table)
    # per role: player id -> (balls by phase×innings [6], wicket-weighted λ by phase×innings [6])
    mix: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = field(default_factory=dict)
    # per role: player id -> what he actually did by phase×innings, [6, 4]: runs off the bat (batter)
    # or runs charged incl. wides / no-balls (bowler), bowler-credited outs, dismissal trials, balls
    totals: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)

    def summary(self) -> dict:
        """λ by phase and wickets down, for the context file / docs."""
        out: dict = {"par_first_innings": round(float(self.par), 1), "n_innings": self.n_innings}
        bounds = {"powerplay": (0, 36), "middle": (36, 90), "death": (90, 120)}
        out["wicket_cost_by_phase_and_wickets_down"] = {
            p: [round(float(self.lam[a:b, w].mean()), 2) for w in range(MAX_W)]
            for p, (a, b) in bounds.items()
        }
        out["wicket_cost_by_over_at_2_down"] = [
            round(float(self.lam[o * 6 : o * 6 + 6, 2].mean()), 2) for o in range(N_BUCKETS)
        ]
        out["baseline_runs_per_ball"] = {
            p: [round(float(x), 4) for x in self.r[i]] for i, p in enumerate(PHASES)
        }
        out["baseline_dismissals_per_ball"] = {
            p: [round(float(x), 5) for x in self.q[i]] for i, p in enumerate(PHASES)
        }
        return out


def _phase_of_bucket(o: np.ndarray) -> np.ndarray:
    return np.where(o < 6, 0, np.where(o < 15, 1, 2))


def _smooth(y: np.ndarray, n: np.ndarray, shrink: float, iters: int = 100) -> np.ndarray:
    """y / n per (bucket, w) as A_o · C_{phase, w}: an over level times a wickets-down factor per phase,
    each phase's factor shrunk toward the all-overs factor (Poisson–gamma, `shrink` pseudo-events)."""
    ph = _phase_of_bucket(np.arange(N_BUCKETS))
    a = np.ones(N_BUCKETS)
    c = np.ones(MAX_W)
    for _ in range(iters):  # raking: the all-overs fit
        a = y.sum(1) / np.maximum((n * c[None, :]).sum(1), 1e-9)
        c = y.sum(0) / np.maximum((n * a[:, None]).sum(0), 1e-9)
    cp = np.ones((3, MAX_W))
    for _ in range(iters):
        fit = a[:, None] * c[None, :] * cp[ph]
        for k in range(3):
            rows = ph == k
            exp_k = (n[rows] * (a[rows, None] * c[None, :])).sum(0)
            cp[k] = (y[rows].sum(0) + shrink) / (exp_k + shrink)
        a = y.sum(1) / np.maximum((n * (c[None, :] * cp[ph])).sum(1), 1e-9)
    fit = a[:, None] * c[None, :] * cp[ph]
    return np.where(np.isfinite(fit), fit, 0.0)


def _value_function(
    rate: np.ndarray, pout: np.ndarray, balls: int = N_BALLS
) -> tuple[np.ndarray, np.ndarray]:
    """V(b, w) by backward recursion and λ(b, w) = V(b+1, w) − V(b+1, w+1). The innings is cut into
    N_BALLS steps whatever its length: with `balls` legal balls (100 in The Hundred) each step is
    balls / N_BALLS of a ball, so the runs and the wicket chance per step are scaled to match."""
    f = balls / N_BALLS
    v = np.zeros((N_BALLS + 1, MAX_W + 1))
    per = N_BALLS // N_BUCKETS
    for b in range(N_BALLS - 1, -1, -1):
        o = b // per
        p = 1.0 - (1.0 - np.clip(pout[o], 0.0, 0.5)) ** f
        v[b, :MAX_W] = rate[o] * f + p * v[b + 1, 1:] + (1 - p) * v[b + 1, :MAX_W]
    lam = np.clip(v[1:, :MAX_W] - v[1:, 1:], 0.0, None)
    return v, lam


def _default_tables() -> tuple[np.ndarray, np.ndarray, float]:
    lam = np.zeros((N_BALLS, MAX_W))
    lam[:36] = DEFAULT_LAMBDA["powerplay"]
    lam[36:90] = DEFAULT_LAMBDA["middle"]
    lam[90:] = DEFAULT_LAMBDA["death"]
    return lam, np.full((N_BUCKETS, MAX_W), 0.05), 0.0


def _window(safe: str, has_m: bool, since: str | None, before: str | None) -> str:
    from cricdesk.scout.ratings.bayesian import _window_sql  # one window rule for the fit and this

    return _window_sql(safe, has_m, since, before)


def _ball_rows(
    db_path: Path | str, collection: str, since: str | None, before: str | None
) -> pl.DataFrame:
    """Every delivery of innings 1–2 with its state (balls bowled, wickets down) and outcomes."""
    safe = table_suffix(collection)
    with duckdb.connect(str(db_path), read_only=True) as con:
        have = _columns(con, f"balls_{safe}")
        tables = _tables(con)
        has_m = f"matches_{safe}" in tables and "match_id" in have
        mcols = _columns(con, f"matches_{safe}") if has_m else set()
        seq_ok = {"match_id", "innings_idx", "over", "ball_in_over"} <= have
        window = _window(safe, has_m, since, before)
        phase = "COALESCE(b.phase, 'middle')" if "phase" in have else "'middle'"
        inn = "LEAST(COALESCE(b.innings_idx, 0), 1)" if "innings_idx" in have else "0"
        ext = (
            "COALESCE(b.extras_wides, 0) + COALESCE(b.extras_noballs, 0)"
            if {"extras_wides", "extras_noballs"} <= have
            else (
                "CASE WHEN b.extras_type IN ('wides', 'noballs') THEN COALESCE(b.runs_extras, 0) "
                "ELSE 0 END"
                if "runs_extras" in have
                else "0"
            )
        )
        total = "COALESCE(b.runs_total, b.runs_batter)" if "runs_total" in have else "b.runs_batter"
        overs = "COALESCE(m.overs, 20)" if "overs" in mcols else "20"
        bpo = "COALESCE(m.balls_per_over, 6)" if "balls_per_over" in mcols else "6"
        dl = "m.outcome_method IS NOT NULL" if "outcome_method" in mcols else "FALSE"
        join_m = f"LEFT JOIN matches_{safe} m ON m.match_id = b.match_id" if has_m else ""
        if not has_m:
            overs, bpo, dl = "20", "6", "FALSE"
        not_w = ", ".join(f"'{k}'" for k in _NOT_A_WICKET)
        kinds = ", ".join(f"'{k}'" for k in _BOWLER_KINDS)
        main = "b.innings_idx <= 1" if "innings_idx" in have else "TRUE"
        kb = keyed_balls(con, collection)
        if seq_ok:
            order = "b.over, b.ball_in_over" + (", b.ball_id" if "ball_id" in have else "")
            state = """
                CAST(COALESCE(SUM(legal) OVER w, 0) AS BIGINT) AS k,
                CAST(COALESCE(SUM(wkt) OVER w, 0) AS BIGINT) AS wb"""
            win = f"""WINDOW w AS (PARTITION BY match_id, inn ORDER BY {order.replace("b.", "")}
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)"""
            extra_cols = "b.match_id, b.over, b.ball_in_over" + (
                ", b.ball_id" if "ball_id" in have else ""
            )
        else:
            state, win, extra_cols = "-1 AS k, 0 AS wb", "", "NULL AS match_id"
        df = con.execute(
            f"""
            WITH b AS (
                SELECT {extra_cols}, b.batter, b.bowler, {phase} AS phase, {inn} AS inn,
                       b.runs_batter AS runs, {total} AS runs_total, {ext} AS ext,
                       CASE WHEN b.extras_type IN ('wides') THEN 0 ELSE 1 END AS legal,
                       CASE WHEN b.player_out IS NOT NULL
                             AND COALESCE(b.wicket_kind, '') NOT IN ({not_w}) THEN 1 ELSE 0 END AS wkt,
                       CASE WHEN b.wicket_kind IN ({kinds}) AND b.player_out = b.batter
                            THEN 1 ELSE 0 END AS out_b,
                       {overs} * {bpo} AS sched, {overs} AS overs, {dl} AS dl
                FROM {kb} b {join_m}
                WHERE b.batter IS NOT NULL AND b.bowler IS NOT NULL AND {main} {window}
            )
            SELECT match_id, batter, bowler, phase, inn, runs, runs_total, ext, legal, wkt, out_b,
                   sched, overs, dl, {state}
            FROM b {win}
            """
        ).pl()
    return df


def league_tables(
    db_path: Path | str,
    collection: str,
    since: str | None = None,
    before: str | None = None,
) -> LeagueTables:
    """Fit the league's wicket-cost function and baselines, and every player's mix, on the window."""
    rows = _ball_rows(db_path, collection, since, before)
    rows = rows.with_columns(
        pl.col("phase")
        .replace_strict({p: i for i, p in enumerate(PHASES)}, default=1, return_dtype=pl.Int64)
        .alias("pi"),
        pl.col("inn").cast(pl.Int64).clip(0, 1),
        ((pl.col("legal") == 1) | (pl.col("out_b") == 1)).cast(pl.Int64).alias("trial"),
    )
    has_state = rows.height > 0 and int(rows["k"].max() or -1) >= 0
    if has_state:
        rows = rows.with_columns(
            (pl.col("k") * N_BUCKETS // pl.col("sched").clip(1)).clip(0, N_BUCKETS - 1).alias("o"),
            (pl.col("k") * N_BALLS // pl.col("sched").clip(1)).clip(0, N_BALLS - 1).alias("b"),
            pl.col("wb").clip(0, MAX_W - 1).alias("w"),
        )
        first = rows.filter(
            (pl.col("inn") == 0)
            & ~pl.col("dl")
            & (pl.col("overs") == 20)
            & (pl.col("k") < pl.col("sched"))
        )
        n_inn = first.select(pl.col("match_id").n_unique()).item() if first.height else 0
    else:
        n_inn = 0

    if n_inn >= MIN_INNINGS:
        g = first.group_by("o", "w").agg(
            pl.col("legal").sum(), pl.col("runs_total").sum(), pl.col("wkt").sum()
        )
        n = np.zeros((N_BUCKETS, MAX_W))
        runs = np.zeros_like(n)
        wk = np.zeros_like(n)
        for o, w, legal, rt, k in g.iter_rows():
            n[o, w] += legal
            runs[o, w] += rt
            wk[o, w] += k
        rate = _smooth(runs, n, _SHRINK_RUNS)
        pout = np.clip(_smooth(wk, n, _SHRINK_WKTS), 1e-4, 0.5)
        sched = int(first["sched"].mode().sort()[0])  # the league's innings length in balls
        v, lam = _value_function(rate, pout, sched)
        par = float(v[0, 0])
    else:
        lam, pout, par = _default_tables()
        n_inn = 0

    # league baselines by phase × innings
    base = rows.group_by("pi", "inn").agg(
        pl.col("legal").sum(),
        pl.col("trial").sum(),
        pl.col("runs").sum(),
        (pl.col("runs") + pl.col("ext")).sum().alias("conceded"),
        pl.col("out_b").sum(),
    )
    r = np.zeros((3, 2))
    rtot = np.zeros((3, 2))
    q = np.zeros((3, 2))
    tot = base.select(pl.all().sum()).row(0, named=True) if base.height else None
    for p in range(3):
        for c in range(2):
            cell = base.filter((pl.col("pi") == p) & (pl.col("inn") == c))
            src = cell.row(0, named=True) if cell.height and cell["legal"][0] >= 60 else tot
            if not src or not src["legal"]:
                r[p, c], rtot[p, c], q[p, c] = 1.2, 1.25, 0.05
                continue
            r[p, c] = src["runs"] / src["legal"]
            rtot[p, c] = src["conceded"] / src["legal"]
            q[p, c] = min(max(src["out_b"] / max(src["trial"], 1), 1e-4), 0.5)

    # each player's balls and wicket-weighted λ by phase × innings, per role
    if has_state:
        o_idx = rows["o"].to_numpy()
        w_idx = rows["w"].to_numpy()
        pw = pout[o_idx, w_idx]
        lw = lam[rows["b"].to_numpy(), w_idx]
    else:
        ph = rows["pi"].to_numpy()
        pw = np.ones(rows.height)
        lw = np.array([DEFAULT_LAMBDA[PHASES[i]] for i in ph]) if rows.height else np.zeros(0)
    rows = rows.with_columns(
        pl.Series("pw", pw * rows["trial"].to_numpy()),
        pl.Series("plw", pw * lw * rows["trial"].to_numpy()),
        (pl.col("pi") * 2 + pl.col("inn")).alias("cell"),
    )
    tables = LeagueTables(lam=lam, pout=pout, par=par, r=r, rtot=rtot, q=q, n_innings=int(n_inn))
    # fallback λ for a cell with no balls
    phase_lam = np.array([[DEFAULT_LAMBDA[p]] * 2 for p in PHASES]).reshape(-1)
    for role, key in (("batter", "batter"), ("bowler", "bowler")):
        charged = pl.col("runs") + (pl.col("ext") if role == "bowler" else 0)
        agg = rows.group_by(key, "cell").agg(
            pl.col("legal").sum(),
            pl.col("pw").sum(),
            pl.col("plw").sum(),
            charged.sum().alias("charged"),
            pl.col("out_b").sum(),
            pl.col("trial").sum(),
        )
        mix: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        totals: dict[str, np.ndarray] = {}
        for pid, cell, legal, sw, slw, ch, outs, trials in agg.iter_rows():
            balls, lw_cell = mix.setdefault(pid, (np.zeros(6), phase_lam.copy()))
            balls[cell] += legal
            if sw > 0:
                lw_cell[cell] = slw / sw
            totals.setdefault(pid, np.zeros((6, 4)))[cell] += (ch, outs, trials, legal)
        tables.mix[role] = mix
        tables.totals[role] = totals
    return tables


def observed_value(tables: LeagueTables, role: str, ids: list[str]) -> np.ndarray:
    """What each player actually did, in the same currency as `value`, from raw counts: runs per 100
    balls above the league's average ball in the window, each bowler-credited dismissal above (or
    below) the league's rate priced at the player's own wicket cost. NaN for no balls. Used by the
    backtest (a season's outcome, and the career-numbers baseline)."""
    r = tables.r.reshape(-1) if role == "batter" else tables.rtot.reshape(-1)
    q = tables.q.reshape(-1)
    out = np.full(len(ids), np.nan)
    for i, pid in enumerate(ids):
        t = tables.totals.get(role, {}).get(pid)
        if t is None or t[:, 3].sum() <= 0:
            continue
        lam = tables.mix[role][pid][1]
        runs, outs, trials, balls = t.T
        extra_runs = runs - r * balls
        extra_outs = outs - q * trials
        net = -extra_runs + lam * extra_outs if role == "bowler" else extra_runs - lam * extra_outs
        out[i] = 100.0 * net.sum() / balls.sum()
    return out


def _mix_arrays(
    tables: LeagueTables, role: str, ids: list[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(share of balls [N, 6], λ [N, 6], balls [N]) in id order; a player with no balls gets the
    league's own mix."""
    league = np.zeros(6)
    for balls, _ in tables.mix.get(role, {}).values():
        league += balls
    league = league / league.sum() if league.sum() > 0 else np.full(6, 1 / 6)
    fallback_lam = np.array([[DEFAULT_LAMBDA[p]] * 2 for p in PHASES]).reshape(-1)
    share = np.zeros((len(ids), 6))
    lam = np.zeros((len(ids), 6))
    n = np.zeros(len(ids))
    for i, pid in enumerate(ids):
        balls, lw = tables.mix.get(role, {}).get(pid, (np.zeros(6), fallback_lam))
        n[i] = balls.sum()
        share[i] = balls / n[i] if n[i] > 0 else league
        lam[i] = lw
    return share, lam, n


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _logit(p):
    return np.log(p / (1.0 - p))


def _recentre(v: np.ndarray, n: np.ndarray) -> np.ndarray:
    w = n / n.sum() if n.sum() > 0 else np.full(len(n), 1 / max(len(n), 1))
    return v - (v @ w)[:, None]


def batting_value(
    tables: LeagueTables,
    ids: list[str],
    scoring: np.ndarray,
    survival: np.ndarray,
) -> dict[str, np.ndarray]:
    """Per-draw batting value (runs per 100 balls above the league's average ball) for draws of
    [D, N] scoring / survival skills, with its scoring part and its wicket part."""
    share, lam, n = _mix_arrays(tables, "batter", ids)
    w = n / n.sum() if n.sum() > 0 else np.full(len(n), 1 / max(len(n), 1))
    e = np.exp(scoring)
    m = e / (e @ w)[:, None]  # run-rate multiplier vs the average ball
    ds = survival - (survival @ w)[:, None]
    r = tables.r.reshape(-1)
    q = tables.q.reshape(-1)
    rate_part = (m - 1.0) * (share @ r)[None, :]
    wkt_part = np.zeros_like(rate_part)
    for c in range(6):
        if not share[:, c].any():
            continue
        extra_outs = _sigmoid(_logit(q[c]) - ds) - q[c]
        wkt_part -= share[None, :, c] * lam[None, :, c] * extra_outs
    # each part re-centred on the league's average ball, so value = rate part + wicket part
    rate = _recentre(100.0 * rate_part, n)
    wkt = _recentre(100.0 * wkt_part, n)
    return {
        "value": rate + wkt,
        "rate": rate,
        "wkt": wkt,
        "lam": lam,
        "share": share,
    }


def bowling_value(
    tables: LeagueTables,
    ids: list[str],
    economy: np.ndarray,
    strike: np.ndarray,
) -> dict[str, np.ndarray]:
    """Per-draw bowling value: runs saved per 100 balls plus the runs his extra wickets are worth."""
    share, lam, n = _mix_arrays(tables, "bowler", ids)
    w = n / n.sum() if n.sum() > 0 else np.full(len(n), 1 / max(len(n), 1))
    e = np.exp(-economy)
    m = e / (e @ w)[:, None]  # runs conceded per ball vs the average ball
    dt = strike - (strike @ w)[:, None]
    rt = tables.rtot.reshape(-1)
    q = tables.q.reshape(-1)
    rate_part = (1.0 - m) * (share @ rt)[None, :]
    wkt_part = np.zeros_like(rate_part)
    for c in range(6):
        if not share[:, c].any():
            continue
        extra_wkts = _sigmoid(_logit(q[c]) + dt) - q[c]
        wkt_part += share[None, :, c] * lam[None, :, c] * extra_wkts
    # each part re-centred on the league's average ball, so value = rate part + wicket part
    rate = _recentre(100.0 * rate_part, n)
    wkt = _recentre(100.0 * wkt_part, n)
    return {
        "value": rate + wkt,
        "rate": rate,
        "wkt": wkt,
        "lam": lam,
        "share": share,
    }


def wicket_cost(lam: np.ndarray, share: np.ndarray) -> np.ndarray:
    """A player's average wicket cost (runs) over where he plays, by his share of balls."""
    return (lam * share).sum(axis=1)
