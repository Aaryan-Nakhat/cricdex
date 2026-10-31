"""Time-aware ratings: a player's level now, not his career average (docs/METHODOLOGY.md §4b;
ROADMAP Tier D #34, I18).

The Bayesian rating (`bayesian.py`) has one skill per role for a whole career in a league: the context
is adjusted for, but the player's own level is not allowed to move. A 37-year-old's rating still carries
the seasons he played at 29, and a 19-year-old's his first season. Everything downstream (the
contribution per match, the auction pool's ranking, Bid plan, Keep, the market price's inputs) read it
as his level now. This module turns a career rating into a forecast of his level in the coming season:

    value now = career rating + E[ his level next season − his career-average level | his seasons ]

The shift comes from a state-space model of his season-by-season numbers in every auction-pool league,
fitted by maximum likelihood per group (batting; bowling, or pace and spin apart):

    level(y) = level(y − 1) + A(age(y)) − A(age(y − 1)) + N(0, q)      a random walk with an aging drift
    level(first season) ~ N(mu0, tau2)
    a season's value in league L, on the IPL scale:  a_L + b_L × value ~ N(level(y), R)
    R = b_L² × c × 100 / balls  (+ e for a league other than the IPL)
    P(he plays in year y | level) = Φ(b0[y] + bL × level(y) + bA(age(y)))       the selection model

`A` is the aging curve: piecewise linear in age through knots every four years (`KNOTS`), fitted, with
A(28) = 0. `a_L`, `b_L` are the fitted league translation (`scout/translation.py`). The curve is learned
within players (each player is compared only with himself). The selection model is the survivorship
correction: the players who decline are the ones who stop playing, so a curve fitted on the seasons
that were played is too kind to age (Lichtman 2009); a season he was at risk of playing and didn't is
evidence that his level fell.

The shift is the difference between two estimates from the same filter, his level next season and the
balls-weighted average of his levels over the seasons his rating rests on (each league's seasons
weighted as the blend weights that league), so what the season values don't share with the rating
(opponents, grounds, a league's translation offset) cancels. It is computed with a two-part state
(level, running weighted sum of levels) in a Kalman filter.

Fitted and chosen by `scripts/rating_drift_fit.py` (frozen protocol: candidates declared first, chosen
on 2019-2024 walk-forward, tested once on 2025-26) into `config/rating_drift.json`. The chosen one has
no random walk (q = 0): the shift is then exactly A(age next season) − the weighted mean of A over his
seasons. Every random-walk candidate predicted next season worse than the career rating.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl

from cricdesk.config import DATA_DIR

VERSION = "2026.10-1"
MODEL_PATH = Path(__file__).resolve().parents[4] / "config" / "rating_drift.json"
CACHE_DIR = DATA_DIR / "metrics" / ".drift"
OBS_CACHE = CACHE_DIR / "season_obs.parquet"

# The aging curve's knots (ages). A basis, not a cut-off: every knot's level is fitted; the curve is
# linear between them and flat beyond the ends.
KNOTS = (16.0, 20.0, 24.0, 28.0, 32.0, 36.0, 40.0, 44.0)
AGE_REF = 28.0  # A(28) = 0: only differences of A are identified
ROLES = ("batter", "bowler")
GROUPS = (
    "bat",
    "pace",
    "spin",
    "bowl",
)  # "bowl": bowling of unknown style (the pooled bowling curve)
CATEGORY_GROUP = {"seam": "pace", "spin": "spin"}


def group_of(role: str, category: str | None) -> str:
    """The parameter group of a (role, bowling category): batting is one group; bowling is pace or
    spin from the player master's `bowling_category`, else the pooled bowling group."""
    if role == "batter":
        return "bat"
    return CATEGORY_GROUP.get(category or "", "bowl")


def age_on(dob: str | None, year: int) -> float | None:
    """Age in years on 15 April of `year` (the forecast's convention, forecast.age_on)."""
    if not dob:
        return None
    try:
        d = _dt.date.fromisoformat(str(dob)[:10])
    except ValueError:
        return None
    return (_dt.date(year, 4, 15) - d).days / 365.25


def curve_at(curve, age):
    """The aging curve (levels at KNOTS) at `age` (scalar or array): linear between knots, flat
    beyond."""
    return np.interp(np.clip(age, KNOTS[0], KNOTS[-1]), KNOTS, np.asarray(curve, dtype=float))


