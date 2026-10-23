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
from sklearn.base import BaseEstimator, RegressorMixin

from cricdex import leagues
from cricdex.config import DATA_DIR
from cricdex.scout import translation
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


def asof_sources(
    season: int, date: str
) -> tuple[dict[tuple[str, str], tuple[float, float, int]], dict[tuple[str, str], dict]]:
    """Every rating known at an auction: ({(cid, role): (IPL value, sd, IPL balls)},
    {(cid, role): {league: (value, sd)}}). Only fits whose cut-off is on or before `date`."""
    own: dict[tuple[str, str], tuple[float, float, int]] = {}
    other: dict[tuple[str, str], dict] = {}
    p = ipl_fit_path(season)
    if p.exists():
        for r in pl.read_parquet(p).iter_rows(named=True):
            if r["value"] is None:
                continue
            own[(r["cricsheet_id"], r["role"])] = (
                float(r["value"]), float(r["value_sd"] or 1.0), int(r["balls"] or 0)
            )  # fmt: skip
    for col in OTHER_LEAGUES:
        cands = [
            s
            for s in range(2010, season + 1)
            if f"{s}-01-01" <= date and league_fit_path(col, s).exists()
        ]
        if not cands:
            continue
        for r in pl.read_parquet(league_fit_path(col, max(cands))).iter_rows(named=True):
            if r["value"] is None or r["cricsheet_id"] is None:
                continue
            other.setdefault((r["cricsheet_id"], r["role"]), {})[col] = (
                float(r["value"]), float(r["value_sd"] or 1.0)
            )  # fmt: skip
    return own, other


def asof_values(season: int, date: str, which: str = "roles") -> dict[str, dict]:
    """Each player's value as of an auction, blended across leagues exactly as the auction pool
    blends them (export_site._export_auction_pool): per role, every league translated onto the IPL
    scale and combined with his IPL rating by precision (cricdex.scout.translation.blend; `which` =
    "roles" for the shipped translation, "roles_le2024" for the one fitted on seasons ≤ 2024); best
    role wins. `value_legacy` / `value_sd_legacy`: the scheme it replaced on 2026-10-23 (one discount
    per league, the 300-ball switch), the market price's input until a recipe on the translated
    value wins (candidate Y)."""
    own, other = asof_sources(season, date)
    tm = translation.load_model()
    best: dict[str, dict] = {}
    legacy: dict[str, tuple[float, float, int]] = {}
    ipl_balls: dict[str, int] = {}
    for (cid, _role), o in own.items():
        ipl_balls[cid] = ipl_balls.get(cid, 0) + o[2]
    for key in set(own) | set(other):
        cid, role = key
        o = own.get(key)
        oth = other.get(key, {})
        if role in translation.ROLES:
            val, vsd, _ = translation.blend(role, (o[0], o[1]) if o else None, oth, tm, which)
        else:
            val, vsd = (o[0], o[1]) if o else (None, None)
        lv, lsd, _ = translation.legacy_blend(o, oth)
        tb = o[2] if o else 0
        if val is not None and (cid not in best or val > best[cid]["value"]):
            best[cid] = {"value": val, "value_sd": vsd, "target_balls": tb}
        if cid not in legacy or lv > legacy[cid][0]:
            legacy[cid] = (lv, lsd, tb)
    for cid, b in best.items():
        b["ipl_balls"] = ipl_balls.get(cid, 0)
        lv = legacy.get(cid)
        b["value_legacy"], b["value_sd_legacy"] = (lv[0], lv[1]) if lv else (None, None)
        b["target_balls_legacy"] = lv[2] if lv else 0
    return best


ASOF_CONTRIB = DATA_DIR / "metrics" / ".playing_time" / "asof_contrib.parquet"


def _asof_contrib() -> dict[tuple[int, str], tuple[float, float]]:
    """(auction season, cid) → (contribution per match, its sd) as of that auction
    (`scripts/playing_time_fit.py asof-contrib`); empty when not built."""
    if not ASOF_CONTRIB.exists():
        return {}
    d = pl.read_parquet(ASOF_CONTRIB).select("season", "cid", "contrib", "contrib_sd")
    return {(s, c): (v, sd) for s, c, v, sd in d.iter_rows()}


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
    """The IPL-relevance weight export_site used until 2026-10-22 (the old curve's input, kept only
    for that baseline), as of `date`, for a player entering an auction (no current franchise)."""
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
    features_in, hist, apps = feature_fn(refresh_caps)
    return _build_rows(features_in, hist, apps)


def feature_fn(refresh_caps: bool = False):
    """(features_in(cid, season, date, vals, country) → the `market_features` inputs of a player as
    of an auction, the auction history, cid → IPL match dates). Shared by `build_rows` and
    scripts/keep_backtest.py (the squads before each retention deadline)."""
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
    verdicts = pricing.market_verdicts(hist)
    # each auction's lowest price (its lowest base price: 0.2 cr 2018-2024, 0.3 from 2025), the
    # floor a prediction for that auction is clamped to when scored
    floors: dict[int, float] = {}
    for r in hist["lots"]:
        if r.get("sold") and r.get("price_cr"):
            floors[r["season"]] = min(floors.get(r["season"], math.inf), float(r["price_cr"]))

    contrib = _asof_contrib()

    def features_in(cid: str, season: int, date: str, vals: dict, country: str | None) -> dict:
        rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
        v = vals.get(cid)
        ct = contrib.get((season, cid))
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
            # his value as of the auction: `price_value` / `value_sd` the blend every recipe up to
            # T was fitted on (one discount per league, the 300-ball switch: translation.legacy_blend),
            # `value_tr` / `value_sd_tr` the fitted league translation (candidate Y, 2026-10-23)
            "price_value": v["value_legacy"] if v else None,
            "value_sd": v["value_sd_legacy"] if v else None,
            "value_tr": v["value"] if v else None,
            "value_sd_tr": v["value_sd"] if v else None,
            # his contribution per match as of the auction (scripts/playing_time_fit.py asof-contrib):
            # the value of candidate X
            "contrib": ct[0] if ct else None,
            "contrib_sd": ct[1] if ct else None,
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
            "floor_cr": floors.get(season, 0.3),
            # the market's last verdict on him before this auction (pricing.market_features)
            **pricing.prior_verdict(verdicts.get(cid, []), season),
        }

    return features_in, hist, apps


def _build_rows(features_in, hist: dict, apps: dict) -> tuple:
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
        # retentions: keeping a player at a price reveals he is worth at least that to his
        # franchise, so each is a floor (a censored observation; `fit --retentions censored`).
        # Mega years: the agreed retention salary (slab-set, 18 / 14 / 11 cr in 2025); mini years
        # with a complete retained list: his contract salary (an older auction price), which the
        # franchise chose to keep paying rather than re-enter the auction.
        if cycle == "mega" or season in FULL_RETENTION_SEASONS:
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
                        "retention_kind": cycle,
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


# Tried, not shipped (the comparison rows in `fit`; docs/METHODOLOGY.md §6b), so computed for the
# training rows only, never by the site:
# * `mega_x_overseas`: an overseas player in a mega auction, as a regression term. The four
#   calibration groups (overseas split by auction type) do the same job and scored as well.
# * ERA, the 2025-27 player regulations (first used at the 2025 mega auction: an overseas player
#   must register for the mega auction to enter the next minis, one who pulls out after being bought
#   is banned for two seasons, an overseas mini-auction buy is paid at most 18 cr). The overseas
#   level fell about 0.3 (ln) below its auction type's 2018-24 level in both auctions of the cycle,
#   but a term fitted on 2025 made the 2026 overseas prices worse, not better, in median and mean
#   absolute error (walk forward), so it isn't shipped.
ERA = "overseas_x_rules_2025"
ERA_FIRST_SEASON = 2025
TRIED_FEATURES = ("mega_x_overseas", ERA)


