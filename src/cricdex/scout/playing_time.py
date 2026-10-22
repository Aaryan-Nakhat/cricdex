"""Playing time: who plays, and how many balls he gets when he does (docs/METHODOLOGY.md §6c).

A player's worth to a side over a season is not his rate per 100 balls: it is

    expected season value = P(plays a match | in the squad) × his contribution per match

and his contribution per match is the runs he adds over a replacement in the balls he actually gets:

    contribution = (batting value − replacement batting value for his slot)  × balls faced per match / 100
                 + (bowling value − replacement bowling value for his group) × balls bowled per match / 100

all in the runs currency of `ratings/runs_value.py` (runs per 100 balls above the league's average ball).
This module fits the three pieces from real IPL XIs (Cricsheet `match_players_<league>`, the XI of every
match, and the ball-by-ball record), each out of time:

1. **Usage.** For every player and match: was he in the XI (or the impact player, 2023+), his batting
   position, his legal balls faced and bowled, and his side's legal balls in the innings.
2. **Expected balls** (`BallsModel`). His share of his side's balls when he plays, batting and bowling
   apart, as a credibility (shrinkage) estimate: his past IPL matches (recent seasons count more), his
   matches in the other leagues (discounted: a different side uses him differently) and the mean share of
   players of his role, weighted by fitted pseudo-counts. Times the IPL's balls per innings.
3. **Replacement levels.** What a side gets from the balls its fringe players play (players who played
   fewer than half of their side's matches that season), balls-weighted, per batting-slot group (top 1-3,
   middle 4-5, lower middle 6-7, tail 8-11, as the ratings' slot priors) and bowling group (frontline:
   15+ balls a match; part-time).
4. **P(plays)** (`PlayModel`). A logistic model of the share of his side's matches a squad player plays
   (retained and bought players of every season with a complete retained list, 2018 on), from what is
   known at the auction: where his contribution ranks in his squad (the projected XI and the distance to
   its last place, overseas players against the four overseas places), IPL experience, age, his share of
   matches last season (availability), keeper, and last season's captaincy.

Fielding is left out: Cricsheet records completed catches, run-outs and stumpings, not chances, drops or
runs saved, so a fielding value in runs can't be identified from it.

Everything here is Python only: the site export stores each player's `contrib`, `p_play` and
`season_value`, and the shared code (`web_parity/*` ⇄ `site/src/lib/*`) reads them.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

from cricdex.common.sql import _tables, keyed_balls, materialize_keyed, table_suffix
from cricdex.config import DATA_DIR

VERSION = "2026.10-1"
CACHE_DIR = DATA_DIR / "metrics" / ".playing_time"
MODEL_PATH = Path(__file__).resolve().parents[3] / "config" / "playing_time_model.json"

ROLES = ("batter", "bowler", "all_rounder", "keeper")
SLOT_GROUPS = ("top", "middle", "lower", "tail")  # batting positions 1-3, 4-5, 6-7, 8-11
BOWL_GROUPS = ("frontline", "part_time")
FRONTLINE_BALLS = (
    15.0  # balls bowled per match he plays: a frontline bowler (the ratings' prior groups)
)
FRINGE_SHARE = (
    0.5  # played fewer than this share of his side's matches in a season: a fringe player
)
LEAGUE_MATCHES = 14  # each side's league-stage matches (IPL 2022-2026): the season in season value
RECENT_SEASONS = 3  # the IPL's balls per innings: the mean of the last seasons before the forecast
XI_SIZE = 11
XI_OVERSEAS = 4


def slot_group(pos: float | None) -> str:
    """Batting position → the ratings' slot group (bayesian._slot_group): None (never batted) = tail."""
    if pos is None or (isinstance(pos, float) and math.isnan(pos)):
        return "tail"
    if pos <= 3:
        return "top"
    if pos <= 5:
        return "middle"
    if pos <= 7:
        return "lower"
    return "tail"