@dataclass
class GroupParams:
    """One group's fitted parameters (see the module docstring)."""

    mu0: float
    tau2: float
    q: float
    c: float
    e: float
    curve: tuple[float, ...] = field(default_factory=lambda: tuple(0.0 for _ in KNOTS))
    curve_sd: tuple[float, ...] | None = None  # the curve's standard errors (inverse Hessian)
    n_keys: int = 0
    n_obs: int = 0
    nll: float = 0.0
    # the selection model (whether he plays a season, given his level): {"bL", "bA", "b0": {year: …}}
    sel: dict | None = None

    def to_json(self) -> dict:
        d = {
            "mu0": round(self.mu0, 4), "tau2": round(self.tau2, 4), "q": round(self.q, 5),
            "c": round(self.c, 3), "e": round(self.e, 4),
            "curve": [round(float(x), 4) for x in self.curve],
            "n_keys": self.n_keys, "n_obs": self.n_obs, "nll": round(self.nll, 2),
        }  # fmt: skip
        if self.curve_sd is not None:
            d["curve_sd"] = [round(float(x), 4) for x in self.curve_sd]
        if self.sel is not None:
            d["sel"] = {"bL": round(self.sel["bL"], 6), "bA": [round(x, 4) for x in self.sel["bA"]],
                        "b0": {k: round(v, 4) for k, v in self.sel["b0"].items()}}  # fmt: skip
        return d

    @staticmethod
    def from_json(d: dict) -> GroupParams:
        return GroupParams(
            float(d["mu0"]), float(d["tau2"]), float(d["q"]), float(d["c"]), float(d["e"]),
            tuple(float(x) for x in d["curve"]),
            tuple(float(x) for x in d["curve_sd"]) if d.get("curve_sd") else None,
            int(d.get("n_keys") or 0), int(d.get("n_obs") or 0), float(d.get("nll") or 0.0),
            d.get("sel"),
        )  # fmt: skip


@dataclass
class DriftModel:
    """Per-group parameters plus the age imputed at a player's first season when his date of birth
    is unknown (fitted: the median of the known ones)."""

    groups: dict[str, GroupParams]
    debut_age: float
    trained_before: str = ""
    candidate: str = ""

    def params(self, group: str) -> GroupParams:
        if group in self.groups:
            return self.groups[group]
        return self.groups["bowl"] if group in ("pace", "spin") and "bowl" in self.groups else (
            self.groups["bat"]
        )  # fmt: skip

    def to_json(self) -> dict:
        return {"groups": {g: p.to_json() for g, p in self.groups.items()},
                "debut_age": round(self.debut_age, 3), "trained_before": self.trained_before,
                "candidate": self.candidate}  # fmt: skip

    @staticmethod
    def from_json(d: dict) -> DriftModel:
        return DriftModel({g: GroupParams.from_json(p) for g, p in d["groups"].items()},
                          float(d["debut_age"]), d.get("trained_before", ""),
                          d.get("candidate", ""))  # fmt: skip


def load_model(path: Path | str | None = None, which: str = "model") -> DriftModel | None:
    """The shipped model (`which` = "model", fitted on every season) or the one the protocol runs use
    ("model_le2024", fitted on seasons up to 2024). None when there is no file (the career rating is
    then used as it stands)."""
    p = Path(path) if path else MODEL_PATH
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    m = d.get(which)
    return DriftModel.from_json(m) if m else None


# ---- 1. season values in every league -----------------------------------------------------------------


def _league_dates(db_path, col: str) -> tuple[str, str] | None:
    """The league's first and last match dates in the database (None when it isn't ingested: no
    database file, or no matches / balls table for it — the league is then skipped)."""
    import duckdb

    from cricdesk.common.sql import _tables, table_suffix

    if not Path(db_path).exists():
        return None
    safe = table_suffix(col)
    with duckdb.connect(str(db_path), read_only=True) as con:
        if not {f"matches_{safe}", f"balls_{safe}"} <= set(_tables(con)):
            return None
        lo, hi = con.execute(
            f"SELECT MIN(match_date), MAX(match_date) FROM matches_{safe}"
        ).fetchone()
    if lo is None:
        return None
    return str(lo)[:10], str(hi)[:10]


def _window_obs(db_path, col: str, since: str, before: str) -> list[tuple]:
    from cricdesk.scout.ratings import runs_value

    tab = runs_value.league_tables(db_path, col, since=since, before=before)
    out = []
    for role in ROLES:
        ids = list(tab.totals.get(role, {}))
        if not ids:
            continue
        vals = runs_value.observed_value(tab, role, ids)
        for pid, v in zip(ids, vals, strict=True):
            n = float(tab.totals[role][pid][:, 3].sum())
            if n > 0 and math.isfinite(v):
                out.append((pid, role, float(v), n))
    return out