# The form of the candidate being evaluated (`_use_form`): whether the shipped clamps include the
# IPL-evidence ceiling (the recipes before 2026-10-22 did), and the top of the value support the
# priced value is held to (None = pricing.MARKET_PV_MAX; a number = winsorised at the largest value
# of any training row: no extrapolation beyond the best player the market has priced).
_FORM: dict = {"ceiling": True, "pv_max": None, "cal": "none+group-median-offset", "tail": 0.2,
               "value": "best"}  # fmt: skip


def _form_of(spec: tuple) -> dict:
    return {
        "ceiling": True, "winsor": False, "cal": "none+group-median-offset", "tail": TAIL_SHARE,
        "value": "best", **(spec[4] if len(spec) > 4 else {}),
    }  # fmt: skip


def _valued(r: dict) -> dict:
    """The row as the candidate prices it: with `value` = "contrib" (candidate X) his contribution
    per match and its sd stand in for `price_value` / `value_sd`."""
    if _FORM.get("value") == "contrib":
        return {**r, "price_value": r.get("contrib"), "value_sd": r.get("contrib_sd")}
    if _FORM.get("value") == "translated":
        return {**r, "price_value": r.get("value_tr"), "value_sd": r.get("value_sd_tr")}
    return r


def _pv_support(rows: list[dict]) -> float:
    """The largest priced value (the cautious estimate, before any clamp) among `rows`."""
    out = -math.inf
    for r in rows:
        r = _valued(r)
        v = r.get("price_value")
        if v is not None:
            out = max(out, pricing.priced_value(v, r.get("value_sd")))
    return round(out, 3)


def _use_form(spec: tuple, train: list[dict] | None = None) -> None:
    form = _form_of(spec)
    _FORM["ceiling"] = form["ceiling"]
    _FORM["cal"] = form["cal"]
    _FORM["tail"] = form["tail"]
    _FORM["value"] = form["value"]
    _FORM["pv_max"] = _pv_support(train) if form["winsor"] and train else None


def _features(r: dict) -> dict[str, float]:
    """pricing.market_features for a history row, plus the tried-only terms."""
    f = pricing.market_features(_valued(r), r["cycle"], pv_max=_FORM["pv_max"])
    f["mega_x_overseas"] = f["overseas"] * f["mega"]
    f[ERA] = f["overseas"] * (1.0 if r["season"] >= ERA_FIRST_SEASON else 0.0)
    return f


def _matrix(rows: list[dict], names: list[str], extra: tuple[str, ...] = ()) -> np.ndarray:
    X = []
    for r in rows:
        f = _features(r)
        x = [f[k] for k in names]
        for e in extra:
            v = r.get(e)
            if e in ("prev_share", "base_share"):
                x += [math.log(v) if v else 0.0, 0.0 if v else 1.0]
            else:
                x.append(float(v or 0.0))
        X.append(x)
    return np.asarray(X, dtype=float)


class TobitRidge(RegressorMixin, BaseEstimator):
    """Linear regression with right-open censoring (a Tobit model), normal errors, L2 penalty.

    An exact row says ln price = x·b + e; a censored row (a retention) says only ln price ≥ its
    value: the franchise kept him at that price, so his worth is at least that (a floor, not a
    price). Maximises Σ_exact ln φ(r/σ) − ln σ + Σ_censored ln Φ((x·b − c)/σ) − α/2 ‖b‖² (intercept
    and σ unpenalised) by L-BFGS with the analytic gradient. `predict` is the median of the latent
    ln price. On standardised features (inside a pipeline after StandardScaler).

    `link` sets how the linear index η = x·b becomes the median ln share of the purse:
    * "log": the median is η itself (ln price is linear in the features, without limit);
    * "sat": the median is ln S + ln σ(η), σ the logistic function: below the top it is η + ln S
      (the log-linear model), at the top it saturates at S, the most one franchise pays for one
      player as a share of its purse. S is a parameter fitted with the rest (ML), bounded by the
      purse itself (S ≤ 1: a bid can't exceed the purse, the IPL's own rule). The second-highest
      bidder sets an auction price, and what he can commit to one lot is limited by the squad he
      still has to fill from the same purse: the saturation is that budget limit (§6b)."""

    def __init__(self, alpha: float = 1.0, link: str = "log"):
        self.alpha = alpha
        self.link = link

    def fit(self, X: np.ndarray, y: np.ndarray, cens: np.ndarray | None = None):
        from scipy.optimize import minimize
        from scipy.special import expit, log_expit, log_ndtr

        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        c = np.zeros(len(y), bool) if cens is None else np.asarray(cens, bool)
        e = ~c
        n, p = X.shape
        sd0 = float(np.std(y[e])) if e.any() else 1.0
        sat = self.link == "sat"

        def nll(th: np.ndarray) -> tuple[float, np.ndarray]:
            b0, b, ls = th[0], th[1 : p + 1], th[p + 1]
            s = math.exp(ls)
            eta = b0 + X @ b
            mu = th[p + 2] + log_expit(eta) if sat else eta
            g_mu = np.zeros(n)
            g_ls = 0.0
            f = 0.0
            if e.any():
                r = (y[e] - mu[e]) / s
                f += float(np.sum(0.5 * r * r + ls))
                g_mu[e] = -r / s
                g_ls += float(np.sum(1.0 - r * r))
            if c.any():
                z = (mu[c] - y[c]) / s
                lc = log_ndtr(z)
                # φ/Φ (the inverse Mills ratio); -z for very negative z, where it tends to -z
                zz = np.maximum(z, -30.0)
                lam = np.where(
                    z > -30.0,
                    np.exp(-0.5 * zz * zz - 0.5 * math.log(2 * math.pi) - log_ndtr(zz)),
                    -z,
                )
                f -= float(np.sum(lc))
                g_mu[c] = -lam / s
                g_ls += float(np.sum(lam * z))
            f += 0.5 * self.alpha * float(b @ b)
            g = np.empty(len(th))
            g_eta = g_mu * expit(-eta) if sat else g_mu  # d ln σ(η) / dη = σ(−η)
            g[0] = g_eta.sum()
            g[1 : p + 1] = X.T @ g_eta + self.alpha * b
            g[p + 1] = g_ls
            if sat:
                g[p + 2] = g_mu.sum()
            return f, g

        th0 = np.zeros(p + 3 if sat else p + 2)
        th0[0] = float(np.mean(y[e])) if e.any() else float(np.mean(y))
        th0[p + 1] = math.log(max(sd0, 1e-3))
        bounds = None
        if sat:
            # start at S = the purse (where ln σ(η) ≈ η for the typical lot, the log-linear fit)
            th0[p + 2] = 0.0
            bounds = [(None, None)] * (p + 2) + [(math.log(1e-3), 0.0)]
        res = minimize(
            nll, th0, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 10000}
        )
        self.intercept_ = float(res.x[0])
        self.coef_ = res.x[1 : p + 1].copy()
        self.scale_ = float(math.exp(res.x[p + 1]))
        self.cap_share_ = float(math.exp(res.x[p + 2])) if sat else None
        self.converged_ = bool(res.success)
        return self

    def eta(self, X: np.ndarray) -> np.ndarray:
        return self.intercept_ + np.asarray(X, dtype=float) @ self.coef_

    def predict(self, X: np.ndarray) -> np.ndarray:
        from scipy.special import log_expit

        eta = self.eta(X)
        return math.log(self.cap_share_) + log_expit(eta) if self.link == "sat" else eta