# ---- 1. usage: one row per player per match he played ------------------------------------------------


def usage(con: duckdb.DuckDBPyConnection, col: str) -> pl.DataFrame:
    """Every player in every XI of league `col` (Cricsheet's `match_players_<col>`, impact players
    included from 2023): match, date, side, his batting position (None = did not bat), legal balls
    faced and bowled, and his side's legal balls batted and bowled in the match. Super overs left out."""
    safe = table_suffix(col)
    if f"match_players_{safe}" not in _tables(con) or f"balls_{safe}" not in _tables(con):
        return pl.DataFrame()
    materialize_keyed(con, col)
    kb = keyed_balls(con, col)
    q = f"""
    WITH b AS (
        SELECT match_id, match_date, innings_idx, batting_team, bowling_team, over, ball_in_over,
               batter, non_striker, bowler,
               COALESCE(extras_wides, 0) = 0 AS legal_bat,
               COALESCE(extras_wides, 0) = 0 AND COALESCE(extras_noballs, 0) = 0 AS legal_bowl
        FROM {kb} WHERE innings_idx <= 1
    ),
    arrive AS (
        SELECT match_id, innings_idx, batting_team AS team, p AS cid, MIN(k) AS k FROM (
            SELECT match_id, innings_idx, batting_team, batter AS p,
                   over * 1000 + ball_in_over * 2 AS k FROM b
            UNION ALL
            SELECT match_id, innings_idx, batting_team, non_striker,
                   over * 1000 + ball_in_over * 2 + 1 FROM b
        ) WHERE p IS NOT NULL GROUP BY 1, 2, 3, 4
    ),
    pos AS (
        SELECT match_id, team, cid,
               ROW_NUMBER() OVER (PARTITION BY match_id, innings_idx ORDER BY k, cid) AS bat_pos
        FROM arrive
    ),
    faced AS (
        SELECT match_id, batting_team AS team, batter AS cid, SUM(CAST(legal_bat AS INT)) AS faced
        FROM b GROUP BY 1, 2, 3
    ),
    bowled AS (
        SELECT match_id, bowling_team AS team, bowler AS cid, SUM(CAST(legal_bowl AS INT)) AS bowled
        FROM b GROUP BY 1, 2, 3
    ),
    tbat AS (
        SELECT match_id, batting_team AS team, SUM(CAST(legal_bat AS INT)) AS team_faced
        FROM b GROUP BY 1, 2
    ),
    tbowl AS (
        SELECT match_id, bowling_team AS team, SUM(CAST(legal_bowl AS INT)) AS team_bowled
        FROM b GROUP BY 1, 2
    )
    SELECT p.match_id, CAST(m.match_date AS VARCHAR) AS date, p.team, p.identifier AS cid,
           pos.bat_pos, COALESCE(f.faced, 0) AS faced, COALESCE(w.bowled, 0) AS bowled,
           tb.team_faced, tw.team_bowled
    FROM match_players_{safe} p
    JOIN matches_{safe} m USING (match_id)
    LEFT JOIN pos ON pos.match_id = p.match_id AND pos.team = p.team AND pos.cid = p.identifier
    LEFT JOIN faced f ON f.match_id = p.match_id AND f.team = p.team AND f.cid = p.identifier
    LEFT JOIN bowled w ON w.match_id = p.match_id AND w.team = p.team AND w.cid = p.identifier
    LEFT JOIN tbat tb ON tb.match_id = p.match_id AND tb.team = p.team
    LEFT JOIN tbowl tw ON tw.match_id = p.match_id AND tw.team = p.team
    WHERE p.identifier IS NOT NULL
    """
    df = pl.from_arrow(con.execute(q).arrow())
    return df.with_columns(
        pl.lit(col).alias("league"),
        pl.col("date").str.slice(0, 10),
        pl.col("date").str.slice(0, 4).cast(pl.Int64).alias("season"),
        pl.col("bat_pos").cast(pl.Float64),
        pl.col("faced").cast(pl.Float64),
        pl.col("bowled").cast(pl.Float64),
        pl.col("team_faced").cast(pl.Float64),
        pl.col("team_bowled").cast(pl.Float64),
    )