def season_obs(db_path, cols, cuts=(), refresh: bool = False, log=None) -> pl.DataFrame:
    """Every player's value (`runs_value.observed_value`: runs per 100 balls above that window's
    average ball, wickets at his own wicket cost) and legal balls per league, role and calendar year
    (`cut` = ""), plus the part of a year before each date in `cuts` (`cut` = that date: what was known
    at an auction held during the year). Cached in OBS_CACHE; only missing windows are computed."""
    schema = {"league": pl.String, "role": pl.String, "cid": pl.String, "year": pl.Int64,
              "cut": pl.String, "value_obs": pl.Float64, "balls": pl.Float64}  # fmt: skip
    have = pl.read_parquet(OBS_CACHE) if OBS_CACHE.exists() and not refresh else pl.DataFrame(
        schema=schema
    )  # fmt: skip
    done = {(lg, y, c) for lg, y, c in have.select("league", "year", "cut").unique().iter_rows()}
    marker = CACHE_DIR / "season_obs_windows.json"
    mk = json.loads(marker.read_text()) if marker.exists() and not refresh else {}
    if isinstance(mk, list):  # the first format: the windows only
        mk = {"windows": mk}
    windows = {tuple(w) for w in mk.get("windows", [])} | done
    last_seen: dict[str, str] = dict(mk.get("max_date") or {})
    rows: list[tuple] = []
    changed = False
    for col in cols:
        span = _league_dates(db_path, col)
        if span is None:
            continue
        old = last_seen.get(col)
        if old is not None and old != span[1]:
            # the league has new matches since the cache was built: its windows from that year on
            # are recomputed
            y_old = int(old[:4])
            windows = {w for w in windows if not (w[0] == col and w[1] >= y_old)}
            have = have.filter(~((pl.col("league") == col) & (pl.col("year") >= y_old)))
            changed = True
        last_seen[col] = span[1]
        y_lo, y_hi = int(span[0][:4]), int(span[1][:4])
        todo = [(y, "") for y in range(y_lo, y_hi + 1)]
        todo += [(int(c[:4]), c) for c in cuts if c[5:] != "01-01" and y_lo <= int(c[:4]) <= y_hi]
        for y, c in todo:
            if (col, y, c) in windows:
                continue
            before = c or f"{y + 1}-01-01"
            for pid, role, v, n in _window_obs(db_path, col, f"{y}-01-01", before):
                rows.append((col, role, pid, y, c, v, n))
            windows.add((col, y, c))
            if log:
                log(f"  season values: {col} {y}{' to ' + c if c else ''}")
    if rows or changed:
        if rows:
            have = pl.concat([have, pl.DataFrame(rows, schema=schema, orient="row")])
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        have.write_parquet(OBS_CACHE)
    if windows and (rows or changed or mk.get("max_date") != last_seen):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"windows": sorted(windows), "max_date": last_seen}))
    return have


def obs_asof(obs: pl.DataFrame, date: str) -> pl.DataFrame:
    """The season values known before `date`: every full calendar year before its year, and its own
    year up to the date (the `cut` rows for that date)."""
    y = int(date[:4])
    full = obs.filter((pl.col("cut") == "") & (pl.col("year") < y))
    if date[5:] == "01-01":
        return full
    return pl.concat([full, obs.filter((pl.col("cut") == date) & (pl.col("year") == y))])


# ---- 2. sequences ---------------------------------------------------------------------------------------


@dataclass
class Seqs:
    """Every (player, role) with season values, as flat arrays the filters read.

    keys[k] = (cid, role); per key: group, first year index `y0`, age at the grid's first year
    `age0`; per observation: key index, year index, value on the IPL scale `t`, balls `n`, other
    league (1) or the IPL (0), b² (the translation slope squared), league."""

    keys: list[tuple[str, str]]
    group: np.ndarray
    y0: np.ndarray
    age0: np.ndarray
    age_known: np.ndarray
    k: np.ndarray
    y: np.ndarray
    t: np.ndarray
    n: np.ndarray
    other: np.ndarray
    b2: np.ndarray
    league: np.ndarray
    first_year: int
    last_year: int
    index: dict[tuple[str, str], int] = field(default_factory=dict)
    risk: np.ndarray | None = None  # [P, Y]: at risk of playing that year (the selection model)
    play: np.ndarray | None = None  # [P, Y]: played that year

    @property
    def n_years(self) -> int:
        return self.last_year - self.first_year + 1


def _trans(col: str, role: str, tmodel, which: str) -> tuple[float, float]:
    from cricdesk.scout import translation

    t = translation.table(col, role, tmodel, which)
    return (0.0, 1.0) if t is None else (float(t["a"]), float(t["b"]))


def debut_age(obs: pl.DataFrame, dob: dict[str, str]) -> float:
    """The median age at a player's first season in the data among players with a known date of
    birth (the age imputed when it is unknown)."""
    first = obs.group_by("cid").agg(pl.col("year").min())
    ages = [a for cid, y in first.iter_rows() if (a := age_on(dob.get(cid), y)) is not None]
    return float(np.median(ages)) if ages else 23.0


