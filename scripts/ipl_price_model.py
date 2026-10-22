"""Fit the IPL market-price model to real auction prices (docs/METHODOLOGY.md §6).

Two steps:

1. `fits` — the player ratings AS OF each auction: the IPL fitted on matches before that auction's
   date (2009-2026; one ADVI fit each, ~1-3 min, cached under
   `data/metrics/.backtest_cache/<model version>/v2/ipl_auction<season>_s42_12000.parquet`, so a
   rerun only fits what's missing — safe to stop and resume). The other leagues come from the
   newcomer backtest's cache (fitted on matches before 1 January of a season); an auction only
   uses a league fit whose cut-off is on or before its own date, so nothing after the auction
   leaks in (for a December auction that league data is up to a year old).
2. `fit` — the hurdle model on `data/curated/ipl_auction_history.json` (scripts/ipl_auction_history.py):
   P(bought) by logistic regression and log(price / purse | bought) by a regularised hedonic
   regression, both on features known at auction time (no leakage). Evaluated out of time
   (train ≤ 2024, test the 2025 mega + 2026 mini auctions) against the old hand-set curve, then
   refitted on every auction and written to `config/price_model.json` (read by
   web_parity/pricing.py ⇄ site/src/lib/auction.ts through the site export).

Run:
    uv run python scripts/ipl_price_model.py fits            # long: ~45 min the first time
    uv run python scripts/ipl_price_model.py fit             # seconds
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import time
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import typer
from loguru import logger

from cricdex import leagues
from cricdex.config import DATA_DIR
from cricdex.scout.identity import captains, master, sources
from cricdex.scout.identity.countries import normalise
from cricdex.scout.ratings import bayesian
from cricdex.web_parity import pricing

app = typer.Typer(add_completion=False)

CACHE = DATA_DIR / "metrics" / ".backtest_cache"
HISTORY = DATA_DIR / "curated" / "ipl_auction_history.json"
MODEL_PATH = Path(__file__).resolve().parents[1] / "config" / "price_model.json"
STEPS = 12000
SEED = 42
VARIANT = "v2"
KEEP = [
    "cricsheet_id", "role", "balls", "skill", "skill_sd", "value", "value_sd",
]  # fmt: skip


def auction_dates() -> dict[int, str]:
    from ipl_auction_history import AUCTIONS

    return {y: a["date"] for y, a in AUCTIONS.items()}


def ipl_fit_path(season: int) -> Path:
    return CACHE / bayesian.MODEL_VERSION / VARIANT / f"ipl_auction{season}_s{SEED}_{STEPS}.parquet"


def league_fit_path(col: str, season: int) -> Path:
    """The newcomer backtest's cache: `col` fitted on matches before `season`-01-01."""
    return CACHE / bayesian.MODEL_VERSION / VARIANT / f"{col}_{season}_s{SEED}_{STEPS}.parquet"


@app.command()
def fits(
    first: int = typer.Option(2009, "--first"),
    last: int = typer.Option(2026, "--last"),
    log_file: Path | None = typer.Option(None, "--log", help="Also append progress here."),
) -> None:
    """Fit the IPL before every auction date (cached; resumable)."""

    def say(msg: str) -> None:
        logger.info(msg)
        if log_file:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")

    dates = auction_dates()
    for season in range(first, last + 1):
        path = ipl_fit_path(season)
        if path.exists():
            say(f"{season}: cached")
            continue
        t = time.time()
        r = bayesian.fit(
            collection="ipl", before=dates[season], advi_steps=STEPS, seed=SEED, variant=VARIANT
        )
        for c in KEEP:
            if c not in r.columns:
                r = r.with_columns(pl.lit(None, pl.Float64).alias(c))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        r.select(KEEP).write_parquet(tmp)
        tmp.replace(path)
        say(f"{season}: fitted before {dates[season]} in {time.time() - t:.0f}s ({r.height} rows)")
    say("done")


# ---- auction-time features -------------------------------------------------------------------------

INTL_CACHE = CACHE / "intl_appearances.parquet"
OTHER_LEAGUES = [lg.key for lg in leagues.auction_pool() if not lg.auction_target]
# A role record this big in the IPL stands on its own (export_site.AUCTION_TRUST_BALLS).
TRUST_BALLS = 300
# The P(bought) risk set: an IPL player whose last IPL match is this recent, not retained and not
# bought, counts as "not bought" (unsold, unregistered or retired: the pages list no unsold lots).
RISK_DAYS = 730
# Seasons whose Wikipedia page lists every retained player (so "not retained" is known).
FULL_RETENTION_SEASONS = (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)
ROLE_MAP = {
    "wk_batter": "keeper",
    "allrounder": "all_rounder",
    "bowler": "bowler",
    "batter": "batter",
}
PV_SHIFT = 0.5  # pricing.PRICE_CAUTION_SD (the cautious estimate)
TEST_SEASONS = (2025, 2026)
ALPHAS = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0)


def intl_appearances(refresh: bool = False) -> dict[str, list[str]]:
    """cricsheet_id → sorted dates of his men's international XIs (sources.international_dates,
    cached here as a parquet because the ODI / Test archives take a while to read)."""
    if INTL_CACHE.exists() and not refresh:
        out: dict[str, list[str]] = {}
        for cid, d in pl.read_parquet(INTL_CACHE).sort("date").iter_rows():
            out.setdefault(cid, []).append(d)
        return out
    with duckdb.connect(str(bayesian.DEFAULT_DB_PATH), read_only=True) as con:
        got = sources.international_dates(con)
    rows = [(cid, d) for cid, ds in got.items() for d in ds]
    INTL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows, schema=["cid", "date"], orient="row").write_parquet(INTL_CACHE)
    return got