def usage_all(db_path: Path | str, cols: list[str], refresh: bool = False) -> pl.DataFrame:
    """`usage` for every league in `cols`, cached as one parquet (rebuilt when a league is missing or
    `refresh`)."""
    f = CACHE_DIR / "usage.parquet"
    if f.exists() and not refresh:
        u = pl.read_parquet(f)
        if set(cols) <= set(u["league"].unique().to_list()):
            return u.filter(pl.col("league").is_in(cols))
    parts = []
    with duckdb.connect(str(db_path), read_only=True) as con:
        for c in cols:
            d = usage(con, c)
            if d.height:
                parts.append(d)
    u = pl.concat(parts, how="vertical_relaxed")
    f.parent.mkdir(parents=True, exist_ok=True)
    u.write_parquet(f)
    return u


# ---- 2. expected balls: a credibility estimate of his share of his side's balls ----------------------


@dataclass
class BallsModel:
    """His share of his side's legal balls when he plays (one per discipline), estimated as

        share = (Σ_ipl d^age × his balls + k_o × Σ_other d^age × his balls + k0 × team balls × μ_role)
                / (Σ_ipl d^age × team balls + k_o × Σ_other d^age × team balls + k0 × team balls)

    i.e. his past matches' share, recent seasons weighted by d per season back, the other leagues' matches
    discounted by k_o, shrunk toward the mean share of his role μ_role with k0 matches' weight (`team
    balls` = a typical innings, so k0 counts in matches). Fitted by weighted least squares on the share he
    then had in each IPL season (weight = his matches that season)."""

    discipline: str  # "bat" | "bowl"
    k0: float = 3.0
    k_o: float = 0.5
    decay: float = 0.7
    mu: dict[str, float] = field(default_factory=dict)
    trained_on: tuple[int, int] = (0, 0)

    def predict(self, prior: dict[str, float], role: str) -> float:
        """`prior` = {"ipl_n", "ipl_b", "oth_n", "oth_b"}: decayed matches and decayed share-weighted
        matches (Σ d^age × his balls ÷ team balls) in the IPL and the other leagues."""
        mu = self.mu.get(role, self.mu.get("all", 0.1))
        num = prior["ipl_b"] + self.k_o * prior["oth_b"] + self.k0 * mu
        den = prior["ipl_n"] + self.k_o * prior["oth_n"] + self.k0
        return num / den if den > 0 else mu

    def to_json(self) -> dict:
        return {"discipline": self.discipline, "k0": self.k0, "k_o": self.k_o, "decay": self.decay,
                "mu": self.mu, "trained_on": list(self.trained_on)}  # fmt: skip

    @staticmethod
    def from_json(d: dict) -> BallsModel:
        return BallsModel(d["discipline"], d["k0"], d["k_o"], d["decay"], dict(d["mu"]),
                          tuple(d.get("trained_on") or (0, 0)))  # fmt: skip