def sequences(
    obs: pl.DataFrame,
    dob: dict[str, str],
    category: dict[str, str | None],
    tmodel=None,
    which: str = "roles",
    imputed_debut_age: float | None = None,
    keys: set[tuple[str, str]] | None = None,
    last_year: int | None = None,
) -> Seqs:
    """Flatten the season values `obs` (one row per league, role, player and year) into `Seqs`;
    `keys` limits it to those (cid, role); `last_year` = the grid's last year (the year of the
    date the values are known at; default the last year with a value).

    The selection arrays: a player is at risk of playing in year y (after his first season) when a
    league he played before y has values in y (so a league whose data stops, Cricsheet's SMAT after
    2024, doesn't count as him being dropped); he played it when he has a value in any league."""
    from cricdesk.scout import translation

    tm = tmodel or translation.load_model()
    da = imputed_debut_age if imputed_debut_age is not None else debut_age(obs, dob)
    active = {(lg, int(y)) for lg, y in obs.select("league", "year").unique().iter_rows()}
    o = obs
    if keys is not None:
        kdf = pl.DataFrame(list(keys), schema={"cid": pl.String, "role": pl.String}, orient="row")
        o = o.join(kdf, on=["cid", "role"], how="inner")
    o = o.sort("cid", "role", "year", "league")
    first_year = int(o["year"].min()) if o.height else 2000
    last_year = max(int(o["year"].max()) if o.height else 2000, last_year or 0)
    tr = {}
    for col in o["league"].unique().to_list():
        for role in ROLES:
            tr[(col, role)] = _trans(col, role, tm, which)
    key_list: list[tuple[str, str]] = []
    index: dict[tuple[str, str], int] = {}
    ks, ys, ts, ns, oth, b2s, lgs = [], [], [], [], [], [], []
    firsts: list[int] = []
    for league, role, cid, year, v, n in o.select(
        "league", "role", "cid", "year", "value_obs", "balls"
    ).iter_rows():
        key = (cid, role)
        i = index.get(key)
        if i is None:
            i = index[key] = len(key_list)
            key_list.append(key)
            firsts.append(year)
        a, b = tr[(league, role)]
        ks.append(i)
        ys.append(year - first_year)
        ts.append(a + b * v)
        ns.append(n)
        oth.append(0.0 if league == "ipl" else 1.0)
        b2s.append(b * b)
        lgs.append(league)
    first_by_cid: dict[str, int] = {}
    for (cid, _r), f in zip(key_list, firsts, strict=True):
        first_by_cid[cid] = min(first_by_cid.get(cid, f), f)
    P, Y = len(key_list), last_year - first_year + 1
    grp = np.empty(P, dtype=object)
    age0 = np.empty(P)
    known = np.zeros(P, dtype=bool)
    for i, (cid, role) in enumerate(key_list):
        grp[i] = group_of(role, category.get(cid))
        a = age_on(dob.get(cid), first_year)
        if a is None:
            a = da + first_year - first_by_cid[cid]
        else:
            known[i] = True
        age0[i] = a
    k_arr, y_arr = np.array(ks, dtype=int), np.array(ys, dtype=int)
    play = np.zeros((P, Y), dtype=bool)
    play[k_arr, y_arr] = True
    risk = np.zeros((P, Y), dtype=bool)
    seen: list[set[str]] = [set() for _ in range(P)]
    by_key: dict[int, dict[int, set[str]]] = {}
    for i, y, lg in zip(ks, ys, lgs, strict=True):
        by_key.setdefault(i, {}).setdefault(y, set()).add(lg)
    for i in range(P):
        yrs = by_key.get(i, {})
        for y in range(Y):
            if seen[i] and any((lg, first_year + y) in active for lg in seen[i]):
                risk[i, y] = True
            seen[i] |= yrs.get(y, set())
    return Seqs(
        key_list, grp, np.array([f - first_year for f in firsts], dtype=int), age0, known,
        k_arr, y_arr, np.array(ts, dtype=float),
        np.array(ns, dtype=float), np.array(oth, dtype=float), np.array(b2s, dtype=float),
        np.array(lgs, dtype=object), first_year, last_year, index, risk, play,
    )  # fmt: skip


def subset(s: Seqs, mask_keys: np.ndarray) -> Seqs:
    """The keys where `mask_keys` is true (observations re-indexed)."""
    keep = np.flatnonzero(mask_keys)
    remap = -np.ones(len(s.keys), dtype=int)
    remap[keep] = np.arange(len(keep))
    om = mask_keys[s.k]
    keys = [s.keys[i] for i in keep]
    return Seqs(keys, s.group[keep], s.y0[keep], s.age0[keep], s.age_known[keep], remap[s.k[om]],
                s.y[om], s.t[om], s.n[om], s.other[om], s.b2[om], s.league[om], s.first_year,
                s.last_year, {k: i for i, k in enumerate(keys)},
                None if s.risk is None else s.risk[keep],
                None if s.play is None else s.play[keep])  # fmt: skip