def _cens(rows: list[dict]) -> np.ndarray:
    """Which rows are censored (a retention under `--retentions censored`)."""
    return np.array([bool(r.get("censored")) for r in rows], dtype=bool)


def _fit_reg(kind: str, X: np.ndarray, y: np.ndarray, alpha: float, cens: np.ndarray | None = None):
    from sklearn.linear_model import HuberRegressor, QuantileRegressor, Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if kind in ("tobit", "tobit-sat"):
        link = "sat" if kind == "tobit-sat" else "log"
        return Pipeline([("sc", StandardScaler()), ("est", TobitRidge(alpha, link))]).fit(
            X, y, est__cens=cens
        )
    if cens is not None and cens.any():
        raise ValueError(f"{kind} can't take censored rows: use kind 'tobit'")
    from sklearn.pipeline import make_pipeline

    if kind == "ridge":
        est = Ridge(alpha=alpha)
    elif kind == "huber":
        est = HuberRegressor(alpha=alpha / 100.0, epsilon=1.35, max_iter=2000)
    else:
        est = QuantileRegressor(quantile=0.5, alpha=alpha / 1000.0, solver="highs")
    return make_pipeline(StandardScaler(), est).fit(X, y)


TOP_PRE = 20  # the top end chosen before the auction: each auction's TOP_PRE dearest predictions


def _price_metrics(
    pred_ln_cr: np.ndarray, y_ln_cr: np.ndarray, rows: list[dict] | None = None
) -> dict:
    err = pred_ln_cr - y_ln_cr
    ape = np.abs(np.exp(err) - 1.0)
    from scipy.stats import spearmanr

    out = {
        "n": int(len(err)),
        "mae_ln": round(float(np.mean(np.abs(err))), 3),
        "median_abs_pct": round(100 * float(np.median(ape)), 1),
        "within_50pct": round(100 * float(np.mean(ape <= 0.5)), 1),
        "bias_ln": round(float(np.mean(err)), 3),
        "median_bias_ln": round(float(np.median(err)), 3),
        "spearman": (
            round(float(spearmanr(pred_ln_cr, y_ln_cr).statistic), 3) if len(err) > 2 else None
        ),
        # the lots that SOLD for 10 cr+: geometric-mean predicted / actual. Chosen by the outcome,
        # so even a perfectly calibrated model comes out well below 1 (regression to the mean)
        "top10_ratio": (
            round(float(np.exp(np.mean(err[y_ln_cr >= math.log(10)]))), 3)
            if np.any(y_ln_cr >= math.log(10))
            else None
        ),
    }
    if rows is not None:
        # the top end chosen BEFORE the auction: in each auction the TOP_PRE lots the model prices
        # highest; geometric-mean actual / predicted (1 = right on average; below 1 = over-priced)
        top = []
        for s in sorted({r["season"] for r in rows}):
            idx = [i for i, r in enumerate(rows) if r["season"] == s]
            top += sorted(idx, key=lambda i: -pred_ln_cr[i])[:TOP_PRE]
        out["top_pre_ratio"] = round(float(np.exp(-np.mean(err[top]))), 3)
    return out


# ---- calibration -----------------------------------------------------------------------------------

CAL_MODES = (
    "none", "isotonic", "isotonic+smear", "quantile", "quantile+smear", "quantile-top",
    "quantile-top+smear", "quantile+group-offset", "group-quantile", "quantile+group-offset-recent",
    "group-quantile+group-offset-recent", "quantile+group-median-offset",
    "isotonic+group-median-offset", "none+group-median-offset",
    "isotonic-tail+group-median-offset", "hinge+group-median-offset",
)  # fmt: skip
# The shipped calibration: no map, each group shifted by its median out-of-fold residual (so the
# price is each kind of player's median). The quantile map (shipped until 2026-10-22) stretched the
# top to match real prices' spread, which over-priced the lots it predicted highest (§6b).
CALIBRATION = "none+group-median-offset"
# "-recent": the group offsets from the last RECENT_SEASONS auctions only (the market moves: the
# 2025-27 rules capped an overseas mini-auction buy's fee at 18 cr)
RECENT_SEASONS = 2
# The calibration groups (shipped in config/price_model.json; pricing.calibration_part): ranges on
# market_features. caps = ln(1 + international caps), so caps > 0 = capped. Overseas players are
# split by auction type: their level differs between mega and mini auctions (§6b).
CAL_GROUPS = [
    {"name": "overseas_mega", "when": {"overseas": [1, 1], "mega": [1, 1]}},
    {"name": "overseas_mini", "when": {"overseas": [1, 1], "mega": [0, 0]}},
    {"name": "capped_indian", "when": {"overseas": [0, 0], "caps": [1e-9, 1e9]}},
    {"name": "uncapped_indian", "when": {"overseas": [0, 0], "caps": [0, 0]}},
]
# the groups of the previous recipe (one overseas group), for the comparison rows
CAL_GROUPS_3 = [
    {"name": "overseas", "when": {"overseas": [1, 1]}},
    {"name": "capped_indian", "when": {"overseas": [0, 0], "caps": [1e-9, 1e9]}},
    {"name": "uncapped_indian", "when": {"overseas": [0, 0], "caps": [0, 0]}},
]
GROUP_KNOTS = 11
CAL_KNOTS = 21
TAIL_SHARE = (
    0.2  # isotonic-tail: the top fifth of the out-of-fold lots sets the slope beyond the map
)


def _oof(
    kind: str, rows: list[dict], alpha: float, extra=(), names=None, retained: bool = False
) -> np.ndarray:
    """Out-of-fold linear predictions (ln price / purse) for the auction lots in `rows`: each season
    predicted by a fit on every other season (retention rows train but are predicted only when
    `retained`: then only they are)."""
    names = names or PRICE_FEATURES
    out = np.full(len(rows), np.nan)
    for s in sorted({r["season"] for r in rows}):
        tr = [r for r in rows if r["season"] != s]
        idx = [i for i, r in enumerate(rows)
               if r["season"] == s and bool(r.get("retained")) == retained]  # fmt: skip
        if not idx:
            continue
        m = _fit_reg(
            kind, _matrix(tr, names, extra), np.array([r["y"] for r in tr]), alpha, _cens(tr)
        )
        out[idx] = m.predict(_matrix([rows[i] for i in idx], names, extra))
    return out


def _group_of(r: dict, groups: list[dict] | None = None) -> str | None:
    f = pricing.market_features(r, r["cycle"])
    for g in groups or CAL_GROUPS:
        if all(lo <= f[k] <= hi for k, (lo, hi) in g["when"].items()):
            return g["name"]
    return None


def _quantile_map(lin: np.ndarray, y: np.ndarray, knots: int) -> dict:
    q = np.linspace(0.0, 1.0, knots)
    xs, ix = np.unique(np.quantile(lin, q), return_index=True)
    ys = np.quantile(y, q)[ix]
    return {"x": [round(float(x), 6) for x in xs], "y": [round(float(v), 6) for v in ys]}