def prior_usage(
    u: pl.DataFrame, before: str, decay: float, target: str = "ipl", years: int = 4
) -> dict[str, dict[str, float]]:
    """cid → {ipl_n, ipl_b, oth_n, oth_b, bat_pos (median of his IPL positions, else other leagues')}
    from his matches before `before` (ISO date) in the last `years` seasons, each match weighted
    decay^(seasons back) (the season of `before` counts as 0 back when its matches precede it).
    `*_b` sum his share of his side's balls per match; batting and bowling are kept apart as
    `bat_*` / `bowl_*`."""
    y0 = int(before[:4])
    w = u.filter(
        (pl.col("date") < before)
        & (pl.col("season") >= y0 - years)
        & (pl.col("team_faced").fill_null(0) > 0)
        & (pl.col("team_bowled").fill_null(0) > 0)
    ).with_columns(
        (pl.lit(decay) ** (y0 - pl.col("season")).clip(0, None)).alias("w"),
        (pl.col("league") == target).alias("is_t"),
        (pl.col("faced") / pl.col("team_faced").clip(1, None)).alias("sf"),
        (pl.col("bowled") / pl.col("team_bowled").clip(1, None)).alias("sb"),
    )
    agg = w.group_by("cid", "is_t").agg(
        pl.col("w").sum().alias("n"),
        (pl.col("w") * pl.col("sf")).sum().alias("bf"),
        (pl.col("w") * pl.col("sb")).sum().alias("bb"),
        pl.col("bat_pos").median().alias("pos"),
    )
    out: dict[str, dict[str, float]] = {}
    for cid, is_t, n, bf, bb, pos in agg.iter_rows():
        d = out.setdefault(cid, {"ipl_n": 0.0, "oth_n": 0.0, "bat_ipl_b": 0.0, "bat_oth_b": 0.0,
                                 "bowl_ipl_b": 0.0, "bowl_oth_b": 0.0, "pos_ipl": None,
                                 "pos_oth": None})  # fmt: skip
        k = "ipl" if is_t else "oth"
        d[f"{k}_n"] += float(n)
        d[f"bat_{k}_b"] += float(bf)
        d[f"bowl_{k}_b"] += float(bb)
        d[f"pos_{k}"] = None if pos is None else float(pos)
    for d in out.values():
        d["bat_pos"] = d["pos_ipl"] if d["pos_ipl"] is not None else d["pos_oth"]
    return out


def _disc(p: dict[str, float], disc: str) -> dict[str, float]:
    return {"ipl_n": p["ipl_n"], "oth_n": p["oth_n"], "ipl_b": p[f"{disc}_ipl_b"],
            "oth_b": p[f"{disc}_oth_b"]}  # fmt: skip


EMPTY_PRIOR = {"ipl_n": 0.0, "oth_n": 0.0, "bat_ipl_b": 0.0, "bat_oth_b": 0.0, "bowl_ipl_b": 0.0,
               "bowl_oth_b": 0.0, "pos_ipl": None, "pos_oth": None, "bat_pos": None}  # fmt: skip


def team_balls(u: pl.DataFrame, before: str, target: str = "ipl") -> float:
    """The target league's mean legal balls per innings over the RECENT_SEASONS seasons before
    `before` (the multiplier from a share to balls)."""
    y0 = int(before[:4])
    t = (
        u.filter(
            (pl.col("league") == target)
            & (pl.col("date") < before)
            & (pl.col("season") >= y0 - RECENT_SEASONS)
        )
        .group_by("match_id", "team")
        .agg(pl.col("team_faced").first())
    )
    return float(t["team_faced"].mean()) if t.height else 113.0


def expected_usage(
    u: pl.DataFrame,
    before: str,
    cids,
    bm: dict[str, BallsModel],
    T: float,
    roles: dict[str, str],
) -> dict[str, dict]:
    """cid -> {faced, bowled, pos}: his expected legal balls faced and bowled per match he plays (the
    expected-balls models x the IPL's balls per innings `T`) and his usual batting position, from his
    matches before `before`. A player with no match in the window gets his role's mean share."""
    pri = {d: prior_usage(u, before, d) for d in {bm["bat"].decay, bm["bowl"].decay}}
    out = {}
    for cid in cids:
        pb = pri[bm["bat"].decay].get(cid, EMPTY_PRIOR)
        pw = pri[bm["bowl"].decay].get(cid, EMPTY_PRIOR)
        role = roles.get(cid, "batter")
        out[cid] = {
            "faced": bm["bat"].predict(_disc(pb, "bat"), role) * T,
            "bowled": bm["bowl"].predict(_disc(pw, "bowl"), role) * T,
            "pos": pb.get("bat_pos"),
        }
    return out