# ---- 3. the filter -------------------------------------------------------------------------------------
#
# One state per (player, role): his level on the IPL scale, and, when the shift is computed, the running
# weighted sum of his levels. A year: the level drifts by the aging curve and a random-walk step; if he
# was at risk of playing, the fact that he played (or didn't) updates it through the selection model;
# then his season values do. Several values in one year (several leagues) are one combined update.
#
# The selection model (a shared-parameter model: Diggle & Kenward 1994; Little & Rubin, *Statistical
# Analysis with Missing Data*, ch. 15) is what keeps survivors from flattering the aging curve: a player
# who stops playing is more likely to have declined, so a season he didn't play is evidence about his
# level, not a gap. P(plays in year y | level) = Φ(b0[y] + bL × level + bA(age)), with a per-year
# intercept (how many leagues there were), a per-group slope and its own age curve (players retire with
# age at any level). The probit update of a Gaussian state is the usual moment-matched one (assumed
# density filtering; Rasmussen & Williams, *Gaussian Processes for Machine Learning*, §3.6).


def _cells(xp, s_k, s_y, P: int, Y: int, R, t, segment_sum):
    w = 1.0 / R
    cell = s_k * Y + s_y
    size = P * Y
    s0 = segment_sum(w, cell, size).reshape(P, Y)
    s1 = segment_sum(w * t, cell, size).reshape(P, Y)
    s2 = segment_sum(w * t * t, cell, size).reshape(P, Y)
    sl = segment_sum(xp.log(R), cell, size).reshape(P, Y)
    return s0, s1, s2, sl


def _year(xp, logcdf, logpdf, prm, state, y, s0y, s1y, s2y, sly, dAy, risk, play, sel_a):
    """One year for every player (numpy or jax.numpy, functional). state = (mL, vLL, mS, vLS, vSS,
    nll per player); prm = (mu0, tau2, q, bL, use_sel); sel_a [P] = b0[year] + bA(age)."""
    mu0, tau2, q, bL, use_sel, y0, W = prm
    mL, vLL, mS, vLS, vSS, nll = state
    prev = y0 < y
    now = y0 == y
    mL = xp.where(prev, mL + dAy, mL)
    vLL = xp.where(prev, vLL + q, vLL)
    mL = xp.where(now, mu0, mL)
    vLL = xp.where(now, tau2, vLL)
    vLS = xp.where(now, 0.0, vLS)
    vSS = xp.where(now, 0.0, vSS)
    mS = xp.where(now, 0.0, mS)
    if use_sel:
        sg = xp.where(play, 1.0, -1.0)
        s2 = 1.0 + bL * bL * vLL
        sq = xp.sqrt(s2)
        kap = (sel_a + bL * mL) / sq
        lp = logcdf(sg * kap)
        lam = xp.exp(logpdf(kap) - lp)
        fac = lam * (lam + sg * kap) * bL * bL / s2
        mL2 = mL + sg * lam * bL * vLL / sq
        mS2 = mS + sg * lam * bL * vLS / sq
        vSS2 = vSS - fac * vLS * vLS
        vLS2 = vLS - fac * vLL * vLS
        vLL2 = vLL - fac * vLL * vLL
        mL, mS = xp.where(risk, mL2, mL), xp.where(risk, mS2, mS)
        vLL, vLS, vSS = (
            xp.where(risk, vLL2, vLL),
            xp.where(risk, vLS2, vLS),
            xp.where(risk, vSS2, vSS),
        )
        nll = nll + xp.where(risk, -2.0 * lp, 0.0)
    has = s0y > 0
    s0s = xp.where(has, s0y, 1.0)
    rb = 1.0 / s0s
    dbar = s1y / s0s
    sv = rb + vLL
    inn = dbar - mL
    term = sly + (s2y - s1y**2 / s0s) + xp.log(s0s) + xp.log(sv) + inn**2 / sv
    nll = nll + xp.where(has, term, 0.0)
    kL = vLL / sv
    kS = vLS / sv
    mL2, mS2 = mL + kL * inn, mS + kS * inn
    vSS2 = vSS - kS * vLS
    vLS2 = vLS - kL * vLS
    vLL2 = vLL - kL * vLL
    mL, mS = xp.where(has, mL2, mL), xp.where(has, mS2, mS)
    vLL, vLS, vSS = xp.where(has, vLL2, vLL), xp.where(has, vLS2, vLS), xp.where(has, vSS2, vSS)
    # the running weighted sum: S += w L
    w = xp.where(y0 <= y, W, 0.0)
    mS = mS + w * mL
    vSS = vSS + 2 * w * vLS + w * w * vLL
    vLS = vLS + w * vLL
    return mL, vLL, mS, vLS, vSS, nll