def ipl_appearances() -> dict[str, list[str]]:
    """cricsheet_id → sorted IPL match dates."""
    with duckdb.connect(str(bayesian.DEFAULT_DB_PATH), read_only=True) as con:
        rows = con.execute(
            "SELECT DISTINCT p.identifier, m.match_date FROM match_players_ipl p "
            "JOIN matches_ipl m USING (match_id) WHERE p.identifier IS NOT NULL"
        ).fetchall()
    out: dict[str, list[str]] = {}
    for cid, d in sorted(rows, key=lambda r: str(r[1])):
        out.setdefault(cid, []).append(str(d)[:10])
    return out


def asof_values(season: int, date: str) -> dict[str, dict]:
    """Each player's value as of an auction, blended across leagues exactly as the auction pool
    blends them (export_site._export_auction_pool): per role, each league's value minus its
    discount, weighted by 1 / (sd² + translation sd²); 300+ IPL balls in the role and the IPL
    rating stands alone; best role wins. Only fits whose cut-off is on or before `date`."""
    acc: dict[tuple[str, str], list[float]] = {}
    own: dict[tuple[str, str], tuple[float, int, float]] = {}
    ipl_balls: dict[str, int] = {}
    p = ipl_fit_path(season)
    if p.exists():
        for r in pl.read_parquet(p).iter_rows(named=True):
            if r["value"] is None:
                continue
            sd = float(r["value_sd"] or 1.0)
            a = acc.setdefault((r["cricsheet_id"], r["role"]), [0.0, 0.0])
            a[0] += 1.0 / (sd * sd)
            a[1] += float(r["value"]) / (sd * sd)
            own[(r["cricsheet_id"], r["role"])] = (float(r["value"]), int(r["balls"] or 0), sd)
            ipl_balls[r["cricsheet_id"]] = ipl_balls.get(r["cricsheet_id"], 0) + int(
                r["balls"] or 0
            )
    for col in OTHER_LEAGUES:
        cands = [
            s
            for s in range(2010, season + 1)
            if f"{s}-01-01" <= date and league_fit_path(col, s).exists()
        ]
        if not cands:
            continue
        pen, tsd = leagues.discount(col), leagues.translation_sd(col)
        for r in pl.read_parquet(league_fit_path(col, max(cands))).iter_rows(named=True):
            if r["value"] is None or r["cricsheet_id"] is None:
                continue
            sd = float(r["value_sd"] or 1.0)
            w = 1.0 / (sd * sd + tsd * tsd)
            a = acc.setdefault((r["cricsheet_id"], r["role"]), [0.0, 0.0])
            a[0] += w
            a[1] += w * (float(r["value"]) - pen)
    best: dict[str, dict] = {}
    for (cid, role), (sw, swx) in acc.items():
        o = own.get((cid, role))
        if o and o[1] >= TRUST_BALLS:
            val, vsd = o[0], o[2]
        else:
            val, vsd = swx / sw, (1.0 / sw) ** 0.5
        if cid not in best or val > best[cid]["value"]:
            best[cid] = {"value": val, "value_sd": vsd, "target_balls": o[1] if o else 0}
    for cid, b in best.items():
        b["ipl_balls"] = ipl_balls.get(cid, 0)
    return best


def _captaincy(cid: str, season: int) -> dict:
    """Captaincy known before the auction for `season` (scout/identity/captains.py)."""
    c = captains.as_of(cid, season)
    return {k: c[k] for k in ("captain_ipl_last", "captain_ipl_seasons", "captain_intl_2y")}


def _recent(dates: list[str], date: str, days: int = 730) -> int:
    """International matches in the `days` before `date`."""
    lo = (dt.date.fromisoformat(date) - dt.timedelta(days=days)).isoformat()
    return bisect.bisect_left(dates, date) - bisect.bisect_left(dates, lo)


def _years(a: str, b: str) -> float:
    return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days / 365.25


def _relevance(last_ipl: str | None, age: float | None, country: str | None, date: str) -> float:
    """export_site's IPL-relevance weight (the old curve's input), as of `date`, for a player
    entering an auction (so he has no current franchise)."""
    af = None
    if age is not None:
        af = 1.0 if age <= 32 else 0.35 if age >= 42 else 1.0 - (age - 32) * 0.065
    if last_ipl:
        yrs = _years(date, last_ipl)
        if yrs <= 1.5:
            return 1.0 if (age is None or age < 40) else 0.8
        return max(0.3, max(0.4, 1.0 - (yrs - 1.5) * 0.18) * (af if af is not None else 1.0))
    if country == "IND":
        return 0.7
    if af is not None:
        return max(0.2, 0.7 * af)
    return 0.5