# ---- 3. replacement levels -----------------------------------------------------------------------------


def replacement_levels(
    u: pl.DataFrame, history: pl.DataFrame, first: int, last: int, target: str = "ipl"
) -> dict[str, dict[str, float]]:
    """{"bat": {slot group: value}, "bowl": {group: value}}: the balls-weighted mean of the season
    values (`history`: forecast.season_history, runs per 100 balls above that season's average ball)
    of fringe players, those who played fewer than FRINGE_SHARE of their side's matches in the season,
    in seasons first..last. A batter's group is his median position that season, a bowler's frontline
    when he bowled FRONTLINE_BALLS+ balls a match he played."""
    t = u.filter(
        (pl.col("league") == target) & (pl.col("season") >= first) & (pl.col("season") <= last)
    )
    tm = t.group_by("season", "team").agg(pl.col("match_id").n_unique().alias("team_m"))
    ps = (
        t.group_by("season", "team", "cid")
        .agg(
            pl.len().alias("m"),
            pl.col("bat_pos").median().alias("pos"),
            pl.col("bowled").sum().alias("bowled"),
        )
        .join(tm, on=["season", "team"])
    )
    # a player in two sides in a season (a mid-season move) is judged by his larger share
    ps = ps.with_columns((pl.col("m") / pl.col("team_m")).alias("share"))
    best = ps.sort("share", descending=True).unique(["season", "cid"], keep="first")
    out: dict[str, dict[str, float]] = {"bat": {}, "bowl": {}}
    h = history.filter((pl.col("season") >= first) & (pl.col("season") <= last))
    j = h.join(best.rename({"cid": "cricsheet_id"}), on=["cricsheet_id", "season"], how="inner")
    fringe = j.filter(pl.col("share") < FRINGE_SHARE)
    acc: dict[tuple[str, str], list[float]] = {}
    for role, v, n, pos, bowled, m in fringe.select(
        "role", "value_obs", "balls", "pos", "bowled", "m"
    ).iter_rows():
        if v is None or n is None or n <= 0 or not math.isfinite(v):
            continue
        if role == "batter":
            k = ("bat", slot_group(pos))
        else:
            k = ("bowl", "frontline" if bowled / max(m, 1) >= FRONTLINE_BALLS else "part_time")
        a = acc.setdefault(k, [0.0, 0.0])
        a[0] += n
        a[1] += n * v
    for (d, g), (n, s) in acc.items():
        out[d][g] = round(s / n, 3)
    return out


# ---- 4. contribution per match ---------------------------------------------------------------------------


def contribution(
    bat: tuple[float, float] | None,
    bowl: tuple[float, float] | None,
    faced: float,
    bowled: float,
    pos: float | None,
    repl: dict[str, dict[str, float]],
) -> tuple[float, float, dict]:
    """(runs per match above replacement, its sd, the parts) from his (value, sd) per discipline (None
    = no rating: counted at replacement), his expected legal balls faced and bowled per match, his usual
    batting position and the replacement levels."""
    rb = repl["bat"].get(slot_group(pos), 0.0)
    rw = repl["bowl"]["frontline" if bowled >= FRONTLINE_BALLS else "part_time"]
    vb, sb = bat if bat else (rb, 0.0)
    vw, sw = bowl if bowl else (rw, 0.0)
    cb = (vb - rb) * faced / 100.0
    cw = (vw - rw) * bowled / 100.0
    sd = math.hypot(sb * faced / 100.0, sw * bowled / 100.0)
    return cb + cw, sd, {"bat": cb, "bowl": cw, "repl_bat": rb, "repl_bowl": rw}


# ---- 5. P(plays): the share of his side's matches a squad player plays ------------------------------------