# z = [mu0, ln tau2, ln q, ln c, ln e, the curve at the knots other than AGE_REF,
#      (selection) bL, bA at the knots other than AGE_REF, b0 per grid year]
N_FIXED = 5


def _unpack(z, xp, Y: int, fix_q0: bool, fix_curve, use_sel: bool):
    ref = KNOTS.index(AGE_REF)
    nk = len(KNOTS) - 1
    mu0, tau2 = z[0], xp.exp(z[1])
    q = 0.0 if fix_q0 else xp.exp(z[2])
    c, e = xp.exp(z[3]), xp.exp(z[4])
    i = N_FIXED
    if fix_curve is None:
        cv = xp.concatenate([z[i : i + ref], xp.zeros(1), z[i + ref : i + nk]])
        i += nk
    else:
        cv = xp.asarray(fix_curve, dtype=float)
    bL, bA, b0 = 0.0, None, None
    if use_sel:
        bL = z[i]
        bA = xp.concatenate([z[i + 1 : i + 1 + ref], xp.zeros(1), z[i + 1 + ref : i + 1 + nk]])
        b0 = z[i + 1 + nk : i + 1 + nk + Y]
    return mu0, tau2, q, c, e, cv, bL, bA, b0


def nll_fn(
    s: Seqs, fix_q0: bool = False, fix_curve: np.ndarray | None = None, use_sel: bool = True
):
    """A JAX function z → −2 log-likelihood (constants dropped) of one group's sequences (see
    `_unpack` for z). `fix_q0` holds q at 0 (no random walk), `fix_curve` holds the aging curve,
    `use_sel` adds the selection model."""
    import jax
    import jax.numpy as jnp
    from jax.scipy.stats import norm

    jax.config.update("jax_enable_x64", True)
    P, Y = len(s.keys), s.n_years
    kk, yy = jnp.asarray(s.k), jnp.asarray(s.y)
    t, n, oth, b2 = (jnp.asarray(x) for x in (s.t, s.n, s.other, s.b2))
    y0 = jnp.asarray(s.y0)
    ages = jnp.clip(jnp.asarray(s.age0)[:, None] + jnp.arange(Y)[None, :], KNOTS[0], KNOTS[-1])
    knots = jnp.asarray(KNOTS)
    risk = jnp.asarray(s.risk) if use_sel else jnp.zeros((P, Y), dtype=bool)
    play = jnp.asarray(s.play) if use_sel else jnp.zeros((P, Y), dtype=bool)
    zero = jnp.zeros(P)

    def seg(v, idx, size):
        return jax.ops.segment_sum(v, idx, num_segments=size)

    def f(z):
        mu0, tau2, q, c, e, cv, bL, bA, b0 = _unpack(z, jnp, Y, fix_q0, fix_curve, use_sel)
        A = jnp.interp(ages, knots, cv)
        dA = jnp.concatenate([jnp.zeros((P, 1)), A[:, 1:] - A[:, :-1]], axis=1)
        R = b2 * c * 100.0 / n + e * oth
        s0, s1, s2, sl = _cells(jnp, kk, yy, P, Y, R, t, seg)
        sa = (b0[None, :] + jnp.interp(ages, knots, bA)) if use_sel else jnp.zeros((P, Y))
        prm = (mu0, tau2, q, bL, use_sel, y0, zero)
        st = (zero, zero, zero, zero, zero, zero)

        def body(st, xs):
            y, s0y, s1y, s2y, sly, dAy, rk, pl_, sa_y = xs
            return _year(jnp, norm.logcdf, norm.logpdf, prm, st, y, s0y, s1y, s2y, sly, dAy, rk, pl_,
                         sa_y), None  # fmt: skip

        xs = (jnp.arange(Y), s0.T, s1.T, s2.T, sl.T, dA.T, risk.T, play.T, sa.T)
        st, _ = jax.lax.scan(body, st, xs)
        return jnp.sum(st[5])

    return f