def build_rows(refresh_caps: bool = False) -> tuple[list[dict], list[dict], dict, list[dict]]:
    """(price rows: every bought lot with a Cricsheet id; risk rows: the P(bought) risk set;
    history) — each row holds `market_features` inputs as of its auction plus the label."""
    hist = json.loads(HISTORY.read_text(encoding="utf-8"))
    pm = master.load()
    caps = intl_appearances(refresh_caps)
    apps = ipl_appearances()
    # the latest known salary of a player before each season (auction price or retained salary)
    paid: dict[str, list[tuple[int, float, float]]] = {}
    for r in hist["lots"]:
        if r.get("sold") and r.get("cricsheet_id") and r.get("price_cr"):
            purse = hist["auctions"][str(r["season"])]["purse_cr"]
            paid.setdefault(r["cricsheet_id"], []).append((r["season"], r["price_cr"], purse))
    for r in hist["retentions"]:
        if r.get("cricsheet_id") and r.get("salary_cr"):
            purse = hist["auctions"][str(r["season"])]["purse_cr"]
            paid.setdefault(r["cricsheet_id"], []).append((r["season"], r["salary_cr"], purse))

    def features_in(cid: str, season: int, date: str, vals: dict, country: str | None) -> dict:
        rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
        v = vals.get(cid)
        country = country or normalise(rec.get("country"))
        dob = rec.get("dob")
        age = None
        if dob:
            try:
                age = _years(date, str(dob)[:10])
            except ValueError:
                age = None
        ipl = [d for d in apps.get(cid, []) if d < date]
        last = ipl[-1] if ipl else None
        prev = [x for x in paid.get(cid, []) if x[0] < season]
        prev_share = None
        if prev:
            s, amt, purse = max(prev, key=lambda x: x[0])
            prev_share = amt / purse
        return {
            "cricsheet_id": cid,
            "season": season,
            "price_value": v["value"] if v else None,
            "value_sd": v["value_sd"] if v else None,
            "target_balls": v["target_balls"] if v else 0,
            "ipl_balls": v["ipl_balls"] if v else 0,
            "role": ROLE_MAP.get(rec.get("primary_role") or "", "batter"),
            "country": country,
            "is_overseas": bool(country) and country != "IND",
            "intl_caps": bisect.bisect_left(caps.get(cid, []), date),
            "intl_caps_2y": _recent(caps.get(cid, []), date),
            **_captaincy(cid, season),
            "age": age,
            "ipl_seasons": len({d[:4] for d in ipl}),
            "ipl_gap": _years(date, last) if last else None,
            "last_ipl": last,
            "prev_share": prev_share,
        }

    price_rows: list[dict] = []
    risk_rows: list[dict] = []
    ret_rows: list[dict] = []
    for ys, a in hist["auctions"].items():
        season = int(ys)
        date = a["date"]
        vals = asof_values(season, date)
        cycle = a["kind"]
        purse = a["purse_cr"]
        bought: set[str] = set()
        for r in hist["lots"]:
            if r["season"] != season or not r.get("sold") or not r.get("cricsheet_id"):
                continue
            if not r.get("price_cr"):
                continue
            bought.add(r["cricsheet_id"])
            f = features_in(r["cricsheet_id"], season, date, vals, r.get("country"))
            base = r.get("base_price_cr")
            price_rows.append(
                {
                    **f,
                    "name": r["name"],
                    "cycle": cycle,
                    "purse": purse,
                    "price_cr": r["price_cr"],
                    "y": math.log(r["price_cr"] / purse),
                    "base_share": (base / purse) if base else None,
                    "team": r.get("team"),
                }
            )
        # mega-year retentions: what the franchise pays out of the purse to keep him (the purse
        # deduction where it differs from his salary) — slab-set, so a floor on his worth to it
        if cycle == "mega":
            for r in hist["retentions"]:
                if r["season"] != season or r["kind"] != "retained" or not r.get("cricsheet_id"):
                    continue
                cost = r.get("purse_deduction_cr") or r.get("salary_cr")
                if not cost:
                    continue
                f = features_in(r["cricsheet_id"], season, date, vals, r.get("country"))
                ret_rows.append(
                    {
                        **f,
                        "name": r["name"],
                        "cycle": cycle,
                        "purse": purse,
                        "price_cr": cost,
                        "y": math.log(cost / purse),
                        "base_share": None,
                        "team": r.get("team"),
                        "retained": 1.0,
                    }
                )
        if season not in FULL_RETENTION_SEASONS:
            continue
        kept = {
            r["cricsheet_id"]
            for r in hist["retentions"]
            if r["season"] == season and r.get("cricsheet_id")
        }
        lo = (dt.date.fromisoformat(date) - dt.timedelta(days=RISK_DAYS)).isoformat()
        recent = {
            cid
            for cid, ds in apps.items()
            if bisect.bisect_left(ds, date) > bisect.bisect_left(ds, lo)
        }
        for cid in sorted((recent - kept) | bought):
            f = features_in(cid, season, date, vals, None)
            if f["ipl_gap"] is None:
                continue  # newcomers: no unsold record exists for them
            risk_rows.append({**f, "cycle": cycle, "purse": purse, "bought": cid in bought})
    return price_rows, risk_rows, hist, ret_rows


# ---- models -----------------------------------------------------------------------------------------


def _matrix(rows: list[dict], names: list[str], extra: tuple[str, ...] = ()) -> np.ndarray:
    X = []
    for r in rows:
        f = pricing.market_features(r, r["cycle"])
        x = [f[k] for k in names]
        for e in extra:
            v = r.get(e)
            if e in ("prev_share", "base_share"):
                x += [math.log(v) if v else 0.0, 0.0 if v else 1.0]
            else:
                x.append(float(v or 0.0))
        X.append(x)
    return np.asarray(X, dtype=float)


def _fit_reg(kind: str, X: np.ndarray, y: np.ndarray, alpha: float):
    from sklearn.linear_model import HuberRegressor, QuantileRegressor, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if kind == "ridge":
        est = Ridge(alpha=alpha)
    elif kind == "huber":
        est = HuberRegressor(alpha=alpha / 100.0, epsilon=1.35, max_iter=2000)
    else:
        est = QuantileRegressor(quantile=0.5, alpha=alpha / 1000.0, solver="highs")
    return make_pipeline(StandardScaler(), est).fit(X, y)