PLAY_FEATURES_ALL = (
    "contrib", "in_xi", "margin", "rank_log", "overseas", "os_out", "os_rank_gt4",
    "ipl_exp", "never_ipl", "age", "age_gt32", "last_share", "no_last", "keeper", "captain",
    "impact_era",
)  # fmt: skip


def projected_xi(squad: list[dict]) -> dict[str, dict]:
    """A squad's projected XI from its players' contributions (`c`), greedy as Bid plan picks it: best
    first, at most XI_OVERSEAS overseas, at least one keeper, five bowling and six batting options
    (`bowl` / `bat` flags). Returns cid → {in_xi, margin, rank, os_rank}: the margin is his
    contribution minus the selection line (the mean of the last player in and the first one out)."""
    order = sorted(squad, key=lambda p: (-p["c"], p["cid"]))
    chosen: list[dict] = []
    out_list: list[dict] = []
    k = bw = bt = os_n = 0
    for p in order:
        if len(chosen) >= XI_SIZE or (p["os"] and os_n >= XI_OVERSEAS):
            out_list.append(p)
            continue
        nk, nbw, nbt = k + p["k"], bw + p["bowl"], bt + p["bat"]
        room = XI_SIZE - len(chosen) - 1
        if max(0, 5 - nbw) + max(max(0, 1 - nk), max(0, 6 - nbt)) > room:
            out_list.append(p)
            continue
        chosen.append(p)
        k, bw, bt = nk, nbw, nbt
        os_n += p["os"]
    last_in = min((p["c"] for p in chosen), default=0.0)
    first_out = max((p["c"] for p in out_list), default=last_in)
    line = 0.5 * (last_in + first_out)
    ids = {p["cid"] for p in chosen}
    res: dict[str, dict] = {}
    os_rank = 0
    for i, p in enumerate(order):
        if p["os"]:
            os_rank += 1
        res[p["cid"]] = {"in_xi": p["cid"] in ids, "margin": p["c"] - line, "rank": i + 1,
                         "os_rank": os_rank if p["os"] else 0}  # fmt: skip
    return res


def play_features(r: dict) -> dict[str, float]:
    """One squad player's P(plays) inputs (all known at the auction). `r` keys: contrib, in_xi, margin,
    rank, overseas, os_rank, ipl_matches, age, last_share (None = not in a squad last season), keeper,
    captain, season."""
    age = r.get("age")
    a = (age - 28.0) if age is not None else 0.0
    m = max(-6.0, min(6.0, r["margin"]))
    ov = 1.0 if r["overseas"] else 0.0
    ls = r.get("last_share")
    return {
        "contrib": max(-6.0, min(12.0, r["contrib"])),
        "in_xi": 1.0 if r["in_xi"] else 0.0,
        "margin": m,
        "rank_log": math.log(max(r["rank"], 1)),
        "overseas": ov,
        "os_out": ov * (1.0 if r["os_rank"] > XI_OVERSEAS else 0.0),
        "os_rank_gt4": ov * max(0.0, r["os_rank"] - XI_OVERSEAS),
        "ipl_exp": math.log1p(max(r.get("ipl_matches") or 0.0, 0.0)),
        "never_ipl": 1.0 if not r.get("ipl_matches") else 0.0,
        "age": a / 5.0,
        "age_gt32": max(0.0, a - 4.0) / 5.0,
        "last_share": ls if ls is not None else 0.0,
        "no_last": 0.0 if ls is not None else 1.0,
        "keeper": 1.0 if r.get("keeper") else 0.0,
        "captain": 1.0 if r.get("captain") else 0.0,
        "impact_era": 1.0 if (r.get("season") or 0) >= 2023 else 0.0,
    }