def fit_group(
    s: Seqs,
    fix_q0: bool = False,
    no_curve: bool = False,
    fix_curve: np.ndarray | None = None,
    start: GroupParams | None = None,
    with_sd: bool = True,
    use_sel: bool = True,
) -> GroupParams:
    """Maximum-likelihood parameters of one group (L-BFGS on the JAX gradient). `no_curve` fixes the
    curve at 0 (no aging); `fix_q0` fixes q at 0 (no random walk); `fix_curve` fixes it at given
    knot levels; `use_sel` adds the selection model. With `with_sd`, the curve's standard errors
    from the inverse Hessian."""
    import jax
    from scipy.optimize import minimize

    jax.config.update("jax_enable_x64", True)
    ref = KNOTS.index(AGE_REF)
    nk = len(KNOTS) - 1
    Y = s.n_years
    fc = np.zeros(len(KNOTS)) if no_curve else fix_curve
    f = nll_fn(s, fix_q0, fc, use_sel)
    vg = jax.jit(jax.value_and_grad(f))
    st = start or GroupParams(mu0=0.0, tau2=100.0, q=3.0, c=900.0, e=5.0)
    z0 = [st.mu0, math.log(st.tau2), math.log(max(st.q, 1e-2)), math.log(st.c),
          math.log(max(st.e, 1e-2))]  # fmt: skip
    bounds = [(-60.0, 60.0), (-5.0, 10.0), (-8.0, 6.0), (2.0, 12.0), (-8.0, 8.0)]
    if fc is None:
        z0 += [x for i, x in enumerate(st.curve) if i != ref]
        bounds += [(-60.0, 60.0)] * nk
    if use_sel:
        sel = st.sel or {}
        z0 += [float(sel.get("bL", 0.02))]
        z0 += [x for i, x in enumerate(sel.get("bA") or [0.0] * len(KNOTS)) if i != ref]
        b0 = sel.get("b0") or {}
        z0 += [float(b0.get(str(s.first_year + y), 1.0)) for y in range(Y)]
        bounds += [(-1.0, 1.0)] + [(-10.0, 10.0)] * nk + [(-10.0, 10.0)] * Y
    z0 = np.array(z0, dtype=float)

    def fun(z):
        val, g = vg(z)
        return float(val), np.asarray(g, dtype=float)

    res = minimize(fun, z0, jac=True, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 5000, "ftol": 1e-13, "gtol": 1e-6})  # fmt: skip
    z = res.x
    mu0, tau2, q, c, e, cv, bL, bA, b0 = _unpack(z, np, Y, fix_q0, fc, use_sel)
    sd = None
    if with_sd and fc is None:
        H = np.asarray(jax.jit(jax.hessian(f))(z), dtype=float) / 2.0  # f is −2 log L
        # parameters the data say nothing about (a year's selection intercept with nobody at risk,
        # one held at a bound) are left out of the inversion
        free = np.array([abs(H[i, i]) > 1e-9 and bounds[i][0] < z[i] < bounds[i][1]
                         for i in range(len(z))])  # fmt: skip
        try:
            cov = np.full(H.shape, np.nan)
            cov[np.ix_(free, free)] = np.linalg.inv(H[np.ix_(free, free)])
            dd = np.sqrt(np.clip(np.diag(cov)[N_FIXED : N_FIXED + nk], 0.0, None))
            sd = tuple(np.concatenate([dd[:ref], [0.0], dd[ref:]]).tolist())
        except np.linalg.LinAlgError:
            sd = None
    sel_out = None
    if use_sel:
        sel_out = {"bL": float(bL), "bA": [float(x) for x in bA],
                   "b0": {str(s.first_year + y): float(b0[y]) for y in range(Y)}}  # fmt: skip
    return GroupParams(
        float(mu0), float(tau2), float(q), float(c), float(e), tuple(float(x) for x in cv), sd,
        len(s.keys), len(s.t), float(res.fun), sel_out,
    )  # fmt: skip


# ---- 4. the shift (apply) ---------------------------------------------------------------------------------


def shifts(
    s: Seqs,
    model: DriftModel,
    weights: dict[tuple[str, str], dict[str, float]],
    target_year: int,
    dob: dict[str, str],
) -> dict[tuple[str, str], tuple[float, float]]:
    """(cid, role) → (shift, its variance) for every key of `s` in `weights`: E[level in `target_year`
    − the weighted average of his levels over his seasons | his seasons], the seasons of league L
    weighted by `weights[key][L]` (his blend's share of that league) × his balls there that year ÷ his
    balls in L. The filter's state carries the running weighted sum."""
    out: dict[tuple[str, str], tuple[float, float]] = {}
    sel = np.array([key in weights for key in s.keys], dtype=bool)
    if not sel.any():
        return out
    for g in sorted(set(s.group[sel])):
        sub = subset(s, sel & (s.group == g))
        out.update(_shifts_group(sub, model.params(g), weights, target_year, dob))
    return out


def _b0_at(sel: dict, year: int) -> float:
    """The selection model's intercept for a calendar year (a year after its fit: the last one)."""
    b0 = {int(k): v for k, v in sel["b0"].items()}
    ys = [y for y in b0 if y <= year]
    return float(b0[max(ys)] if ys else b0[min(b0)])