def _price_metrics(pred_ln_cr: np.ndarray, y_ln_cr: np.ndarray) -> dict:
    err = pred_ln_cr - y_ln_cr
    ape = np.abs(np.exp(err) - 1.0)
    from scipy.stats import spearmanr

    return {
        "n": int(len(err)),
        "mae_ln": round(float(np.mean(np.abs(err))), 3),
        "median_abs_pct": round(100 * float(np.median(ape)), 1),
        "within_50pct": round(100 * float(np.mean(ape <= 0.5)), 1),
        "bias_ln": round(float(np.mean(err)), 3),
        "spearman": round(float(spearmanr(pred_ln_cr, y_ln_cr).statistic), 3),
        # the lots that sold for 10 cr+: geometric-mean predicted / actual (1 = right on average)
        "top10_ratio": (
            round(float(np.exp(np.mean(err[y_ln_cr >= math.log(10)]))), 3)
            if np.any(y_ln_cr >= math.log(10))
            else None
        ),
    }


# ---- top-end calibration -------------------------------------------------------------------------

CAL_MODES = (
    "none", "isotonic", "isotonic+smear", "quantile", "quantile+smear", "quantile-top",
    "quantile-top+smear", "quantile+group-offset", "group-quantile", "quantile+group-offset-recent",
    "group-quantile+group-offset-recent",
)  # fmt: skip
# "-recent": the group offsets from the last RECENT_SEASONS auctions only (the market moves: the
# 2025-27 rules capped an overseas mini-auction buy's fee at 18 cr)
RECENT_SEASONS = 2
# The calibration groups (shipped in config/price_model.json; pricing.calibration_part): ranges on
# market_features. caps = ln(1 + international caps), so caps > 0 = capped.
CAL_GROUPS = [
    {"name": "overseas", "when": {"overseas": [1, 1]}},
    {"name": "capped_indian", "when": {"overseas": [0, 0], "caps": [1e-9, 1e9]}},
    {"name": "uncapped_indian", "when": {"overseas": [0, 0], "caps": [0, 0]}},
]
GROUP_KNOTS = 11
CAL_KNOTS = 21


def _oof(kind: str, rows: list[dict], alpha: float, extra=(), names=None) -> np.ndarray:
    """Out-of-fold linear predictions (ln price / purse) for the auction lots in `rows`: each season
    predicted by a fit on every other season (retention rows train but are never predicted)."""
    names = names or PRICE_FEATURES
    out = np.full(len(rows), np.nan)
    for s in sorted({r["season"] for r in rows}):
        tr = [r for r in rows if r["season"] != s]
        idx = [i for i, r in enumerate(rows) if r["season"] == s and not r.get("retained")]
        if not idx:
            continue
        m = _fit_reg(kind, _matrix(tr, names, extra), np.array([r["y"] for r in tr]), alpha)
        out[idx] = m.predict(_matrix([rows[i] for i in idx], names, extra))
    return out


def _group_of(r: dict) -> str | None:
    f = pricing.market_features(r, r["cycle"])
    for g in CAL_GROUPS:
        if all(lo <= f[k] <= hi for k, (lo, hi) in g["when"].items()):
            return g["name"]
    return None


def _quantile_map(lin: np.ndarray, y: np.ndarray, knots: int) -> dict:
    q = np.linspace(0.0, 1.0, knots)
    xs, ix = np.unique(np.quantile(lin, q), return_index=True)
    ys = np.quantile(y, q)[ix]
    return {"x": [round(float(x), 6) for x in xs], "y": [round(float(v), 6) for v in ys]}


def _fit_calibration(mode: str, lin: np.ndarray, y: np.ndarray, rows: list[dict]) -> dict:
    """{"calibration": {x, y} or None, "shift": float} from out-of-fold predictions `lin` and the
    actual ln shares `y`. isotonic: E[y | prediction], monotone (it undoes the regression to the
    mean a shrunken fit leaves at the top); quantile: the predictions' quantiles mapped onto the
    actual prices' (the same spread as real auctions); +smear: plus Duan's retransformation,
    ln mean(e^residual), so the price is a mean rather than a median."""
    from sklearn.isotonic import IsotonicRegression

    part: dict = {"calibration": None, "shift": 0.0}
    q = np.linspace(0.0, 1.0, CAL_KNOTS)
    if mode.startswith("isotonic"):
        iso = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(lin, y)
        xs = np.unique(np.quantile(lin, q))
        part["calibration"] = {
            "x": [round(float(x), 6) for x in xs],
            "y": [round(float(v), 6) for v in iso.predict(xs)],
        }
    elif mode.startswith("quantile-top"):
        # the upper half only: above the median prediction, the predictions' quantiles are mapped
        # onto the actual prices' spread above their median; below it the prediction is unchanged
        # (the knot at the median continues at slope 1), so the median lot doesn't move
        qq = q[q >= 0.5]
        xs, ix = np.unique(np.quantile(lin, qq), return_index=True)
        x_med = float(np.quantile(lin, 0.5))
        ys = x_med + (np.quantile(y, qq) - np.quantile(y, 0.5))[ix]
        ys = np.maximum.accumulate(ys)  # monotone
        part["calibration"] = {
            "x": [round(float(x), 6) for x in xs],
            "y": [round(float(v), 6) for v in ys],
        }
    elif mode.startswith("quantile"):
        part["calibration"] = _quantile_map(lin, y, CAL_KNOTS)
    elif mode.startswith("group-quantile"):
        # one quantile map per group (its own lots), the global map for anyone in no group
        part["calibration"] = _quantile_map(lin, y, CAL_KNOTS)
        groups = [_group_of(r) for r in rows]
        part["groups"] = []
        for g in CAL_GROUPS:
            m = np.array([x == g["name"] for x in groups])
            if m.sum() >= 30:
                part["groups"].append(
                    {**g, "calibration": _quantile_map(lin[m], y[m], GROUP_KNOTS), "shift": 0.0}
                )
    if mode.startswith("group-quantile") and mode.endswith("-recent"):
        # each group's own map, then its mean residual over the recent auctions as its shift
        res = y - _apply_cal(part, lin, rows)
        last = max(r["season"] for r in rows)
        groups = [_group_of(r) for r in rows]
        for g in part["groups"]:
            m = np.array([x == g["name"] and r["season"] > last - RECENT_SEASONS
                          for x, r in zip(groups, rows, strict=True)])  # fmt: skip
            if m.sum():
                g["shift"] = round(float(np.mean(res[m])), 6)
    elif mode.endswith("+group-offset") or mode.endswith("+group-offset-recent"):
        # the global map, then each group's mean out-of-fold residual as its own shift
        res = y - _apply_cal(part, lin, rows)
        groups = [_group_of(r) for r in rows]
        last = max(r["season"] for r in rows)
        recent = mode.endswith("-recent")
        part["groups"] = []
        for g in CAL_GROUPS:
            m = np.array([x == g["name"] and (not recent or r["season"] > last - RECENT_SEASONS)
                          for x, r in zip(groups, rows, strict=True)])  # fmt: skip
            if m.sum():
                part["groups"].append(
                    {**g, "calibration": part["calibration"],
                     "shift": round(float(np.mean(res[m])), 6)}
                )  # fmt: skip
    if mode.endswith("+smear"):
        resid = y - _apply_cal(part, lin, rows)
        part["shift"] = round(float(np.log(np.mean(np.exp(resid)))), 6)
    return part