# A free agent (in the auction pool, not in a squad) has no squad to rank in, and whether he plays
# at all also depends on whether a franchise buys him. His P(plays) is fitted on every free agent of
# every past auction pool (active, eligible, not retained): the share of a side's matches he then
# played (0 when nobody bought or picked him). That is the fitted replacement of the hand-set
# IPL-relevance curve, which tried to say exactly this.
FA_FEATURES_ALL = (
    "contrib", "margin", "ipl_exp", "never_ipl", "gap", "age", "age_gt32", "last_share",
    "played_last", "overseas", "keeper", "captain", "impact_era",
)  # fmt: skip
GAP_MAX = 6.0


def fa_features(r: dict) -> dict[str, float]:
    """A free agent's P(plays) inputs (known before the auction). `r` keys: contrib, margin (his
    contribution minus the median squad's XI line), ipl_matches, gap (years since his last IPL match,
    None = never), age, last_share (his share of a side's matches last IPL season, None = none),
    overseas, keeper, captain, season."""
    age = r.get("age")
    a = (age - 28.0) if age is not None else 0.0
    gap = r.get("gap")
    ls = r.get("last_share")
    return {
        "contrib": max(-6.0, min(12.0, r["contrib"])),
        "margin": max(-6.0, min(6.0, r["margin"])),
        "ipl_exp": math.log1p(max(r.get("ipl_matches") or 0.0, 0.0)),
        "never_ipl": 1.0 if gap is None else 0.0,
        "gap": 0.0 if gap is None else min(max(gap, 0.0), GAP_MAX),
        "age": a / 5.0,
        "age_gt32": max(0.0, a - 4.0) / 5.0,
        "last_share": ls if ls is not None else 0.0,
        "played_last": 1.0 if ls else 0.0,
        "overseas": 1.0 if r.get("overseas") else 0.0,
        "keeper": 1.0 if r.get("keeper") else 0.0,
        "captain": 1.0 if r.get("captain") else 0.0,
        "impact_era": 1.0 if (r.get("season") or 0) >= 2023 else 0.0,
    }


def xi_line(squad: list[dict]) -> float:
    """A squad's selection line (`projected_xi`): the mean of the last player in and the first out."""
    x = projected_xi(squad)
    if not x:
        return 0.0
    # margin = c − line for any member, so line = c − margin
    cid, v = next(iter(x.items()))
    c = next(p["c"] for p in squad if p["cid"] == cid)
    return c - v["margin"]


def fit_share_logit(
    X: np.ndarray, y: np.ndarray, w: np.ndarray, alpha: float = 1.0, iters: int = 60
) -> np.ndarray:
    """A fractional (quasi-binomial) logistic regression with an L2 penalty `alpha` on the slopes:
    y = share of matches played in [0, 1], w = his side's matches. Newton steps. Returns [intercept,
    slopes...] on X as given."""
    n, k = X.shape
    Z = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(k + 1)
    pen = np.full(k + 1, alpha)
    pen[0] = 0.0
    for _ in range(iters):
        eta = np.clip(Z @ beta, -30, 30)
        p = 1.0 / (1.0 + np.exp(-eta))
        g = Z.T @ (w * (y - p)) - pen * beta
        H = (Z * (w * p * (1 - p))[:, None]).T @ Z + np.diag(pen)
        step = np.linalg.solve(H, g)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


@dataclass
class PlayModel:
    features: tuple[str, ...]
    intercept: float
    coef: dict[str, float]
    trained_on: tuple[int, int] = (0, 0)

    def prob(self, f: dict[str, float]) -> float:
        t = self.intercept + sum(c * f[k] for k, c in self.coef.items())
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, t))))

    def to_json(self) -> dict:
        return {"features": list(self.features), "intercept": self.intercept, "coef": self.coef,
                "trained_on": list(self.trained_on)}  # fmt: skip

    @staticmethod
    def from_json(d: dict) -> PlayModel:
        return PlayModel(tuple(d["features"]), float(d["intercept"]),
                         {k: float(v) for k, v in d["coef"].items()},
                         tuple(d.get("trained_on") or (0, 0)))  # fmt: skip