def _hinge_slope(lin: np.ndarray, y: np.ndarray, cens: tuple | None, knot: float) -> float:
    """The slope β ∈ [0, 1] of the price on the prediction above `knot` (1 below it), by maximum
    likelihood on the out-of-fold lots (exact: normal) and retentions (censored: P(price ≥ what he
    was retained at)), with its own residual sd: the market's top-end response, estimated from the
    lots that reached the auction AND the stars kept out of it (each a floor), so neither the
    released players alone (who would flatten the top) nor the log-linear index (slope 1) sets it."""
    from scipy.optimize import minimize
    from scipy.special import log_ndtr

    lc, yc = cens if cens is not None else (np.zeros(0), np.zeros(0))

    def g(x: np.ndarray, b: float) -> np.ndarray:
        return np.where(x > knot, knot + b * (x - knot), x)

    def nll(th: np.ndarray) -> float:
        b, ls = th[0], th[1]
        sd = math.exp(ls)
        r = (y - g(lin, b)) / sd
        f = float(np.sum(0.5 * r * r + ls))
        if len(lc):
            f -= float(np.sum(log_ndtr((g(lc, b) - yc) / sd)))
        return f

    res = minimize(nll, np.array([1.0, math.log(max(float(np.std(y)), 1e-3))]),
                   method="L-BFGS-B", bounds=[(0.0, 1.0), (None, None)])  # fmt: skip
    return float(res.x[0])