def _clamp(pred_ln_cr: np.ndarray, rows: list[dict]) -> np.ndarray:
    """The shipped price's clamps on a predicted ln crore: the 0.3 cr floor and the IPL-evidence
    ceiling (pricing.price_ceiling), so the test scores what the site would show."""
    lo = math.log(0.3)
    hi = np.log([pricing.price_ceiling(r.get("target_balls")) for r in rows])
    return np.minimum(np.maximum(pred_ln_cr, lo), hi)


def _apply_cal(part: dict, lin: np.ndarray, rows: list[dict]) -> np.ndarray:
    """The calibration on each row's linear prediction, by its group (pricing.calibration_part)."""
    out = []
    for v, r in zip(lin, rows, strict=True):
        cal = pricing.calibration_part(part, pricing.market_features(r, r["cycle"]))
        out.append(pricing.calibrate(cal, float(v)))
    return np.array(out)


def _old_curve(r: dict) -> float:
    """The hand-set on-field curve as the site priced a player entering this auction: his value
    less the IPL-relevance discount, cautious estimate, IPL-evidence ceiling."""
    from export_site import PEN_SCALE_VALUE

    if r["price_value"] is None:
        return 0.3
    rel = _relevance(r["last_ipl"], r["age"], r["country"], AUCTIONS_DATES[r["season"]])
    v = r["price_value"] - (1 - rel) * PEN_SCALE_VALUE
    return pricing.est_value(v, r["role"], "ipl", r["value_sd"], r["target_balls"])


def _choose_alpha(kind: str, rows: list[dict], names: list[str], extra=()) -> float:
    """Leave-one-auction-out over the training seasons; lowest mean absolute log error."""
    seasons = sorted({r["season"] for r in rows})
    best = (math.inf, ALPHAS[0])
    for alpha in ALPHAS:
        errs = []
        for s in seasons:
            tr = [r for r in rows if r["season"] != s]
            te = [r for r in rows if r["season"] == s]
            if len(te) < 5:
                continue
            m = _fit_reg(kind, _matrix(tr, names, extra), np.array([r["y"] for r in tr]), alpha)
            errs += list(
                np.abs(m.predict(_matrix(te, names, extra)) - np.array([r["y"] for r in te]))
            )
        e = float(np.mean(errs))
        if e < best[0]:
            best = (e, alpha)
    return best[1]


def _raw_coef(model, names: list[str]) -> tuple[float, dict[str, float]]:
    """Fold the scaler into the coefficients: intercept + Σ coef × raw feature."""
    sc, est = model[0], model[-1]
    beta = np.asarray(est.coef_, dtype=float).ravel()
    scale = np.where(sc.scale_ == 0, 1.0, sc.scale_)
    raw = beta / scale
    icpt = float(np.asarray(est.intercept_).ravel()[0]) - float(np.sum(raw * sc.mean_))
    return round(icpt, 6), {k: round(float(c), 6) for k, c in zip(names, raw, strict=True)}


def _fit_logit(X: np.ndarray, y: np.ndarray, c: float):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=5000)).fit(X, y)


def _logit_metrics(p: np.ndarray, y: np.ndarray) -> dict:
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    p = np.clip(p, 1e-6, 1 - 1e-6)
    bins = []
    for lo, hi in ((0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 0.9), (0.9, 1.01)):
        m = (p >= lo) & (p < hi)
        if m.sum():
            bins.append(
                {"band": f"{lo:.2f}-{min(hi, 1):.2f}", "n": int(m.sum()),
                 "predicted": round(float(p[m].mean()), 3), "observed": round(float(y[m].mean()), 3)}
            )  # fmt: skip
    return {
        "n": int(len(y)),
        "bought_share": round(float(y.mean()), 3),
        "log_loss": round(float(log_loss(y, p, labels=[0, 1])), 3),
        "log_loss_base_rate": round(
            float(log_loss(y, np.full_like(p, y.mean()), labels=[0, 1])), 3
        ),
        "brier": round(float(brier_score_loss(y, p)), 3),
        "auc": round(float(roc_auc_score(y, p)), 3),
        "calibration": bins,
    }