def fit_play_model(rows: list[dict], feats: tuple[str, ...], alpha: float) -> PlayModel:
    """Fit P(plays) on rows ({"_f": the features (play_features or fa_features), "share", "team_m",
    "season"}), standardising the features and folding the coefficients back to raw units."""
    X = np.array([[r["_f"][k] for k in feats] for r in rows], dtype=float)
    y = np.array([r["share"] for r in rows], dtype=float)
    w = np.array([r["team_m"] for r in rows], dtype=float)
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    beta = fit_share_logit((X - mu) / sd, y, w / w.mean(), alpha)
    raw = beta[1:] / sd
    icpt = float(beta[0] - np.sum(raw * mu))
    seasons = [r["season"] for r in rows]
    return PlayModel(feats, icpt, {k: float(v) for k, v in zip(feats, raw, strict=True)},
                     (min(seasons), max(seasons)))  # fmt: skip


# ---- the shipped model file ---------------------------------------------------------------------------------


def load_model(path: Path | str | None = None) -> dict | None:
    p = Path(path) if path else MODEL_PATH
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---- applying the shipped model (the site export) ---------------------------------------------------------


def shipped_balls(model: dict) -> dict[str, BallsModel]:
    return {k: BallsModel.from_json(v) for k, v in model["balls"].items()}


def contributions(
    per_role: dict[str, dict[str, tuple[float, float]]],
    u: pl.DataFrame,
    before: str,
    roles: dict[str, str],
    model: dict,
) -> dict[str, dict]:
    """cid → {contrib, contrib_sd, bat, bowl (the two parts), faced, bowled, pos} for every cid in
    `per_role` ({"batter": (value, sd), "bowler": (value, sd)}, the pool's blend per role), his usage
    from matches before `before` and the shipped model."""
    bm = shipped_balls(model)
    T = float(model["balls_per_innings"])
    repl = model["replacement"]
    us = expected_usage(u, before, list(per_role), bm, T, roles)
    out = {}
    for cid, v in per_role.items():
        x = us[cid]
        c, sd, parts = contribution(v.get("batter"), v.get("bowler"), x["faced"], x["bowled"],
                                    x["pos"], repl)  # fmt: skip
        out[cid] = {"contrib": c, "contrib_sd": sd, "bat": parts["bat"], "bowl": parts["bowl"],
                    "faced": x["faced"], "bowled": x["bowled"], "pos": x["pos"]}  # fmt: skip
    return out


def squad_member(cid: str, c: float, role: str, overseas: bool) -> dict:
    """A player as `projected_xi` reads him."""
    return {"cid": cid, "c": c, "os": int(bool(overseas)), "k": int(role == "keeper"),
            "bowl": int(role in ("bowler", "all_rounder")),
            "bat": int(role in ("batter", "keeper", "all_rounder"))}  # fmt: skip


def p_play(player: dict, squad: list[dict], meta: dict, model: PlayModel, season: int) -> float:
    """P(plays a match) for `player` (a `squad_member`) in `squad` (the others, `squad_member`s; he is
    added if missing), with his `meta` = {age, ipl_matches, last_share, keeper, captain, overseas}."""
    sq = [p for p in squad if p["cid"] != player["cid"]] + [player]
    x = projected_xi(sq)[player["cid"]]
    r = {"contrib": player["c"], "in_xi": x["in_xi"], "margin": x["margin"], "rank": x["rank"],
         "os_rank": x["os_rank"], "season": season, **meta}  # fmt: skip
    return model.prob(play_features(r))


def p_play_free(meta: dict, model: PlayModel) -> float:
    """P(plays a match) next season for a free agent (`fa_features` keys in `meta`)."""
    return model.prob(fa_features(meta))


def season_value(p: float, contrib: float) -> float:
    """Expected runs above replacement over a season: P(plays) × contribution × league matches."""
    return p * contrib * LEAGUE_MATCHES