def _fit_calibration(
    mode: str,
    lin: np.ndarray,
    y: np.ndarray,
    rows: list[dict],
    groups: list[dict] | None = None,
    cens: tuple | None = None,
) -> dict:
    """{"calibration": {x, y} or None, "shift": float, "groups": [...]} from out-of-fold predictions
    `lin` and the actual ln shares `y`. isotonic: E[y | prediction], monotone (it undoes the
    regression to the mean a shrunken fit leaves at the top); quantile: the predictions' quantiles
    mapped onto the actual prices' (the same spread as real auctions); none: no map; +smear: plus
    Duan's retransformation, ln mean(e^residual), so the price is a mean rather than a median;
    +group-offset / +group-median-offset: each group's mean / median residual as its own shift."""
    from sklearn.isotonic import IsotonicRegression

    groups = groups or CAL_GROUPS
    part: dict = {"calibration": None, "shift": 0.0}
    q = np.linspace(0.0, 1.0, CAL_KNOTS)
    if mode.startswith("isotonic"):
        iso = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(lin, y)
        xs = np.unique(np.quantile(lin, q))
        part["calibration"] = {
            "x": [round(float(x), 6) for x in xs],
            "y": [round(float(v), 6) for v in iso.predict(xs)],
        }
        if mode.startswith("isotonic-tail"):
            # beyond the last knot (the highest out-of-fold prediction) the map continues at the slope
            # real prices show on the prediction over the top fifth of the lots (least squares,
            # held to [0, 1]): the market's own top-end response, not the log-linear index's slope 1
            top = lin >= np.quantile(lin, 1.0 - TAIL_SHARE)
            slope = float(np.polyfit(lin[top], y[top], 1)[0]) if top.sum() >= 3 else 1.0
            part["calibration"]["hi_slope"] = round(min(1.0, max(0.0, slope)), 6)
    elif mode.startswith("hinge"):
        # a hinge: slope 1 up to the top fifth of the lots' predictions, slope β above it (fitted on
        # lots and censored retentions, `_hinge_slope`), continued at β beyond (`hi_slope`)
        knot = float(np.quantile(lin, 1.0 - _FORM["tail"]))
        b = _hinge_slope(lin, y, cens, knot)
        part["calibration"] = {
            "x": [round(knot, 6), round(knot + 1.0, 6)],
            "y": [round(knot, 6), round(knot + b, 6)],
            "hi_slope": round(b, 6),
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
        names = [_group_of(r, groups) for r in rows]
        part["groups"] = []
        for g in groups:
            m = np.array([x == g["name"] for x in names])
            if m.sum() >= 30:
                part["groups"].append(
                    {**g, "calibration": _quantile_map(lin[m], y[m], GROUP_KNOTS), "shift": 0.0}
                )
    if mode.startswith("group-quantile") and mode.endswith("-recent"):
        # each group's own map, then its mean residual over the recent auctions as its shift
        res = y - _apply_cal(part, lin, rows)
        last = max(r["season"] for r in rows)
        names = [_group_of(r, groups) for r in rows]
        for g in part["groups"]:
            m = np.array([x == g["name"] and r["season"] > last - RECENT_SEASONS
                          for x, r in zip(names, rows, strict=True)])  # fmt: skip
            if m.sum():
                g["shift"] = round(float(np.mean(res[m])), 6)
    elif (
        mode.endswith("+group-offset")
        or mode.endswith("+group-offset-recent")
        or mode.endswith("+group-median-offset")
    ):
        # the global map (if any), then each group's mean (median) out-of-fold residual as its shift
        res = y - _apply_cal(part, lin, rows)
        names = [_group_of(r, groups) for r in rows]
        last = max(r["season"] for r in rows)
        recent = mode.endswith("-recent")
        stat = np.median if mode.endswith("+group-median-offset") else np.mean
        part["groups"] = []
        for g in groups:
            m = np.array([x == g["name"] and (not recent or r["season"] > last - RECENT_SEASONS)
                          for x, r in zip(names, rows, strict=True)])  # fmt: skip
            if m.sum():
                part["groups"].append(
                    {**g, "calibration": part["calibration"],
                     "shift": round(float(stat(res[m])), 6)}
                )  # fmt: skip
    if mode.endswith("+smear"):
        resid = y - _apply_cal(part, lin, rows)
        part["shift"] = round(float(np.log(np.mean(np.exp(resid)))), 6)
    return part


def _clamp(pred_ln_cr: np.ndarray, rows: list[dict]) -> np.ndarray:
    """The shipped price's clamps on a predicted ln crore: the auction's floor (its lowest base
    price: 0.3 cr from 2025, 0.2 before; until 2026-10-22 always 0.3, which put a ln(1.5) error on
    every 0.2 cr lot of 2018-2024) and the IPL-evidence ceiling (pricing.price_ceiling), so the test
    scores what the site would show."""
    lo = np.log([r.get("floor_cr", 0.3) for r in rows])
    out = np.maximum(pred_ln_cr, lo)
    if not _FORM["ceiling"]:
        return out
    hi = np.log([_old_ceiling(r.get("target_balls")) for r in rows])
    return np.minimum(out, hi)


def _old_ceiling(target_balls) -> float:
    """The IPL-evidence ceiling the site applied until 2026-10-22 (27 cr × (0.5 + 0.5 × min(1, IPL
    balls / 600))), kept here only to score the earlier recipes as they were shipped."""
    b = target_balls if isinstance(target_balls, int | float) and math.isfinite(target_balls) else 0
    return 27.0 * (0.5 + 0.5 * min(1.0, max(b, 0) / 600))


def _apply_cal(part: dict, lin: np.ndarray, rows: list[dict]) -> np.ndarray:
    """The calibration on each row's linear prediction, by its group (pricing.calibration_part)."""
    out = []
    for v, r in zip(lin, rows, strict=True):
        cal = pricing.calibration_part(part, pricing.market_features(r, r["cycle"]))
        out.append(pricing.calibrate(cal, float(v)))
    return np.array(out)


# The hand-set pieces of the old on-field price, kept here only to reproduce that baseline in the
# comparison tables (both were removed from the site on 2026-10-22, audit items 4 and 6): the
# IPL-relevance penalty (up to 36 runs per 100 balls, `_relevance`) and the role premium.
OLD_PEN_SCALE_VALUE = 36.0
OLD_ROLE_MULT = {"all_rounder": 1.15, "keeper": 1.05}


def _old_curve(r: dict) -> float:
    """The hand-set on-field curve as the site priced a player entering this auction until
    2026-10-22: his value less the IPL-relevance discount, cautious estimate, the role premium,
    IPL-evidence ceiling."""
    if r["price_value"] is None:
        return 0.3
    rel = _relevance(r["last_ipl"], r["age"], r["country"], AUCTIONS_DATES[r["season"]])
    v = r["price_value"] - (1 - rel) * OLD_PEN_SCALE_VALUE
    adj = pricing.priced_value(v, r["value_sd"])
    raw = pricing.PV_BASE * math.exp(pricing.PV_SCALE * adj) * OLD_ROLE_MULT.get(r["role"], 1.0)
    return max(0.3, min(pricing.price_ceiling(r["target_balls"]), raw))


def _choose_alpha(kind: str, rows: list[dict], names: list[str], extra=()) -> float:
    """Leave-one-auction-out over the training seasons; lowest mean absolute log error."""
    seasons = sorted({r["season"] for r in rows})
    best = (math.inf, ALPHAS[0])
    for alpha in ALPHAS:
        errs = []
        for s in seasons:
            tr = [r for r in rows if r["season"] != s]
            # scored on the auction lots only: a retention is a floor, not a price
            te = [r for r in rows if r["season"] == s and not r.get("retained")]
            if len(te) < 5:
                continue
            m = _fit_reg(
                kind, _matrix(tr, names, extra), np.array([r["y"] for r in tr]), alpha, _cens(tr)
            )
            errs += list(
                np.abs(m.predict(_matrix(te, names, extra)) - np.array([r["y"] for r in te]))
            )
        e = float(np.mean(errs))
        if e < best[0]:
            best = (e, alpha)
    return best[1]


def _raw_coef(model, names: list[str]) -> tuple[float, dict[str, float]]:
    """Fold the scaler into the coefficients: intercept + Σ coef × raw feature (the linear index η;
    `_link` says how η becomes the median ln share)."""
    sc, est = model[0], model[-1]
    beta = np.asarray(est.coef_, dtype=float).ravel()
    scale = np.where(sc.scale_ == 0, 1.0, sc.scale_)
    raw = beta / scale
    icpt = float(np.asarray(est.intercept_).ravel()[0]) - float(np.sum(raw * sc.mean_))
    return round(icpt, 6), {k: round(float(c), 6) for k, c in zip(names, raw, strict=True)}


def _link(model) -> dict:
    """The shipped `price.link` (pricing.link_share): {"kind": "log"} or {"kind": "sat",
    "cap_share": S}."""
    est = model[-1]
    if getattr(est, "link", "log") == "sat":
        return {"kind": "sat", "cap_share": round(float(est.cap_share_), 6)}
    return {"kind": "log"}


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


def _calibration_for(
    kind: str, train: list[dict], alpha: float, names: list[str], mode: str, groups, flag=()
) -> dict:
    """The calibration part of a recipe from the training seasons' own out-of-fold predictions
    (lots; and, for "hinge", the censored retentions too), with `resid_sd`."""
    y = np.array([r["y"] for r in train])
    o = _oof(kind, train, alpha, flag, names=names)
    ok = ~np.isnan(o)
    rows_ok = [r for r, k in zip(train, ok, strict=True) if k]
    cens = None
    if mode.startswith("hinge"):
        oc = _oof(kind, train, alpha, flag, names=names, retained=True)
        okc = ~np.isnan(oc) & _cens(train)
        cens = (oc[okc], y[okc])
    part = _fit_calibration(mode, o[ok], y[ok], rows_ok, groups, cens=cens)
    # the spread of a lot around its calibrated prediction, out of fold (the scale of the held-out
    # log-likelihood; the shipped `resid_sd`)
    part["resid_sd"] = float(np.std(y[ok] - _apply_cal(part, o[ok], rows_ok)))
    return part


def _recipe(
    kind: str, train: list[dict], names: list[str], mode: str, groups: list[dict], flag=()
) -> tuple:
    """The whole price recipe on `train`: the regression (alpha by leave-one-auction-out) and its
    calibration fitted on the training seasons' own out-of-fold predictions."""
    alpha = _choose_alpha(kind, train, names, flag)
    y = np.array([r["y"] for r in train])
    m = _fit_reg(kind, _matrix(train, names, flag), y, alpha, _cens(train))
    return m, _calibration_for(kind, train, alpha, names, mode, groups, flag)


def _recipe_pred(m, part: dict, test: list[dict], names: list[str], flag=()) -> np.ndarray:
    """ln crore as shipped: calibrated, × purse, clamped."""
    lin = m.predict(_matrix(test, names, flag))
    return _clamp(_apply_cal(part, lin, test) + np.log([r["purse"] for r in test]), test)


def _scored(pred: np.ndarray, test: list[dict]) -> dict:
    """Metrics overall, per auction and per calibration group (the four shipped groups)."""
    y = np.log([r["price_cr"] for r in test])
    out = _price_metrics(pred, y, test)
    for s in sorted({r["season"] for r in test}):
        idx = [i for i, r in enumerate(test) if r["season"] == s]
        out[str(s)] = _price_metrics(pred[idx], y[idx], [test[i] for i in idx])
    gs = [_group_of(r) for r in test]
    for g in [*CAL_GROUPS, {"name": "overseas"}]:
        if g["name"] == "overseas":
            idx = [i for i, x in enumerate(gs) if x and x.startswith("overseas")]
        else:
            idx = [i for i, x in enumerate(gs) if x == g["name"]]
        if idx:
            out[g["name"]] = _price_metrics(pred[idx], y[idx], [test[i] for i in idx])
    return out


def _loao(kind: str, rows: list[dict], lots: list[dict], names, mode, groups, flag=()) -> dict:
    """Leave one auction out: each auction 2019-2026 predicted by the recipe fitted on all the
    others (later ones included), pooled."""
    preds, tests = [], []
    for s in sorted({r["season"] for r in lots}):
        if s < 2019:
            continue
        m, part = _recipe(kind, [r for r in rows if r["season"] != s], names, mode, groups, flag)
        te = [r for r in lots if r["season"] == s]
        preds.append(_recipe_pred(m, part, te, names, flag))
        tests += te
    return _scored(np.concatenate(preds), tests)


# ---- the selection protocol (issue I3 rework, 2026-10-22) -------------------------------------------
#
# The recipe is CHOSEN on auctions up to 2024 only, then scored on the 2025 mega and 2026 mini
# auctions ONCE. Until 2026-10-22 about twenty recipes were compared on those same 2025-26 lots and
# the best kept, which made the "out-of-time" score a best-of-twenty on the test set.
#
# Selection: leave one auction out over 2019-2024 (each auction predicted by the recipe fitted on the
# other auctions up to 2024; mean absolute ln error on its lots), and, as a second view, a validation
# split (fitted up to 2022, scored on the 2023 and 2024 mini auctions). The candidate with the lowest
# leave-one-out error is chosen. The candidates are declared here, before any test number is seen.
VALID_TRAIN_LAST = 2022
SELECT_LAST = 2024
PRIOR_FEATURES = ["prior", "no_prior", "prior_years", "prior_x_years", "prior_retained"]
_NO_CAP = [f for f in PRICE_FEATURES if f not in CAPTAIN_FEATURES]
_NO_SQ = [f for f in PRICE_FEATURES if f != "pv_pos_sq"]
# name: (features, regression kind, mega-year retentions "exact" | "censored", mini-year retentions
# censored too[, form: {"ceiling": the shipped clamp includes the IPL-evidence ceiling (default
# True, as every recipe up to K was shipped), "winsor": the priced value held to its training
# support}]). "tobit-sat": the saturating budget-limit link (TobitRidge). Candidates L-T were
# declared on 2026-10-22 (top-end rework) before any of their test numbers was computed.
CANDIDATES: dict[str, tuple] = {
    "A  previous: Huber, mega retentions as prices": (PRICE_FEATURES, "huber", "exact", False),
    "B  A without captaincy": (_NO_CAP, "huber", "exact", False),
    "C  A + prior market price": (PRICE_FEATURES + PRIOR_FEATURES, "huber", "exact", False),
    "D  C without captaincy": (_NO_CAP + PRIOR_FEATURES, "huber", "exact", False),
    "E  C as Tobit, retentions still as prices": (
        PRICE_FEATURES + PRIOR_FEATURES, "tobit", "exact", False),
    "F  C as Tobit, mega retentions censored (floors)": (
        PRICE_FEATURES + PRIOR_FEATURES, "tobit", "censored", False),
    "G  F + mini-year retentions censored": (
        PRICE_FEATURES + PRIOR_FEATURES, "tobit", "censored", True),
    "H  G without captaincy": (_NO_CAP + PRIOR_FEATURES, "tobit", "censored", True),
    "I  G without the prior (censoring alone)": (PRICE_FEATURES, "tobit", "censored", True),
    "J  F without captaincy": (_NO_CAP + PRIOR_FEATURES, "tobit", "censored", False),
    "K  F without the prior (censoring alone)": (PRICE_FEATURES, "tobit", "censored", False),
    "L  K without the IPL-evidence ceiling (raw log-linear)": (
        PRICE_FEATURES, "tobit", "censored", False, {"ceiling": False}),
    "M  L, value held to its training support": (
        PRICE_FEATURES, "tobit", "censored", False, {"ceiling": False, "winsor": True}),
    "N  L with the saturating budget limit (S fitted)": (
        PRICE_FEATURES, "tobit-sat", "censored", False, {"ceiling": False}),
    "R  L with a monotone calibration and a fitted top tail": (
        PRICE_FEATURES, "tobit", "censored", False,
        {"ceiling": False, "cal": "isotonic-tail+group-median-offset"}),
    "S  R, value held to its training support": (
        PRICE_FEATURES, "tobit", "censored", False,
        {"ceiling": False, "winsor": True, "cal": "isotonic-tail+group-median-offset"}),
    "T  S without the quadratic value term": (
        _NO_SQ, "tobit", "censored", False,
        {"ceiling": False, "winsor": True, "cal": "isotonic-tail+group-median-offset"}),
    # declared after the first selection run (2026-10-22): R-T's lots-only top map lost on the
    # retentions' held-out likelihood (it priced the stars franchises kept below what they were
    # kept at), so the top-end slope is fitted on lots AND censored retentions together
    "U  L, value held to its training support, top-end hinge (top fifth)": (
        PRICE_FEATURES, "tobit", "censored", False,
        {"ceiling": False, "winsor": True, "cal": "hinge+group-median-offset", "tail": 0.2}),
    "V  U with the hinge at the top tenth": (
        PRICE_FEATURES, "tobit", "censored", False,
        {"ceiling": False, "winsor": True, "cal": "hinge+group-median-offset", "tail": 0.1}),
    "W  U with the hinge at the top twentieth": (
        PRICE_FEATURES, "tobit", "censored", False,
        {"ceiling": False, "winsor": True, "cal": "hinge+group-median-offset", "tail": 0.05}),
    # declared 2026-10-22 evening (audit items 4 and 6), before any of its numbers: T with the value
    # replaced by the contribution per match (both roles at their expected balls, above
    # replacement; scout/playing_time.py) instead of the better role's rate per 100 balls
    "X  T with the contribution per match as the value": (
        _NO_SQ, "tobit", "censored", False,
        {"ceiling": False, "winsor": True, "cal": "isotonic-tail+group-median-offset",
         "value": "contrib"}),
    # declared 2026-10-23 (audit item 5), before any of its numbers: T with the value blended through
    # the fitted league translation (scripts/league_translation_fit.py; per league and role, a
    # precision blend with no 300-ball switch) instead of one discount per league
    "Y  T with the fitted league translation as the value": (
        _NO_SQ, "tobit", "censored", False,
        {"ceiling": False, "winsor": True, "cal": "isotonic-tail+group-median-offset",
         "value": "translated"}),
}  # fmt: skip
# P(bought): the previous features, and with the prior market price
BOUGHT_CANDIDATES = {
    "previous": BOUGHT_FEATURES,
    "+ prior market price": BOUGHT_FEATURES + PRIOR_FEATURES,
}


def shipped_spec(model: dict | None = None) -> tuple:
    """The candidate the shipped model was built from (its `evaluation.chosen`), for the scripts that
    refit the recipe on earlier auctions (bidplan_backtest, auction_calibrate)."""
    model = model or pricing.load_price_model() or {}
    chosen = (model.get("evaluation") or {}).get("chosen")
    if chosen not in CANDIDATES:
        raise ValueError(f"the shipped price model names no known recipe ({chosen!r}): rerun `fit`")
    return CANDIDATES[chosen]


def fit_price_part(
    price_rows: list[dict], ret_rows: list[dict], spec: tuple, first: int, before: int
) -> dict:
    """The `price` part of a model (pricing.market_price reads it) for the recipe `spec`, trained on
    auctions `first` … `before` − 1 only: the walk-forward price model of scripts/bidplan_backtest.py,
    auction_calibrate.py and keep_backtest.py."""
    names, kind = spec[0], spec[1]
    rows = [r for r in _rows_for(price_rows, ret_rows, first, spec) if r["season"] < before]
    _use_form(spec, rows)
    y = np.array([r["y"] for r in rows])
    alpha = _choose_alpha(kind, rows, names)
    m = _fit_reg(kind, _matrix(rows, names), y, alpha, _cens(rows))
    cal = _calibration_for(kind, rows, alpha, names, _FORM["cal"], CAL_GROUPS)
    icpt, coef = _raw_coef(m, names)
    out = {"intercept": icpt, "coef": coef, "link": _link(m), **cal}
    if _FORM["pv_max"] is not None:
        out["pv_max"] = _FORM["pv_max"]
    return out


def _rows_for(price_rows: list[dict], ret_rows: list[dict], first: int, spec: tuple) -> list[dict]:
    """The training rows of a candidate: every lot from `first`, the mega-year retentions (as prices
    or censored) and, when asked, the mini-year retentions (censored)."""
    mega, mini = spec[2], spec[3]
    out = [r for r in price_rows if r["season"] >= first]
    for r in ret_rows:
        if r["season"] < first:
            continue
        if r["retention_kind"] == "mega":
            out.append({**r, "censored": mega == "censored"})
        elif mini:
            out.append({**r, "censored": True})
    return out


def _evaluate_on(kind, names, train, test, mode=None, groups=None) -> dict:
    m, part = _recipe(kind, train, names, mode or _FORM["cal"], groups or CAL_GROUPS)
    return _scored(_recipe_pred(m, part, test, names), test)


def _heldout_loglik(kind, rows, names, last, first_held=2018, mode=None) -> dict:
    """Leave one auction out over `first_held`..`last` (auctions up to `last` only), scored by the
    held-out log-likelihood of every lot (exact: normal density of its ln-price error) and every
    mega-auction retention (censored: the chance the price is at least what he was retained at),
    with each fit's own out-of-fold residual sd as the scale. A proper score for both kinds of
    evidence; lots-only error can't see the retained players at all. Also the revealed-preference
    check: the share of held-out retentions priced at or above their retention price."""
    from scipy.stats import norm

    rows = [r for r in rows if r["season"] <= last]
    ll_lot: list[float] = []
    ll_ret: list[float] = []
    ratio: list[float] = []
    for s in sorted({r["season"] for r in rows}):
        if s < first_held:
            continue
        lots = [r for r in rows if r["season"] == s and not r.get("retained")]
        rets = [r for r in rows if r["season"] == s and r.get("retention_kind") == "mega"]
        if not lots and not rets:
            continue
        m, part = _recipe(
            kind, [r for r in rows if r["season"] != s], names, mode or _FORM["cal"], CAL_GROUPS
        )
        sd = part["resid_sd"]
        if lots:
            e = _recipe_pred(m, part, lots, names) - np.log([r["price_cr"] for r in lots])
            ll_lot += list(norm.logpdf(e / sd) - math.log(sd))
        if rets:
            z = (_recipe_pred(m, part, rets, names) - np.log([r["price_cr"] for r in rets])) / sd
            ll_ret += list(norm.logcdf(z))
            ratio += list(np.exp(z * sd))
    n = len(ll_lot) + len(ll_ret)
    return {
        "loglik_per_obs": round((sum(ll_lot) + sum(ll_ret)) / n, 4),
        "loglik_lots": round(float(np.mean(ll_lot)), 4),
        "loglik_retentions": round(float(np.mean(ll_ret)), 4) if ll_ret else None,
        "n_lots": len(ll_lot),
        "n_retentions": len(ll_ret),
        "retentions_median_model_over_paid": round(float(np.median(ratio)), 3) if ratio else None,
        "retentions_share_at_or_above_paid": (
            round(float(np.mean(np.array(ratio) >= 1.0)), 3) if ratio else None
        ),
    }


def _loao_upto(kind, rows, names, last, mode=None) -> dict:
    """Leave one auction out over 2019..`last`, using only auctions up to `last`."""
    rows = [r for r in rows if r["season"] <= last]
    preds, tests = [], []
    for s in sorted({r["season"] for r in rows}):
        if s < 2019:
            continue
        te = [r for r in rows if r["season"] == s and not r.get("retained")]
        if not te:
            continue
        m, part = _recipe(
            kind, [r for r in rows if r["season"] != s], names, mode or _FORM["cal"], CAL_GROUPS
        )
        preds.append(_recipe_pred(m, part, te, names))
        tests += te
    return _scored(np.concatenate(preds), tests)


def _logit_loao(rows: list[dict], names: list[str], c: float) -> float:
    from sklearn.metrics import log_loss

    lls = []
    for s in sorted({r["season"] for r in rows}):
        a_ = [r for r in rows if r["season"] != s]
        b_ = [r for r in rows if r["season"] == s]
        lm = _fit_logit(_matrix(a_, names), np.array([r["bought"] for r in a_]), c)
        pb = lm.predict_proba(_matrix(b_, names))[:, 1]
        lls.append(log_loss([r["bought"] for r in b_], np.clip(pb, 1e-6, 1 - 1e-6), labels=[0, 1]))
    return float(np.mean(lls))


def _brief(m: dict) -> dict:
    keys = ("n", "mae_ln", "median_abs_pct", "within_50pct", "spearman", "bias_ln",
            "median_bias_ln", "top10_ratio", "top_pre_ratio")  # fmt: skip
    out = {k: m.get(k) for k in keys}
    for g in ("2025", "2026", "2023", "2024", *[c["name"] for c in CAL_GROUPS], "overseas"):
        if g in m:
            out[g] = {k: m[g].get(k) for k in ("n", "mae_ln", "bias_ln", "median_bias_ln")}
    return out


@app.command()
def fit(
    first: int = typer.Option(
        2018, "--first", help="First auction season to train on (2018: the shipped fit)."
    ),
    out: Path = typer.Option(MODEL_PATH, "--out"),
    refresh_caps: bool = typer.Option(False, "--refresh-caps"),
    report: Path | None = typer.Option(None, "--report", help="Write the full evaluation here."),
    only: str = typer.Option(
        "", "--only", help="Comma-separated candidate letters to evaluate (default: all)."
    ),
) -> None:
    """Choose the recipe on auctions up to 2024, score it once on 2025-26, refit on everything and
    export to config/price_model.json."""
    AUCTIONS_DATES.update(auction_dates())
    missing = [s for s in range(max(first, 2009), 2027) if not ipl_fit_path(s).exists()]
    if missing:
        raise typer.BadParameter(f"IPL fits missing for {missing}: run `fits` first")
    price_rows, risk_rows, hist, ret_rows = build_rows(refresh_caps)
    cands = {k: v for k, v in CANDIDATES.items() if not only or k.split()[0] in only.split(",")}
    ev: dict = {"protocol": {
        "selection": f"leave one auction out over 2019-{SELECT_LAST}, auctions <= {SELECT_LAST} "
                     "only; lowest mean absolute ln error on the lots wins",
        "validation": f"fitted <= {VALID_TRAIN_LAST}, scored on 2023 + 2024",
        "test": "fitted <= 2024, scored on 2025 mega + 2026 mini, once, for the chosen recipe "
                "(and the previous one, for reference)",
    }, "selection": {}}  # fmt: skip

    # ---- 1. selection, on auctions up to 2024 only
    for label, spec in cands.items():
        names, kind = spec[0], spec[1]
        rows = _rows_for(price_rows, ret_rows, first, spec)
        sel = [r for r in rows if r["season"] <= SELECT_LAST]
        _use_form(spec, sel)
        lo = _loao_upto(kind, sel, names, SELECT_LAST)
        vtr = [r for r in sel if r["season"] <= VALID_TRAIN_LAST]
        vte = [r for r in sel if r["season"] > VALID_TRAIN_LAST and not r.get("retained")]
        va = _evaluate_on(kind, names, vtr, vte)
        # the held-out log-likelihood needs every mega retention as a censored row, whatever the
        # candidate trains on
        ll = _heldout_loglik(kind, sel, names, SELECT_LAST)
        ev["selection"][label] = {
            "loglik_le_2024": ll, "loao_le_2024": _brief(lo), "validation_2023_24": _brief(va)
        }  # fmt: skip
        logger.info(
            f"{label}: LL/obs {ll['loglik_per_obs']} (lots {ll['loglik_lots']}, retentions "
            f"{ll['loglik_retentions']}, ret >= paid {ll['retentions_share_at_or_above_paid']}) | "
            f"LOAO<=2024 MAE {lo['mae_ln']} top20 {lo['top_pre_ratio']} | "
            f"valid 2023-24 MAE {va['mae_ln']} top20 {va['top_pre_ratio']}"
        )
    # The declared rule (the protocol text above): the lowest leave-one-auction-out mean absolute ln
    # error on the lots. Until 2026-10-22 (top-end rework) the code chose by the held-out
    # log-likelihood instead, which counts each mega retention as P(price >= what he was kept at): a
    # floor can't penalise a price far above it, so that score rewarded recipes that priced the
    # stars franchises kept at several times their retention (Gill ~90 cr). It is still reported.
    chosen = min(cands, key=lambda k: ev["selection"][k]["loao_le_2024"]["mae_ln"])
    ev["chosen"] = chosen
    logger.info(f"chosen: {chosen}")
    names, kind = cands[chosen][0], cands[chosen][1]
    rows = _rows_for(price_rows, ret_rows, first, cands[chosen])

    # ---- 2. the test, once: fitted <= 2024, scored on 2025 + 2026; and walking forward to 2026
    ev["test"] = {}
    ref = next(iter(CANDIDATES))
    for label in dict.fromkeys([chosen, ref]):
        if label not in cands:
            continue
        spec = cands[label]
        rr = _rows_for(price_rows, ret_rows, first, spec)
        tr = [r for r in rr if r["season"] <= SELECT_LAST]
        te = [r for r in rr if r["season"] in TEST_SEASONS and not r.get("retained")]
        _use_form(spec, tr)
        t = _brief(_evaluate_on(spec[1], spec[0], tr, te))
        tr26 = [r for r in rr if r["season"] < 2026]
        te26 = [r for r in rr if r["season"] == 2026 and not r.get("retained")]
        _use_form(spec, tr26)
        t["walk_forward_2026"] = _brief(_evaluate_on(spec[1], spec[0], tr26, te26))
        ev["test"][label] = t

    # ---- 3. P(bought): C by leave one auction out, features chosen the same way, tested once
    rtr = [r for r in risk_rows if r["season"] <= SELECT_LAST]
    rte = [r for r in risk_rows if r["season"] in TEST_SEASONS]
    ev["bought_selection"] = {}
    best_b = (math.inf, None, None)
    for bl, bn in BOUGHT_CANDIDATES.items():
        for c in (0.03, 0.1, 0.3, 1.0, 3.0):
            ll = _logit_loao(rtr, bn, c)
            if ll < best_b[0]:
                best_b = (ll, bl, c)
            ev["bought_selection"][f"{bl}, C={c}"] = round(ll, 4)
    _, b_label, best_c = best_b
    bnames = BOUGHT_CANDIDATES[b_label]
    lm = _fit_logit(_matrix(rtr, bnames), np.array([r["bought"] for r in rtr]), best_c)
    pb = lm.predict_proba(_matrix(rte, bnames))[:, 1]
    yb = np.array([r["bought"] for r in rte], dtype=float)
    ev["bought"] = {"chosen": b_label, "C": best_c, "test": _logit_metrics(pb, yb)}

    # ---- 4. the shipped model: the chosen recipe refitted on every season from `first`
    _use_form(cands[chosen], rows)
    alpha_all = _choose_alpha(kind, rows, names)
    y_all = np.array([r["y"] for r in rows])
    m_all = _fit_reg(kind, _matrix(rows, names), y_all, alpha_all, _cens(rows))
    # the calibration on the out-of-fold predictions; its resid_sd (a lot's spread around his
    # calibrated prediction, out of fold) sets `high`
    cal_all = _calibration_for(kind, rows, alpha_all, names, _FORM["cal"], CAL_GROUPS)
    icpt, coef = _raw_coef(m_all, names)
    lm_all = _fit_logit(
        _matrix(risk_rows, bnames), np.array([r["bought"] for r in risk_rows]), best_c
    )
    bi, bc = _raw_coef(lm_all, bnames)
    link = _link(m_all)
    pv_max = _FORM["pv_max"]
    rets = [
        r for r in ret_rows if r["season"] in (2018, 2022, 2025) and r["retention_kind"] == "mega"
    ]
    ev["mega_retentions"] = _retention_check(
        rets, {"intercept": icpt, "coef": coef, "link": link, "pv_max": pv_max, **cal_all}
    )

    seasons = sorted({r["season"] for r in rows})
    n_ret = sum(1 for r in rows if r.get("retained"))
    model = {
        "schema": 1,
        "league": "ipl",
        "fitted": dt.date.today().isoformat(),
        "method": (
            f"hurdle: P(bought) logistic (L2, C={best_c}, features: {b_label}); ln(price / purse "
            f"| bought) {kind} regression (alpha={alpha_all}, standardised features, refolded to raw "
            f"units; recipe '{chosen.split(maxsplit=1)[1]}', chosen by leave one auction out on "
            f"auctions <= {SELECT_LAST}); calibration {_FORM['cal']} on out-of-fold predictions "
            "(groups: " + ", ".join(g["name"] for g in CAL_GROUPS) + ")"
        ),
        "trained_on": {
            "seasons": [seasons[0], seasons[-1]],
            "price_rows": len(rows),
            "lots": len(rows) - n_ret,
            "retention_rows": n_ret,
            "censored_rows": int(_cens(rows).sum()),
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
            # how the linear index becomes the median ln share (pricing.link_share)
            "link": link,
            # the priced value is held to the largest in the training rows (None: no hold)
            **({"pv_max": pv_max} if pv_max is not None else {}),
            # calibration (pricing.calibrate): knots (none shipped) + each group's shift, out of fold
            **cal_all,
            "calibration_mode": _FORM["cal"],
            "resid_sd": round(float(cal_all["resid_sd"]), 4),
        },
        "bought": {"intercept": bi, "coef": bc},
        "evaluation": {
            "protocol": ev["protocol"],
            "chosen": chosen,
            "selection": ev["selection"],
            "test": ev["test"],
            "bought": ev["bought"],
        },
    }  # fmt: skip
    out.write_text(json.dumps(model, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    pricing.load_price_model.cache_clear()
    if report:
        report.write_text(json.dumps(ev, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: ev[k] for k in ("chosen", "test", "bought")}, indent=1))
    print(json.dumps(ev["mega_retentions"], indent=1))
    print(
        f"wrote {out}: {len(rows)} price rows ({n_ret} retentions), {len(risk_rows)} risk-set rows"
    )


def _next_competition() -> dict:
    from cricdex import competitions

    comps = [c for c in competitions.load().values() if c.league == "ipl"]
    c = max(comps, key=lambda c: (c.season, c.auction_date))
    return {"cycle": c.cycle, "purse": float(c.purse), "key": c.key}


def _retention_check(rets: list[dict], part: dict) -> dict:
    """The mega-year retentions (rows from `build_rows`, features as of their auction): the model's
    price for each retained player against what he was paid."""
    ratios = []
    for r in rets:
        f = pricing.market_features(_valued(r), "mega", part.get("pv_max"))
        share = math.exp(
            pricing.calibrate(
                pricing.calibration_part(part, f),
                pricing.link_share(part, pricing._linear(part, f)),
            )
        )
        ratios.append(share * r["purse"] / r["price_cr"])
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