PRICE_FEATURES = [
    "pv", "pv_pos_sq", "unrated", "overseas", "pv_x_overseas", "caps", "caps_x_indian",
    "pv_x_capped_indian", "recent_caps", "recent_caps_x_indian", "age", "age_sq", "age_missing",
    "ipl_balls", "ipl_seasons", "never_ipl",
    "ipl_gap", "all_rounder", "keeper", "bowler", "mega", "captain_ipl", "captain_seasons",
    "captain_intl",
]  # fmt: skip
CAPTAIN_FEATURES = ("captain_ipl", "captain_seasons", "captain_intl")
BOUGHT_FEATURES = [
    "pv", "unrated", "overseas", "pv_x_overseas", "caps", "caps_x_indian", "recent_caps",
    "recent_caps_x_indian", "age", "age_sq",
    "age_missing", "ipl_balls", "ipl_seasons", "ipl_gap", "all_rounder", "keeper", "bowler", "mega",
    "captain_ipl", "captain_seasons", "captain_intl",
]  # fmt: skip
AUCTIONS_DATES: dict[int, str] = {}


@app.command()
def fit(
    first: int = typer.Option(
        2018, "--first", help="First auction season to train on (2018: the shipped fit)."
    ),
    kind: str = typer.Option("huber", "--kind", help="ridge | huber | quantile (the shipped fit)"),
    out: Path = typer.Option(MODEL_PATH, "--out"),
    refresh_caps: bool = typer.Option(False, "--refresh-caps"),
    report: Path | None = typer.Option(None, "--report", help="Write the full evaluation here."),
    calibration: str = typer.Option(
        "quantile+group-offset",
        "--calibration",
        help="top-end calibration: " + " | ".join(CAL_MODES),
    ),
    retentions: str = typer.Option(
        "plain",
        "--retentions",
        help="mega-year retention prices in the price fit: none | flag (with a `retained` "
        "indicator, 0 when pricing) | plain (as if bought)",
    ),
) -> None:
    """Build the auction-time features, evaluate out of time, refit on everything and export."""
    AUCTIONS_DATES.update(auction_dates())
    missing = [s for s in range(max(first, 2009), 2027) if not ipl_fit_path(s).exists()]
    if missing:
        raise typer.BadParameter(f"IPL fits missing for {missing}: run `fits` first")
    price_rows, risk_rows, hist, ret_rows = build_rows(refresh_caps)
    lots = [r for r in price_rows if r["season"] >= first]
    rets_in = [r for r in ret_rows if r["season"] >= first] if retentions != "none" else []
    price_rows = lots + rets_in
    flag = ("retained",) if retentions == "flag" else ()
    train = [r for r in price_rows if r["season"] not in TEST_SEASONS]
    test = [r for r in lots if r["season"] in TEST_SEASONS]
    y_te_cr = np.array([math.log(r["price_cr"]) for r in test])
    ev: dict = {"price": {}, "bought": {}}

    # ---- price | bought, out of time: train ≤ 2024, test the 2025 mega + 2026 mini auctions
    for k in ("ridge", "huber", "quantile"):
        for extra, label in (
            ((), "market"),
            (("prev_share",), "+prev salary"),
            (("base_share",), "+base price"),
        ):
            alpha = _choose_alpha(k, train, PRICE_FEATURES, flag + extra)
            m = _fit_reg(
                k,
                _matrix(train, PRICE_FEATURES, flag + extra),
                np.array([r["y"] for r in train]),
                alpha,
            )
            pred = _clamp(
                m.predict(_matrix(test, PRICE_FEATURES, flag + extra))
                + np.log([r["purse"] for r in test]),
                test,
            )
            ev["price"][f"{k} {label}"] = {"alpha": alpha, **_price_metrics(pred, y_te_cr)}
            for s in TEST_SEASONS:
                idx = [i for i, r in enumerate(test) if r["season"] == s]
                ev["price"][f"{k} {label}"][str(s)] = _price_metrics(pred[idx], y_te_cr[idx])
    old = np.log([_old_curve(r) for r in test])
    ev["price"]["old curve (on-field)"] = _price_metrics(old, y_te_cr)
    for s in TEST_SEASONS:
        idx = [i for i, r in enumerate(test) if r["season"] == s]
        ev["price"]["old curve (on-field)"][str(s)] = _price_metrics(old[idx], y_te_cr[idx])
    # a segment view of the shipped kind
    alpha = _choose_alpha(kind, train, PRICE_FEATURES, flag)
    m = _fit_reg(
        kind, _matrix(train, PRICE_FEATURES, flag), np.array([r["y"] for r in train]), alpha
    )
    lin_te = m.predict(_matrix(test, PRICE_FEATURES, flag))
    ln_purse = np.log([r["purse"] for r in test])
    # top-end calibration, fitted on out-of-fold predictions of the training seasons only
    y_tr = np.array([r["y"] for r in train])
    oof = _oof(kind, train, alpha, flag)
    ok = ~np.isnan(oof)
    tr_ok = [r for r, k in zip(train, ok, strict=True) if k]
    test_groups = [_group_of(r) for r in test]
    ev["calibration"] = {}
    ev["calibration_groups"] = {}
    for mode in CAL_MODES:
        part = _fit_calibration(mode, oof[ok], y_tr[ok], tr_ok)
        pc = _clamp(_apply_cal(part, lin_te, test) + ln_purse, test)
        ev["calibration"][mode] = _price_metrics(pc, y_te_cr)
        for s_ in TEST_SEASONS:
            idx = [i for i, r in enumerate(test) if r["season"] == s_]
            ev["calibration"][mode][str(s_)] = _price_metrics(pc[idx], y_te_cr[idx])
        ev["calibration_groups"][mode] = {}
        for g in CAL_GROUPS:
            idx = [i for i, x in enumerate(test_groups) if x == g["name"]]
            if idx:
                ev["calibration_groups"][mode][g["name"]] = _price_metrics(pc[idx], y_te_cr[idx])
    # the same without the captaincy features
    nocap = [f for f in PRICE_FEATURES if f not in CAPTAIN_FEATURES]
    m_nc = _fit_reg(kind, _matrix(train, nocap, flag), y_tr, alpha)
    oof_nc = _oof(kind, train, alpha, flag, names=nocap)
    ok_nc = ~np.isnan(oof_nc)
    for mode in ("none", calibration):
        part = _fit_calibration(
            mode, oof_nc[ok_nc], y_tr[ok_nc], [r for r, k in zip(train, ok_nc, strict=True) if k]
        )
        pc = _clamp(
            _apply_cal(part, m_nc.predict(_matrix(test, nocap, flag)), test) + ln_purse, test
        )
        ev["calibration"][mode + ", no captaincy"] = _price_metrics(pc, y_te_cr)
    cal_tr = _fit_calibration(calibration, oof[ok], y_tr[ok], tr_ok)
    pred = _clamp(_apply_cal(cal_tr, lin_te, test) + ln_purse, test)
    segs = {
        "capped Indian": lambda r: not r["is_overseas"] and r["intl_caps"] > 0,
        "uncapped Indian": lambda r: not r["is_overseas"] and r["intl_caps"] == 0,
        "overseas": lambda r: r["is_overseas"],
        "price >= 10 cr": lambda r: r["price_cr"] >= 10,
    }
    ev["segments"] = {}
    for nm, fn in segs.items():
        idx = [i for i, r in enumerate(test) if fn(r)]
        if idx:
            ev["segments"][nm] = {
                "model": _price_metrics(pred[idx], y_te_cr[idx]),
                "old curve": _price_metrics(old[idx], y_te_cr[idx]),
            }
    ev["test_examples"] = sorted(
        (
            {"season": r["season"], "name": r["name"], "actual": r["price_cr"],
             "model": round(float(math.exp(p)), 2), "old": round(float(math.exp(o)), 2)}
            for r, p, o in zip(test, pred, old, strict=True)
        ),
        key=lambda x: -x["actual"],
    )[:25]  # fmt: skip

    # ---- P(bought), out of time
    rtr = [r for r in risk_rows if r["season"] not in TEST_SEASONS]
    rte = [r for r in risk_rows if r["season"] in TEST_SEASONS]
    best_c, best_ll = 1.0, math.inf
    for c in (0.03, 0.1, 0.3, 1.0, 3.0):
        lls = []
        for s in sorted({r["season"] for r in rtr}):
            a_ = [r for r in rtr if r["season"] != s]
            b_ = [r for r in rtr if r["season"] == s]
            lm = _fit_logit(_matrix(a_, BOUGHT_FEATURES), np.array([r["bought"] for r in a_]), c)
            pb = lm.predict_proba(_matrix(b_, BOUGHT_FEATURES))[:, 1]
            from sklearn.metrics import log_loss

            lls.append(
                log_loss([r["bought"] for r in b_], np.clip(pb, 1e-6, 1 - 1e-6), labels=[0, 1])
            )
        if np.mean(lls) < best_ll:
            best_ll, best_c = float(np.mean(lls)), c
    lm = _fit_logit(_matrix(rtr, BOUGHT_FEATURES), np.array([r["bought"] for r in rtr]), best_c)
    pb = lm.predict_proba(_matrix(rte, BOUGHT_FEATURES))[:, 1]
    yb = np.array([r["bought"] for r in rte], dtype=float)
    ev["bought"] = {"C": best_c, "test": _logit_metrics(pb, yb)}
    for s in TEST_SEASONS:
        idx = [i for i, r in enumerate(rte) if r["season"] == s]
        ev["bought"][str(s)] = _logit_metrics(pb[idx], yb[idx])

    # ---- the shipped model: refit on every season from `first` (2025 and 2026 included)
    alpha_all = _choose_alpha(kind, price_rows, PRICE_FEATURES, flag)
    m_all = _fit_reg(
        kind,
        _matrix(price_rows, PRICE_FEATURES, flag),
        np.array([r["y"] for r in price_rows]),
        alpha_all,
    )
    oof_all = _oof(kind, price_rows, alpha_all, flag)
    ok_all = ~np.isnan(oof_all)
    y_all = np.array([r["y"] for r in price_rows])
    rows_ok = [r for r, k in zip(price_rows, ok_all, strict=True) if k]
    cal_all = _fit_calibration(calibration, oof_all[ok_all], y_all[ok_all], rows_ok)
    # the spread of a lot's price around its calibrated prediction, out of fold (sets `high`)
    resid = y_all[ok_all] - _apply_cal(cal_all, oof_all[ok_all], rows_ok)
    icpt, coef = _raw_coef(m_all, PRICE_FEATURES + list(flag))
    # a price is for a player entering the auction: `retained` = 0, so it drops out
    ret_coef = coef.pop("retained", None)
    lm_all = _fit_logit(
        _matrix(risk_rows, BOUGHT_FEATURES), np.array([r["bought"] for r in risk_rows]), best_c
    )
    bi, bc = _raw_coef(lm_all, BOUGHT_FEATURES)

    # mega-year retentions: what the model would have priced each retained player at
    rets = []
    for r in hist["retentions"]:
        if (
            r["season"] in (2018, 2022, 2025)
            and r["kind"] == "retained"
            and r.get("cricsheet_id")
            and r.get("salary_cr")
        ):
            rets.append(r)
    ev["mega_retentions"] = _retention_check(
        rets, hist, {"intercept": icpt, "coef": coef, **cal_all}
    )

    seasons = sorted({r["season"] for r in price_rows})
    model = {
        "schema": 1,
        "league": "ipl",
        "fitted": dt.date.today().isoformat(),
        "method": (
            f"hurdle: P(bought) logistic (L2, C={best_c}); ln(price / purse | bought) {kind} "
            f"regression (alpha={alpha_all}, standardised features, refolded to raw units); "
            f"top-end calibration {calibration} on out-of-fold predictions"
        ),
        "trained_on": {
            "seasons": [seasons[0], seasons[-1]],
            "price_rows": len(price_rows),
            "retention_rows": len(rets_in),
            "retentions": retentions,
            "retained_coef": ret_coef,
            "bought_rows": len(risk_rows),
            "bought_seasons": list(FULL_RETENTION_SEASONS),
        },
        "data": "data/curated/ipl_auction_history.json (Wikipedia, CC BY-SA 4.0)",
        "model_version": bayesian.MODEL_VERSION,
        # the default competition a price is for: the league's next one (export_site rewrites it
        # the same way from config/competitions.toml)
        "competition": _next_competition(),
        "floor_cr": 0.3,
        "price": {
            "intercept": icpt,
            "coef": coef,
            # top-end calibration knots + shift (pricing.calibrate), fitted out of fold
            **cal_all,
            "calibration_mode": calibration,
            "resid_sd": round(float(np.std(resid)), 4),
        },
        "bought": {"intercept": bi, "coef": bc},
        "evaluation": {
            "split": "train auctions <= 2024, test 2025 mega + 2026 mini (out of time)",
            "price": {
                k: {kk: vv for kk, vv in v.items() if not isinstance(vv, dict)}
                for k, v in ev["price"].items()
            },
            "calibration": {
                k: {kk: vv for kk, vv in v.items() if not isinstance(vv, dict)}
                for k, v in ev["calibration"].items()
            },
            "bought": ev["bought"]["test"],
        },
    }
    out.write_text(json.dumps(model, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    pricing.load_price_model.cache_clear()
    if report:
        report.write_text(json.dumps(ev, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(ev["price"], indent=1))
    print(json.dumps(ev["calibration"], indent=1))
    print(json.dumps(ev["calibration_groups"], indent=1))
    print(json.dumps(ev["segments"], indent=1))
    print(json.dumps(ev["bought"], indent=1))
    print(json.dumps(ev["mega_retentions"], indent=1))
    print(f"wrote {out}: {len(price_rows)} priced lots, {len(risk_rows)} risk-set rows")


def _next_competition() -> dict:
    from cricdex import competitions

    comps = [c for c in competitions.load().values() if c.league == "ipl"]
    c = max(comps, key=lambda c: (c.season, c.auction_date))
    return {"cycle": c.cycle, "purse": float(c.purse), "key": c.key}


def _retention_check(rets: list[dict], hist: dict, part: dict) -> dict:
    """Mega-year retention salaries are slab-set (not bids), so they're left out of the fit; as a
    check: the model's price for each retained player against what he was paid."""
    pm = master.load()
    caps = intl_appearances()
    apps = ipl_appearances()
    ratios = []
    for r in rets:
        a = hist["auctions"][str(r["season"])]
        date = a["date"]
        vals = asof_values(r["season"], date)
        cid = r["cricsheet_id"]
        rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
        v = vals.get(cid)
        ipl = [d for d in apps.get(cid, []) if d < date]
        country = r.get("country") or normalise(rec.get("country"))
        age = _years(date, str(rec["dob"])[:10]) if rec.get("dob") else None
        row = {
            "price_value": v["value"] if v else None, "value_sd": v["value_sd"] if v else None,
            "target_balls": v["target_balls"] if v else 0, "ipl_balls": v["ipl_balls"] if v else 0,
            "role": ROLE_MAP.get(rec.get("primary_role") or "", "batter"),
            "is_overseas": bool(country) and country != "IND",
            "intl_caps": bisect.bisect_left(caps.get(cid, []), date),
            "intl_caps_2y": _recent(caps.get(cid, []), date), "age": age,
            **_captaincy(cid, r["season"]),
            "ipl_seasons": len({d[:4] for d in ipl}),
            "ipl_gap": _years(date, ipl[-1]) if ipl else None,
        }  # fmt: skip
        f = pricing.market_features(row, "mega")
        share = math.exp(
            pricing.calibrate(pricing.calibration_part(part, f), pricing._linear(part, f))
        )
        ratios.append(share * a["purse_cr"] / r["salary_cr"])
    ratios = np.array(ratios)
    return {
        "n": int(len(ratios)),
        "median_model_over_salary": round(float(np.median(ratios)), 2),
        "share_model_at_least_salary": round(float(np.mean(ratios >= 1.0)), 3),
    }


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    app()