def _shifts_group(s: Seqs, p: GroupParams, weights, target_year: int, dob) -> dict:
    from scipy.special import log_ndtr

    P, Y = len(s.keys), s.n_years
    # per value: its weight in his career average (his blend's share of the league × its balls share)
    nl: dict[tuple[int, str], float] = {}
    for i, lg, n in zip(s.k, s.league, s.n, strict=True):
        nl[(int(i), lg)] = nl.get((int(i), lg), 0.0) + n
    wobs = np.array([weights.get(s.keys[i], {}).get(lg, 0.0) * n / nl[(int(i), lg)]
                     for i, lg, n in zip(s.k, s.league, s.n, strict=True)])  # fmt: skip
    wy = np.zeros((P, Y))
    np.add.at(wy, (s.k, s.y), wobs)
    nb = np.zeros((P, Y))
    np.add.at(nb, (s.k, s.y), s.n)
    no_w = wy.sum(axis=1) <= 0  # none of his blend's leagues has a value: all his seasons by balls
    wy[no_w] = nb[no_w]
    wy = wy / np.maximum(wy.sum(axis=1), 1e-300)[:, None]
    ages = s.age0[:, None] + np.arange(Y)[None, :]
    A = curve_at(p.curve, ages)
    dA = np.concatenate([np.zeros((P, 1)), A[:, 1:] - A[:, :-1]], axis=1)
    R = s.b2 * p.c * 100.0 / s.n + p.e * s.other

    def seg(v, idx, size):
        return np.bincount(idx, weights=v, minlength=size)

    s0, s1, s2, sl = _cells(np, s.k, s.y, P, Y, R, s.t, seg)
    use_sel = p.sel is not None and s.risk is not None
    if use_sel:
        b0 = np.array([_b0_at(p.sel, s.first_year + y) for y in range(Y)])
        sa = b0[None, :] + curve_at(p.sel["bA"], ages)
        bL = p.sel["bL"]
    else:
        sa, bL = np.zeros((P, Y)), 0.0
    risk = s.risk if use_sel else np.zeros((P, Y), dtype=bool)
    play = s.play if use_sel else np.zeros((P, Y), dtype=bool)

    def logpdf(x):
        return -0.5 * x * x - 0.5 * math.log(2 * math.pi)

    st = tuple(np.zeros(P) for _ in range(6))
    for y in range(Y):
        prm = (p.mu0, p.tau2, p.q, bL, use_sel, s.y0, wy[:, y])
        st = _year(np, log_ndtr, logpdf, prm, st, y, s0[:, y], s1[:, y], s2[:, y], sl[:, y],
                   dA[:, y], risk[:, y], play[:, y], sa[:, y])  # fmt: skip
    mL, vLL, mS, vLS, vSS, _ = st
    steps = max(target_year - s.last_year, 0)
    a_last = ages[:, -1].copy()
    a_t = a_last + steps
    for i, (cid, _r) in enumerate(s.keys):
        a = age_on(dob.get(cid), target_year)
        if a is not None:
            a_t[i] = a
    mT = mL + curve_at(p.curve, a_t) - curve_at(p.curve, a_last)
    vT = vLL + steps * p.q
    sh = mT - mS
    var = np.maximum(vT + vSS - 2 * vLS, 0.0)
    return {k: (float(sh[i]), float(var[i])) for i, k in enumerate(s.keys)}


def adjust(
    values: dict[str, dict[str, tuple[float, float]]],
    shares: dict[tuple[str, str], dict[str, float]],
    obs: pl.DataFrame,
    date: str,
    target_year: int,
    dob: dict[str, str],
    category: dict[str, str | None],
    model: DriftModel | None,
    which: str = "roles",
    tmodel=None,
) -> tuple[dict[str, dict[str, tuple[float, float]]], dict[tuple[str, str], tuple[float, float]]]:
    """Time-aware values: `values` (cid → {role: (career value, sd)} on the IPL scale) shifted to the
    coming season (`target_year`) from the season values known before `date`, with `shares` ((cid,
    role) → {league: blend weight}). Returns (cid → {role: (value now, sd)}, (cid, role) → (shift,
    shift sd)). Without a model (no config file) the values come back as they are."""
    if model is None:
        return values, {}
    keys = {(cid, r) for cid, rs in values.items() for r in rs}
    s = sequences(
        obs_asof(obs, date), dob, category, tmodel, which, model.debut_age, keys, int(date[:4])
    )
    sh = shifts(s, model, {k: shares.get(k, {}) for k in keys}, target_year, dob)
    out: dict[str, dict[str, tuple[float, float]]] = {}
    info: dict[tuple[str, str], tuple[float, float]] = {}
    for cid, rs in values.items():
        for role, (v, sd) in rs.items():
            d = sh.get((cid, role))
            if d is None:
                out.setdefault(cid, {})[role] = (v, sd)
                continue
            out.setdefault(cid, {})[role] = (v + d[0], math.sqrt(sd * sd + d[1]))
            info[(cid, role)] = (d[0], math.sqrt(d[1]))
    return out, info
