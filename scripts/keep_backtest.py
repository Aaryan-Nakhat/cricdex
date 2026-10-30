"""Keep or release, backtested on what franchises really did (docs/METHODOLOGY.md §10).

Every retention deadline with a complete published retained list (2018-2026: the 2018, 2022 and 2025
mega auctions and the mini auctions in between) is replayed with only what was known before it:

* the squad each franchise held before the deadline: every player whose latest signing since the
  cycle's mega auction (a retention, an auction buy, or a match played for it) was its and whom it
  retained at every deadline since (`_owners`; 2018, with no retained list before it, from the season
  before); a player another franchise lists as retained was traded and is left out, as is one whose
  retirement was announced on or before the deadline (data/curated/ipl_availability.json);
* each player's market price from the price model fitted on the earlier auctions only (the shipped
  recipe, `ipl_price_model.fit_price_part`), his value, captaincy, caps and age as of the retention
  deadline (`RETENTION_DEADLINES`; `ipl_price_model.feature_fn`), his first IPL side from the seasons
  before it, and his three-season Form forecast built from the seasons up to the deadline
  (`scout/forecast.build_forecast` on the walk-forward ratings);
* what keeping him cost the purse: his contract salary in a mini year, the cycle's retention slab in a
  mega year (in order: 2018 15 / 11 / 7 cr capped, 3 cr uncapped; 2022 16 / 12 / 8 / 6, 4; 2025
  18 / 14 / 11 / 18 / 14, 4), and in 2026 the 2025 slab holders at the slab they free
  (web_parity/keep.retention_costs).

The label is the published retained list. Candidate rules (declared before any test number) are
chosen by leave-one-season-out on the deadlines up to 2024 and scored once on 2025 + 2026.

A published retention with no row is listed with its reason in `<work>/excluded_<key>.json`
(traded, a retirement, or not in the squad data: a replacement signing who never played). The caches
are keyed on a hash of their inputs (`_rows_key`, `_market_key`), and the output carries the git
commit and those keys.

    uv run python scripts/keep_backtest.py rows --work <dir>      # build the rows (resumable, cached)
    uv run python scripts/keep_backtest.py score --work <dir> [--out data/metrics/keep_backtest_ipl.json]
"""

from __future__ import annotations

import json
import math
import pickle
import sys
from pathlib import Path

import numpy as np
import polars as pl
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ipl_price_model as ipm  # noqa: E402

from cricdex.config import DATA_DIR  # noqa: E402
from cricdex.scout import forecast as fc  # noqa: E402
from cricdex.scout.identity import captains, master  # noqa: E402
from cricdex.scout.ratings import bayesian  # noqa: E402
from cricdex.web_parity import keep as kp  # noqa: E402
from cricdex.web_parity import pricing  # noqa: E402

app = typer.Typer(add_completion=False)

SEASONS = (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)
SELECT_LAST = 2024
TEST = (2025, 2026)
OUT = DATA_DIR / "metrics" / "keep_backtest_ipl.json"
MODEL_OUT = Path(__file__).resolve().parents[1] / "config" / "keep_model.json"

# Mega-auction retention rules (purse deduction per retained player, in retention order). Sources:
# 2018 - IPL Governing Council, 6 Dec 2017 (ESPNcricinfo "IPL 2018: franchises can retain up to five
# players", three by retention at 15 / 11 / 7 cr, an uncapped player 3 cr); 2022 - IPL retention rules,
# Nov 2021 (ESPNcricinfo "IPL 2022 retention: what you need to know": four at 16 / 12 / 8 / 6 cr, an
# uncapped player 4 cr, at most three Indians and two overseas); 2025 - IPL Player Regulations
# 2025-27, 28 Sep 2024 (BCCI media release: six retentions or RTMs, capped 18 / 14 / 11 / 18 / 14 cr,
# uncapped 4 cr, at most five capped and two uncapped).
MEGA_RULES = {
    2018: {"capped": [15.0, 11.0, 7.0], "uncapped": 3.0, "max": 3, "max_uncapped": 2},
    2022: {"capped": [16.0, 12.0, 8.0, 6.0], "uncapped": 4.0, "max": 4, "max_uncapped": 2},
    2025: {"capped": [18.0, 14.0, 11.0, 18.0, 14.0], "uncapped": 4.0, "max": 6, "max_uncapped": 2},
}
# The 2025-27 cycle charges the 2025 mega-auction retentions by slab while they stay (keep.py)
SLAB_RULES_2025 = {
    "retained_cost": "slabs",
    "retention_slabs": MEGA_RULES[2025]["capped"],
    "uncapped_retention_slab": MEGA_RULES[2025]["uncapped"],
}
# The squads a deadline's franchises held: the season before, except the two sides suspended in 2016-17
PREV_SEASON = {(2018, "CSK"): 2015, (2018, "RR"): 2015}
# The retention deadline before each season's auction: every as-of feature is taken on it (until
# 2026-10-29 they were taken on the auction date, 3-10 weeks later: 79 players gained caps between the
# 2024 deadline and the 2025 auction). Sources: 2018 IPL GC (iplt20.com "VIVO IPL 2018 Player
# Retention announced", 4 Jan 2018); 2019 trading window and lists, 15 Nov 2018 (The Quint, Cricket
# Times); 2020 lists published 15 Nov 2019, the window closing on the 14th (Wisden, India TV); 2021
# 20 Jan 2021 (Wisden; Wikipedia "List of 2021 IPL personnel changes"); 2022 30 Nov 2021 (Wikipedia
# "List of 2022 IPL personnel changes"); 2023 15 Nov 2022 (Scroll, Wisden); 2024 26 Nov 2023
# (Business Today, Wisden); 2025 31 Oct 2024 (iplt20.com "TATA IPL 2025 player retentions list
# announced"); 2026 15 Nov 2025 (iplt20.com "TATA IPL 2026 Player Retentions Announced").
RETENTION_DEADLINES = {
    2018: "2018-01-04", 2019: "2018-11-15", 2020: "2019-11-15", 2021: "2021-01-20",
    2022: "2021-11-30", 2023: "2022-11-15", 2024: "2023-11-26", 2025: "2024-10-31",
    2026: "2025-11-15",
}  # fmt: skip
AVAILABILITY = DATA_DIR / "curated" / "ipl_availability.json"
ROOT = Path(__file__).resolve().parents[1]


def _sha(*parts: Path | str) -> str:
    """sha256 (first 12 hex) of files (their bytes, CRLF folded) and strings."""
    import hashlib

    h = hashlib.sha256()
    for x in parts:
        if isinstance(x, Path):
            h.update(x.name.encode())
            h.update(x.read_bytes().replace(b"\r\n", b"\n") if x.exists() else b"<missing>")
        else:
            h.update(str(x).encode())
    return h.hexdigest()[:12]


def _rows_key() -> str:
    """What the rows are built from: the auction history, squads, retirements, the player master, the
    captaincy record, the rating model's version (its walk-forward fits are cached under it), the
    league translation, time-aware drift and playing-time models, the as-of contributions (size and
    time: a large file) and the code that builds them."""
    cfg = ROOT / "config"
    ac = ipm.ASOF_CONTRIB
    ac_stamp = f"{ac.stat().st_size}:{int(ac.stat().st_mtime)}" if ac.exists() else "none"
    return _sha(
        ipm.HISTORY, DATA_DIR / "curated" / "ipl_squads_2026.json", AVAILABILITY, master.MASTER_PATH,
        captains.CAPTAINS, Path(captains.__file__), bayesian.MODEL_VERSION,
        cfg / "league_translation.json", cfg / "rating_drift.json", cfg / "value_shrink.json",
        cfg / "playing_time_model.json", ac_stamp, Path(__file__), Path(ipm.__file__),
    )  # fmt: skip


def _market_key(rows_key: str) -> str:
    """What the market prices are computed from: the rows, the shipped price model and its code."""
    return _sha(
        rows_key, ROOT / "config" / "price_model.json", Path(ipm.__file__), Path(pricing.__file__)
    )


def _git_sha() -> str | None:
    import subprocess

    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return None
    return out.stdout.strip() or None


def _retired_by(deadline: str) -> set[str]:
    """cids whose retirement (the reviewed availability file) was announced on or before `deadline`:
    left out of that deadline's squads. A retirement announced after it was a release at it."""
    av = json.loads(AVAILABILITY.read_text(encoding="utf-8")) if AVAILABILITY.exists() else {}
    return {cid for cid, v in av.items() if isinstance(v, dict) and v.get("status") == "retired"
            and v.get("date") and v["date"] <= deadline}  # fmt: skip


def _played() -> tuple[dict, dict]:
    """((season, team) → cids who played for it; cid → [(season, team)] in order)."""
    import duckdb

    from cricdex.scout.identity import sources

    with duckdb.connect(str(bayesian.DEFAULT_DB_PATH), read_only=True) as con:
        hist = sources.ipl_team_seasons(con)
    by: dict[tuple[int, str], set[str]] = {}
    for cid, v in hist.items():
        for y, code in v:
            by.setdefault((y, code), set()).add(cid)
    return by, hist


def _forecasts(work: Path, origin: int) -> dict:
    """The Form forecast as it stood at the end of season `origin` (ratings and seasons up to it)."""
    # keyed by the rating model's version: the walk-forward fits it reads are
    f = work / f"forecast_{origin}_{bayesian.MODEL_VERSION}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    import form_forecast as ff

    history = ff._history(False, 2026)
    history = history.filter(pl.col("season") <= origin)
    ratings = {t: pl.read_parquet(ipm.ipl_fit_path(t + 1)) for t in range(2008, origin + 1)}
    payload = fc.build_forecast(ratings, history, ff._dobs(), origin)
    f.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _outlook(fcst: dict, cid: str, role: str) -> dict | None:
    """keep_outlook's pick for this player (batting for batters / keepers, bowling for bowlers, the
    better three-season average for an all-rounder)."""
    o = fc.keep_outlook(fcst, cid, role)
    return o


@app.command()
def rows(work: Path = typer.Option(..., "--work")) -> None:
    """Build one row per (deadline, franchise, squad player) with the inputs and the label."""
    work.mkdir(parents=True, exist_ok=True)
    key = _rows_key()
    out_f = work / f"rows_{key}.pkl"
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    features_in, hist, apps = ipm.feature_fn()
    played, team_hist = _played()
    pm = master.load()
    sq = json.loads((DATA_DIR / "curated" / "ipl_squads_2026.json").read_text(encoding="utf-8"))
    mega25 = (sq.get("mega_retentions_2025") or {}).get("teams") or {}
    # the 2025 slab holders by id: the published 2025 retained list (the same Wikipedia names)
    ret25 = {(r["team"], r["name"]): r["cricsheet_id"] for r in hist["retentions"]
             if r["season"] == 2025 and r["kind"] == "retained" and r.get("cricsheet_id")}  # fmt: skip
    # every deadline's published retained list: cid -> franchise
    kept_at: dict[int, dict[str, str]] = {}
    for r in hist["retentions"]:
        if r["season"] in SEASONS and r["kind"] == "retained" and r.get("cricsheet_id"):
            kept_at.setdefault(r["season"], {})[r["cricsheet_id"]] = r["team"]
    done: dict = pickle.loads(out_f.read_bytes()) if out_f.exists() else {}
    ex_f = work / f"excluded_{key}.json"
    excluded: dict = json.loads(ex_f.read_text(encoding="utf-8")) if ex_f.exists() else {}
    for s in SEASONS:
        if s in done:
            typer.echo(f"{s}: cached ({len(done[s])} rows)")
            continue
        a = hist["auctions"][str(s)]
        date, purse, cycle = RETENTION_DEADLINES[s], float(a["purse_cr"]), a["kind"]
        retired = _retired_by(date)
        fcst = _forecasts(work, s - 1)
        vals = ipm.asof_values(s, date)
        kept: dict[str, str] = {}
        for r in hist["retentions"]:
            if r["season"] == s and r["kind"] == "retained" and r.get("cricsheet_id"):
                kept[r["cricsheet_id"]] = r["team"]
        # the franchises of season s that held a squad before it (2022's two new sides had none)
        teams = sorted({r["team"] for r in hist["lots"] if r["season"] == s and r.get("sold")}
                       & {t for (y, t) in played if y == PREV_SEASON.get((s, t), s - 1)})  # fmt: skip
        owner = _owners(s, teams, team_hist, hist, kept_at)
        out = []
        why_not: dict[str, str] = {}
        for team in teams:
            prev = PREV_SEASON.get((s, team), s - 1)
            for cid in sorted(c for c, t in owner.items() if t == team):
                if cid in kept and kept[cid] != team and kept[cid] in teams:
                    why_not[cid] = f"traded: {team} to {kept[cid]}"
                    continue  # traded to another franchise before the deadline
                # (a pick of a new franchise's draft, 2022, was released by this one: kept = False)
                rec = pm.get(cid) if isinstance(pm.get(cid), dict) else {}
                if cid in retired:
                    why_not[cid] = "retirement announced by the deadline"
                    continue
                f = features_in(cid, s, date, vals, None)
                # his contract salary: the latest price paid for him (auction or retention) before s
                lots_prev = [r for r in hist["lots"] if r.get("cricsheet_id") == cid
                             and r.get("sold") and r["season"] < s]  # fmt: skip
                rets_prev = [r for r in hist["retentions"] if r.get("cricsheet_id") == cid
                             and r["season"] < s and r.get("salary_cr")]  # fmt: skip
                paid = [(r["season"], float(r["price_cr"])) for r in lots_prev if r.get("price_cr")]
                paid += [(r["season"], float(r["salary_cr"])) for r in rets_prev]
                salary = max(paid)[1] if paid else None
                bought_prev = any(r["season"] == prev and r["team"] == team for r in lots_prev)
                seasons_here = sorted({y for y, t in team_hist.get(cid, []) if t == team and y < s})
                # his first IPL side among the seasons before the deadline only (until 2026-10-29 the
                # whole history: a squad player with no match yet got the side he played for later)
                before = [t for y, t in team_hist.get(cid, []) if y < s]
                first_team = before[0] if before else None
                o = _outlook(fcst, cid, f["role"])
                cap = captains.as_of(cid, s)
                out.append({
                    **f, "team": team, "season": s, "cycle": cycle, "purse": purse,
                    "name": rec.get("display_name") or cid,
                    "kept": kept.get(cid) == team, "salary": salary, "salary_known": salary is not None,
                    "bought_prev": bought_prev, "seasons_here": len(seasons_here),
                    "home_grown": first_team == team,
                    "captain_here": team in (cap.get("captain_teams") or []),
                    "forecast_avg3": o["avg3"] if o else None,
                    "forecast_p_regular": o["p_regular_last"] if o else None,
                    "forecast_median": o["median"] if o else None,
                    "slab_holder_2025": None,
                })  # fmt: skip
        # 2026: the 2025 mega retentions still at their franchise are charged by slab (matched by
        # id: by display name Abhishek Porel was missed)
        if s == 2026:
            for team, block in mega25.items():
                for kind in ("capped", "uncapped"):
                    for name in block.get(kind, []):
                        cid = ret25.get((team, name))
                        if cid is None:
                            raise ValueError(f"2025 slab holder {name} ({team}) has no id")
                        for r in out:
                            if r["team"] == team and r["cricsheet_id"] == cid:
                                r["slab_holder_2025"] = kind
        # every published retention is a row, or listed with the reason it isn't
        rowed = {(r["team"], r["cricsheet_id"]) for r in out}
        excluded[str(s)] = [
            {"team": t, "cricsheet_id": c,
             "name": (pm.get(c) or {}).get("display_name") if isinstance(pm.get(c), dict) else c,
             "reason": why_not.get(c) or (
                 f"in the {owner[c]} squad data, not {t}'s" if c in owner
                 else "not in the squad data: no signing on record and no match the season before "
                 "(a replacement signing who didn't play; in 2018 a player who missed 2017)")}
            for c, t in sorted(kept.items()) if (t, c) not in rowed and t in teams
        ]  # fmt: skip
        ids = [r["cricsheet_id"] for r in out]
        if len(ids) != len(set(ids)):
            raise ValueError(
                f"{s}: players in two squads: {sorted({c for c in ids if ids.count(c) > 1})[:5]}"
            )
        done[s] = out
        out_f.write_bytes(pickle.dumps(done))
        ex_f.write_text(json.dumps(excluded, indent=1, ensure_ascii=False), encoding="utf-8")
        n_kept = sum(r["kept"] for r in out)
        typer.echo(f"{s}: {len(out)} squad players, {n_kept} kept, {len(teams)} teams, "
                   f"{len(excluded[str(s)])} retentions without a row")  # fmt: skip
    typer.echo(f"done: {out_f.name}")


def _owners(
    s: int, teams: list[str], team_hist: dict, hist: dict, kept_at: dict[int, dict[str, str]]
) -> dict[str, str]:
    """cid -> the franchise that held his contract before deadline `s`.

    His signings since the cycle's mega auction (a retention, an auction buy, or a match played for a
    side: a replacement signing), by franchises still in the league (Rising Pune and Gujarat Lions
    left in 2018): the latest one is his franchise, if it retained him at every deadline since (the
    published retained lists; one it didn't retain released him). The first deadline, 2018, has no
    retained list before it: its squads are the season before (2015 for CSK and RR, back from their
    suspension), so a contracted player who missed that season isn't seen (Andre Russell, banned in
    2017). A replacement signing who never played is never seen (listed in `excluded_<key>.json`)."""
    live = set(teams)
    events: dict[str, list[tuple[int, int, str]]] = {}
    for r in hist["retentions"]:
        if r["kind"] == "retained" and r.get("cricsheet_id"):
            events.setdefault(r["cricsheet_id"], []).append((r["season"], 0, r["team"]))
    for r in hist["lots"]:
        if r.get("sold") and r.get("cricsheet_id"):
            events.setdefault(r["cricsheet_id"], []).append((r["season"], 1, r["team"]))
    for cid, seasons in team_hist.items():
        for y, t in seasons:
            events.setdefault(cid, []).append((y, 2, t))
    if s == SEASONS[0]:
        window = {t: (PREV_SEASON.get((s, t), s - 1),) * 2 for t in teams}
    else:
        mega = max(m for m in MEGA_RULES if m < s)
        window = dict.fromkeys(teams, (mega, s - 1))
    owner: dict[str, str] = {}
    for cid, ev in events.items():
        ev = sorted(e for e in ev if e[2] in live and window[e[2]][0] <= e[0] <= window[e[2]][1])
        if not ev:
            continue
        last, _, team = ev[-1]
        # under contract from his last signing or match (a released player re-bought at the next
        # auction, Saha 2019, signs again): every deadline after it must have retained him
        if all(kept_at.get(d, {}).get(cid) == team for d in SEASONS if last < d < s):
            owner[cid] = team
    return owner


# ---- scoring ---------------------------------------------------------------------------------------


def _market(work: Path, data: dict, letter: str | None) -> dict:
    """(season, team, cid) → (market price, the upper quartile on his central value) from the price
    recipe (`letter`, else the shipped one) fitted on the auctions before each deadline only."""
    spec_name = letter or "shipped"
    f = work / f"market_{spec_name}_{_market_key(_rows_key())}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    price_rows, _risk, hist, ret_rows = ipm.build_rows()
    spec = (
        ipm.shipped_spec()
        if not letter
        else next(v for k, v in ipm.CANDIDATES.items() if k.split()[0] == letter)
    )
    # the shipped resale rule (ipl_price_model.py resale), refitted on the resold lots before each
    # deadline only
    rs = ((pricing.load_price_model() or {}).get("price") or {}).get("resale")
    lots = ipm.resale_lots(price_rows, ret_rows, spec) if rs and not letter else []
    out: dict = {}
    for s, rows in data.items():
        a = hist["auctions"][str(s)]
        model = {
            "floor_cr": 0.2 if s < 2025 else 0.3,
            "competition": {"cycle": a["kind"], "purse": float(a["purse_cr"])},
            # 2018 and 2019 have too few auctions since 2018 to fit on: 2011 on for those two
            "price": ipm.fit_price_part(price_rows, ret_rows, spec, 2018 if s > 2019 else 2011, s),
            "bought": (pricing.load_price_model() or {}).get("bought"),
        }
        before = [r for r in lots if r["season"] < s and r["prior_share"]
                  and r["prior_years"] is not None and r["prior_years"] <= rs["max_years"]]  # fmt: skip
        if len(before) >= RESALE_MIN_LOTS:
            model["price"]["resale"] = {"max_years": rs["max_years"],
                                        **ipm.resale_coefs(ipm._resale_fit(before, rs.get("rule", "R1")))}  # fmt: skip
        for r in rows:
            # the row as the recipe prices it (its value input: ipl_price_model._valued)
            rv = ipm._valued(r)
            mk = pricing.market_price(rv, model["competition"], model)
            hi = pricing.market_price({**rv, "value_sd": 0.0}, model["competition"], model)["high"]
            out[(s, r["team"], r["cricsheet_id"])] = (mk["price"], hi)
        typer.echo(f"market {s}: {len(rows)} priced")
    f.write_bytes(pickle.dumps(out))
    return out


def _capped(r: dict) -> bool:
    return (r.get("intl_caps") or 0) > 0


def _costs(rows: list[dict], s: int) -> None:
    """Each row's `cost`: what keeping him cost the purse. Mini: his salary (the lowest base price
    when unknown), and in 2026 the 2025 slab holders at the slab their release frees. Mega: the slab
    of his position, the team's players taken in market-price order (capped and uncapped slabs
    apart). Past the last slab he costs the cycle's dearest slab (he can only take a place someone
    else holds) and stays eligible: until 2026-10-30 he cost None and his P(keep) was forced to 0,
    16 of 2025's 46 real retentions among them (METHODOLOGY §10)."""
    floor = 0.2 if s < 2025 else 0.3
    if s in MEGA_RULES:
        rule = MEGA_RULES[s]
        by_team: dict[str, list[dict]] = {}
        for r in rows:
            by_team.setdefault(r["team"], []).append(r)
        for team_rows in by_team.values():
            kc = ku = 0
            for r in sorted(team_rows, key=lambda x: -x["market"]):
                if _capped(r):
                    caps = rule["capped"]
                    r["cost"] = caps[kc] if kc < len(caps) else max(caps)
                    kc += 1
                else:
                    r["cost"] = rule["uncapped"]
                    ku += 1
        return
    for r in rows:
        r["cost"] = float(r["salary"]) if r.get("salary") else floor
    if s == 2026:
        by_team = {}
        for r in rows:
            by_team.setdefault(r["team"], []).append(r)
        for team, team_rows in by_team.items():
            sq = [{"id": r["cricsheet_id"], "team": team, "name": r["name"], "salary": r["cost"],
                   "slab_holder": r.get("slab_holder_2025")} for r in team_rows]  # fmt: skip
            c = kp.retention_costs(sq, SLAB_RULES_2025)
            for r, q in zip(team_rows, sq, strict=True):
                r["cost"] = c[kp.player_key(q)]


def _feats(r: dict) -> dict[str, float]:
    """The candidate inputs of one row (all known before the deadline): web_parity/keep.py
    `keep_features`, the same function the page and the CLI use."""
    return kp.keep_features(
        r["market"], r["cost"] or 0.0, r["cycle"] == "mega", r.get("forecast_avg3"),
        r.get("forecast_p_regular"), bool(r.get("captain_here")), int(r.get("seasons_here") or 0),
        bool(r.get("home_grown")), _capped(r) and not r.get("is_overseas"),
        bool(r.get("is_overseas")), r.get("age"), r.get("ipl_balls"), bool(r.get("bought_prev")),
        r.get("p_play"), r.get("contrib"), bool(r.get("mega_retained")), r.get("matches_last"),
    )  # fmt: skip


def _mega_retained(data: dict) -> None:
    """Each mini-year row's `mega_retained`: his franchise retained him at the cycle's mega auction
    (2018 for 2019-21, 2022 for 2023-24, 2025 for 2026), from the published retained lists. In place."""
    hist = json.loads(ipm.HISTORY.read_text(encoding="utf-8"))
    megas = sorted(MEGA_RULES)
    ret = {(r["season"], r["cricsheet_id"]): r["team"] for r in hist["retentions"]
           if r["season"] in MEGA_RULES and r["kind"] == "retained" and r.get("cricsheet_id")}  # fmt: skip
    for s, rows in data.items():
        last = max((m for m in megas if m < s), default=None)
        for r in rows:
            r["mega_retained"] = (
                s not in MEGA_RULES and last is not None
                and ret.get((last, r["cricsheet_id"])) == r["team"]
            )  # fmt: skip


def _playing_time(data: dict) -> None:
    """Each row's playing time before the deadline (METHODOLOGY §6c): his contribution per match as
    of the auction (`playing_time_fit.py asof-contrib`) and P(plays a match) in the squad his
    franchise held before the deadline, from the squad model (playing_time_fit `play`) fitted
    out of fold: for a deadline up to 2024 on the other seasons up to 2024, for 2025-26 on
    2018-2024 (the model of the test), and his IPL matches the season before. In place: `contrib`,
    `p_play`, `matches_last`."""
    import playing_time_fit as ptf

    from cricdex.scout import playing_time as pt

    rep_ = ptf._read()
    feats = ptf.PLAY_CANDIDATES[rep_["play"]["chosen"]]
    alpha = rep_["play"]["alpha"]
    prows = ptf._all_play_rows(bool(rep_["play"].get("xi_by_era")))
    contrib = {(s_, c): v for (s_, c), v in ipm._asof_contrib().items()}
    u = ptf._u()
    _team_m, played_m, share = ptf.ipl_shares(u)
    # his IPL matches the season before the deadline, for any side (keep.json's matches_last)
    m_season: dict[tuple[int, str], int] = {}
    for (y, _code, cid), n in played_m.items():
        m_season[(y, cid)] = m_season.get((y, cid), 0) + n
    i = u.filter(pl.col("league") == "ipl")
    roles = ptf._roles()
    models: dict[int, pt.PlayModel] = {}
    for s in SEASONS:
        tr = [r for r in prows if r["season"] <= SELECT_LAST and r["season"] != s]
        models[s] = pt.fit_play_model(tr, feats, alpha)
    for s, rows in data.items():
        date = RETENTION_DEADLINES[s]
        ipl_m = dict(i.filter(pl.col("date") < date).group_by("cid").agg(pl.len()).iter_rows())
        by_team: dict[str, list[dict]] = {}
        for r in rows:
            by_team.setdefault(r["team"], []).append(r)
        for team_rows in by_team.values():
            squad = []
            for r in team_rows:
                prev = PREV_SEASON.get((s, r["team"]), s - 1)
                r["matches_last"] = m_season.get((prev, r["cricsheet_id"]), 0)
                c = contrib.get((s, r["cricsheet_id"]))
                r["contrib"] = c[0] if c else None
                squad.append(pt.squad_member(r["cricsheet_id"], c[0] if c else 0.0,
                                             r["role"], bool(r.get("is_overseas"))))  # fmt: skip
            xi = pt.projected_xi(squad, pt.xi_size(s, bool(rep_["play"].get("xi_by_era"))))
            for r in team_rows:
                cid = r["cricsheet_id"]
                x = xi[cid]
                meta = {
                    "contrib": squad[[q["cid"] for q in squad].index(cid)]["c"],
                    "in_xi": x["in_xi"], "margin": x["margin"], "rank": x["rank"],
                    "os_rank": x["os_rank"], "overseas": bool(r.get("is_overseas")),
                    "ipl_matches": ipl_m.get(cid, 0), "age": r.get("age"),
                    "last_share": share.get((s - 1, cid), 0.0),
                    "keeper": roles.get(cid) == "keeper",
                    "captain": bool(captains.as_of(cid, s).get("captain_ipl_last")),
                    "season": s,
                }  # fmt: skip
                r["p_play"] = models[s].prob(pt.play_features(meta))


# a deadline's resale rule needs this many resold lots before it (else the model's price alone)
RESALE_MIN_LOTS = 20


# Candidate rules, declared before any test number (2026-10-22). "rule": a threshold on one index;
# "logit": a logistic regression of the franchise's decision on the inputs.
BASE = ["log_ratio", "mega", "mega_x_log_ratio"]
FORECAST = ["forecast", "forecast_regular", "no_forecast"]
FRANCHISE = ["captain_here", "seasons_here", "home_grown"]
STATUS = ["capped_indian", "overseas", "age", "age_over_33", "ipl_balls", "bought_prev", "log_cost"]
# playing time (declared 2026-10-22 evening, audit items 4 and 6, before any of its numbers): P(plays a
# match) in his squad and P × his contribution per match (runs above replacement)
PLAY = ["p_play", "play_value", "no_play"]
# retained at the cycle's mega auction (declared 2026-10-29, before any of its numbers: the owner's
# reality check that Rohit Sharma, retained by MI in 2025, is no toss-up)
MEGA_RET = ["mega_retained"]
# played last season (declared 2026-10-30, before any of its numbers: METHODOLOGY §10; Dhoni, Dayal and
# Pathirana missed 2026)
PLAYED = ["played_last", "none_last"]
# reference only (not a candidate): keep everyone the rules allow
BASELINE = ("B0 keep everyone the rules allow", ("all", None))
CANDIDATES = {
    "C0 shipped rule (market vs cost, 0.5 cr / 15% margins, age 35)": ("current", None),
    "C1 market price vs cost, threshold fitted": ("rule", "log_ratio"),
    "C2 market price on the 3-season forecast vs cost, threshold fitted": ("rule", "log_ratio_fc"),
    "L1 logistic: market vs cost": ("logit", BASE),
    "L2 L1 + 3-season forecast": ("logit", BASE + FORECAST),
    "L3 L2 + franchise ties (captain, seasons there, home-grown)": ("logit", BASE + FORECAST + FRANCHISE),
    "L4 L3 + status (capped Indian, overseas, age, IPL balls, last auction's buy, cost)": (
        "logit", BASE + FORECAST + FRANCHISE + STATUS),
    "L5 L4 + playing time (P(plays) in his squad, P(plays) x contribution per match)": (
        "logit", BASE + FORECAST + FRANCHISE + STATUS + PLAY),
    "L6 L5 without the Form forecast": ("logit", BASE + FRANCHISE + STATUS + PLAY),
    "L7 L4 + retained at the cycle's mega auction": (
        "logit", BASE + FORECAST + FRANCHISE + STATUS + MEGA_RET),
    "L8 L7 + played last season": (
        "logit", BASE + FORECAST + FRANCHISE + STATUS + MEGA_RET + PLAYED),
}  # fmt: skip
# forward-chaining folds (K14, declared 2026-10-30): each deadline predicted by the deadlines before it
FOLDS = (2020, 2021, 2022, 2023, 2024)
RELIABILITY_BANDS = (0.0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0)
BOOT = 2000
C_GRID = (0.03, 0.1, 0.3, 1.0, 3.0)


def _current(r: dict) -> bool:
    """The shipped rule before 2026-10-22 (keep.py): Release when even the upper quartile on his
    central value is 0.5 cr / 15% below what he costs; everything else kept by default."""
    if r["cost"] is None:
        return False
    m = max(OLD_MARGIN_MIN, OLD_MARGIN_SHARE * r["cost"])
    return not (r["market_central"] - r["cost"] <= -m)


OLD_MARGIN_MIN, OLD_MARGIN_SHARE = 0.5, 0.15  # keep.py's KEEP_MARGIN_MIN / _SHARE until 2026-10-22


def _apply_caps(rows: list[dict], keep: list[bool], score: list[float]) -> list[bool]:
    """A mega deadline's retention limits: per team at most `max` players (`max_uncapped`
    uncapped), the highest scores first; a player past the last slab can't be kept."""
    out = list(keep)
    s = rows[0]["season"] if rows else 0
    if s not in MEGA_RULES:
        return out
    rule = MEGA_RULES[s]
    by_team: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_team.setdefault(r["team"], []).append(i)
    for idx in by_team.values():
        n = nu = 0
        for i in sorted(idx, key=lambda i: -score[i]):
            if not out[i]:
                continue
            if rows[i]["cost"] is None or n >= rule["max"]:
                out[i] = False
                continue
            if not _capped(rows[i]):
                if nu >= rule["max_uncapped"]:
                    out[i] = False
                    continue
                nu += 1
            n += 1
    return out


def _fit_rule(train: list[dict], key: str) -> float:
    """The threshold on `key` with the best F1 for 'kept' on `train`."""
    xs = sorted({round(r["_f"][key], 3) for r in train})
    best = (-1.0, 0.0)
    for t in xs:
        f1 = _prf([r["_f"][key] >= t for r in train], [r["kept"] for r in train])["f1"]
        if f1 > best[0]:
            best = (f1, t)
    return best[1]


def _fit_logit(train: list[dict], names: list[str], c: float):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X = np.array([[r["_f"][k] for k in names] for r in train])
    y = np.array([r["kept"] for r in train], dtype=int)
    return make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=5000)).fit(X, y)


def _logit_p(m, rows: list[dict], names: list[str]) -> np.ndarray:
    X = np.array([[r["_f"][k] for k in names] for r in rows])
    return m.predict_proba(X)[:, 1]


def _prf(pred: list[bool], y: list[bool]) -> dict:
    tp = sum(1 for p, t in zip(pred, y, strict=True) if p and t)
    fp = sum(1 for p, t in zip(pred, y, strict=True) if p and not t)
    fn = sum(1 for p, t in zip(pred, y, strict=True) if not p and t)
    tn = len(y) - tp - fp - fn
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    rel_ok = tn / (tn + fn) if tn + fn else 0.0  # of the players we release, the share released
    spec = tn / (tn + fp) if tn + fp else 0.0  # of the players released, the share we release
    return {"n": len(y), "kept": tp + fn, "called_keep": tp + fp, "precision": round(prec, 3),
            "recall": round(rec, 3), "f1": round(f1, 3), "release_precision": round(rel_ok, 3),
            "release_recall": round(spec, 3), "balanced_accuracy": round((rec + spec) / 2, 3),
            "accuracy": round((tp + tn) / len(y), 3) if y else 0.0}  # fmt: skip


def _tier(r: dict) -> str:
    """Star: what is at stake is at least 8% of the purse (10 cr at 125), on his cost or his market
    price; regular: 2-8%; depth: below."""
    x = max(r["cost"] or 0.0, r["market"]) / r["purse"]
    return "star" if x >= 0.08 else "regular" if x >= 0.02 else "depth"


def _report(rows: list[dict], pred: list[bool]) -> dict:
    out = {"all": _prf(pred, [r["kept"] for r in rows])}
    for t in ("star", "regular", "depth"):
        idx = [i for i, r in enumerate(rows) if _tier(r) == t]
        out[t] = _prf([pred[i] for i in idx], [rows[i]["kept"] for i in idx])
    for cyc in ("mega", "mini"):
        idx = [i for i, r in enumerate(rows) if r["cycle"] == cyc]
        if idx:
            out[cyc] = _prf([pred[i] for i in idx], [rows[i]["kept"] for i in idx])
    return out


def _predict(kind, arg, train: list[dict], test: list[dict], c: float | None = None):
    """(kept calls, scores, fitted parameter) for `test` from a candidate fitted on `train`."""
    if kind == "all":
        keep = [r["cost"] is not None for r in test]
        score = [r["_f"]["log_ratio"] for r in test]
        return _apply_caps(test, keep, score), score, None
    if kind == "current":
        keep = [_current(r) for r in test]
        score = [r["_f"]["log_ratio"] for r in test]
        return _apply_caps(test, keep, score), score, None
    if kind == "rule":
        out_k, out_s = [False] * len(test), [0.0] * len(test)
        par = {}
        for cyc in ("mega", "mini"):
            tr = [r for r in train if r["cycle"] == cyc and r["cost"] is not None]
            idx = [i for i, r in enumerate(test) if r["cycle"] == cyc]
            if not idx:
                continue
            t = _fit_rule(tr, arg)
            par[cyc] = t
            for i in idx:
                out_s[i] = test[i]["_f"][arg]
                out_k[i] = test[i]["cost"] is not None and out_s[i] >= t
        return _apply_caps(test, out_k, out_s), out_s, par
    m = _fit_logit(train, arg, c)
    # no forced zeros (K4): the mega caps limit the calls, never the chance
    p = _logit_p(m, test, arg)
    keep = [bool(x >= 0.5) for x in p]
    return _apply_caps(test, keep, list(p)), list(p), m


def _logloss(p: list[float], y: list[bool]) -> float:
    q = np.clip(np.array(p), 1e-6, 1 - 1e-6)
    t = np.array(y, dtype=float)
    return float(-np.mean(t * np.log(q) + (1 - t) * np.log(1 - q)))


def _ll_each(p: list[float], y: list[bool]) -> np.ndarray:
    q = np.clip(np.array(p, dtype=float), 1e-6, 1 - 1e-6)
    t = np.array(y, dtype=float)
    return -(t * np.log(q) + (1 - t) * np.log(1 - q))


def _reliability(p: list[float], y: list[bool]) -> list[dict]:
    """How often players were kept in each band of P(keep)."""
    out = []
    b = RELIABILITY_BANDS
    for lo, hi in zip(b[:-1], b[1:], strict=True):
        idx = [i for i, x in enumerate(p) if lo <= x < hi or (hi == 1.0 and x == 1.0)]
        if idx:
            out.append({"band": f"{lo:.2f}-{hi:.2f}", "n": len(idx),
                        "mean_p": round(float(np.mean([p[i] for i in idx])), 3),
                        "kept": round(float(np.mean([y[i] for i in idx])), 3)})  # fmt: skip
    return out


def _cycle_report(
    rows: list[dict], pred: list[bool], p: list[float] | None, train: list[dict]
) -> dict:
    """One cycle's held-out calls against its own majority call and a constant rate, both taken from
    the training deadlines of that cycle (K1), with 95% intervals of the differences by resampling
    team-deadlines, the release precision / recall and (with chances) the log loss and reliability."""
    if not rows:
        return {}
    cyc = rows[0]["cycle"]
    tr = [r for r in train if r["cycle"] == cyc] or train
    rate = float(np.mean([r["kept"] for r in tr]))
    maj = rate >= 0.5
    y = [r["kept"] for r in rows]
    hit = np.array([a == b for a, b in zip(pred, y, strict=True)], dtype=float)
    hit0 = np.array([maj == b for b in y], dtype=float)
    out = {"n": len(rows), "kept_rate": round(float(np.mean(y)), 3),
           "majority_call": "keep everyone" if maj else "release everyone",
           "accuracy": round(float(hit.mean()), 3), "majority_accuracy": round(float(hit0.mean()), 3),
           "prf": _report(rows, pred)}  # fmt: skip
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault((r["season"], r["team"]), []).append(i)
    keys = list(groups)
    rng = np.random.default_rng(7)
    llm = ll0 = None
    if p is not None:
        llm = _ll_each(p, y)
        ll0 = _ll_each([rate] * len(y), y)
        out["log_loss"] = round(float(llm.mean()), 4)
        out["const_log_loss"] = round(float(ll0.mean()), 4)
        out["reliability"] = _reliability(p, y)
    d_acc, d_ll = [], []
    for _ in range(BOOT):
        pick = [i for k in rng.integers(0, len(keys), len(keys)) for i in groups[keys[k]]]
        d_acc.append(hit[pick].mean() - hit0[pick].mean())
        if llm is not None:
            d_ll.append(llm[pick].mean() - ll0[pick].mean())
    out["acc_minus_majority"] = {"est": round(float(hit.mean() - hit0.mean()), 3),
                                 "ci95": [round(float(x), 3) for x in np.percentile(d_acc, [2.5, 97.5])]}  # fmt: skip
    if llm is not None:
        out["ll_minus_const"] = {"est": round(float(llm.mean() - ll0.mean()), 4),
                                 "ci95": [round(float(x), 4) for x in np.percentile(d_ll, [2.5, 97.5])]}  # fmt: skip
    return out


def _platt(p: list[float], y: list[bool]) -> tuple[float, float]:
    """(a, b) of the recalibration σ(a + b·logit p), fitted by maximum likelihood (no penalty)."""
    from sklearn.linear_model import LogisticRegression

    q = np.clip(np.array(p, dtype=float), 1e-6, 1 - 1e-6)
    x = np.log(q / (1 - q)).reshape(-1, 1)
    m = LogisticRegression(C=1e6, max_iter=5000).fit(x, np.array(y, dtype=int))
    return float(m.intercept_[0]), float(m.coef_[0][0])


def _recal(p: list[float], ab: tuple[float, float] | None) -> list[float]:
    if ab is None:
        return list(p)
    q = np.clip(np.array(p, dtype=float), 1e-6, 1 - 1e-6)
    z = ab[0] + ab[1] * np.log(q / (1 - q))
    return list(1.0 / (1.0 + np.exp(-z)))


@app.command()
def score(
    work: Path = typer.Option(..., "--work"),
    recipe: str = typer.Option(
        "", "--recipe", help="price recipe letter (default: the shipped one)"
    ),
    out: Path = typer.Option(OUT, "--out"),
    model_out: Path = typer.Option(MODEL_OUT, "--model-out", help="the shipped model (keep.py)"),
) -> None:
    """Choose the rule by forward-chaining folds on the deadlines 2020-2024, validate it once on 2025
    (mega) and 2026 (mini) apart (protocol declared 2026-10-30)."""
    rows_f = work / f"rows_{_rows_key()}.pkl"
    if not rows_f.exists():
        raise typer.BadParameter(f"no {rows_f.name}: the rows' inputs changed, run `rows` first")
    data: dict = pickle.loads(rows_f.read_bytes())
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    _playing_time(data)
    _mega_retained(data)
    mk = _market(work, data, recipe or None)
    for s, rows in data.items():
        for r in rows:
            r["market"], r["market_central"] = mk[(s, r["team"], r["cricsheet_id"])]
        _costs(rows, s)
    # the market price on the 3-season forecast (what a buyer buys over a contract)
    fcm = _forecast_market(work, data, recipe or None)
    for s, rows in data.items():
        for r in rows:
            r["_f"] = _feats(r)
            fm = fcm.get((s, r["team"], r["cricsheet_id"]))
            cost = r["cost"] if r["cost"] else 1e-3
            r["_f"]["log_ratio_fc"] = (
                math.log(max(fm, 1e-3) / cost) if fm is not None else r["_f"]["log_ratio"]
            )
    early = [s for s in SEASONS if s <= SELECT_LAST]
    res: dict = {"protocol": {
        "declared": "2026-10-30, before any of its numbers (METHODOLOGY §10, the 2026-10-30 refit)",
        "selection": "forward-chaining: each deadline 2020-2024 predicted by the candidate fitted on "
                     "the deadlines before it only; the lowest pooled held-out log loss wins "
                     "(logistic C chosen the same way). Mega-auction caps limit the calls, never "
                     "the chance (no forced zeros)",
        "validation": "fitted on 2018-2024, scored once on 2025 (mega) and 2026 (mini), each "
                      "against its own majority call and a constant rate; 95% intervals by "
                      "resampling team-deadlines. Not an untouched test: earlier models were read "
                      "on these deadlines",
        "label": "the published retained list; traded players and retirements announced by the "
                 "deadline left out",
    }, "selection": {}}  # fmt: skip
    best = None
    oof: dict = {}  # (name, c) -> {season: scores} on 2019-2024, for the recalibration
    for name, (kind, arg) in [BASELINE, *CANDIDATES.items()]:
        cs = C_GRID if kind == "logit" else (None,)
        for c in cs:
            preds, ys, ps, rows_all = [], [], [], []
            per: dict[str, dict] = {}
            for s in FOLDS:
                tr = [r for t in early if t < s for r in data[t]]
                k, sc, _ = _predict(kind, arg, tr, data[s], c)
                preds += k
                ys += [r["kept"] for r in data[s]]
                ps += sc
                rows_all += data[s]
                per[str(s)] = _cycle_report(data[s], k, sc if kind == "logit" else None, tr)
            if kind == "logit":
                tr19 = list(data[2018])
                oof[(name, c)] = {2019: _predict(kind, arg, tr19, data[2019], c)[1]}
                for s in FOLDS:
                    oof[(name, c)][s] = ps[sum(len(data[t]) for t in FOLDS if t < s) :][
                        : len(data[s])
                    ]
            rep_ = _report(rows_all, preds)
            label = name if c is None else f"{name} (C={c})"
            if kind == "logit":
                rep_["log_loss"] = round(_logloss(ps, ys), 4)
            rep_["by_deadline"] = per
            for cyc in ("mega", "mini"):
                idx = [i for i, r in enumerate(rows_all) if r["cycle"] == cyc]
                tr_c = [r for t in early if t < FOLDS[0] for r in data[t]]
                rep_[f"{cyc}_cycle"] = _cycle_report(
                    [rows_all[i] for i in idx], [preds[i] for i in idx],
                    [ps[i] for i in idx] if kind == "logit" else None, tr_c,
                )  # fmt: skip
            res["selection"][label] = rep_
            typer.echo(
                f"{label[:70]:70} acc {rep_['all']['accuracy']:.3f} F1 {rep_['all']['f1']:.3f} "
                f"star acc {rep_['star']['accuracy']:.3f}"
                + (f" LL {rep_['log_loss']:.4f}" if kind == "logit" else "")
            )
            if kind == "logit" and (best is None or rep_["log_loss"] < best[0]):
                best = (rep_["log_loss"], name, c)
    _, chosen, chosen_c = best
    res["chosen"] = f"{chosen} (C={chosen_c})"
    typer.echo(f"chosen: {res['chosen']}")

    # K6: a Platt recalibration per cycle, fitted on the earlier deadlines' out-of-fold scores, kept
    # only if it lowers the 2020-2024 log loss
    sc_oof = oof[(chosen, chosen_c)]
    raw_p, cal_p, ys = [], [], []
    for s in FOLDS:
        cyc = data[s][0]["cycle"]
        prior = [(p_, r["kept"]) for t in sc_oof if t < s and data[t][0]["cycle"] == cyc
                 for p_, r in zip(sc_oof[t], data[t], strict=True)]  # fmt: skip
        ab = _platt([x for x, _ in prior], [y for _, y in prior]) if len(prior) >= 100 else None
        raw_p += sc_oof[s]
        cal_p += _recal(sc_oof[s], ab)
        ys += [r["kept"] for r in data[s]]
    ll_raw, ll_cal = _logloss(raw_p, ys), _logloss(cal_p, ys)
    use_cal = ll_cal < ll_raw
    calib = None
    if use_cal:
        calib = {}
        for cyc in ("mega", "mini"):
            pr = [(p_, r["kept"]) for t in sc_oof if data[t][0]["cycle"] == cyc
                  for p_, r in zip(sc_oof[t], data[t], strict=True)]  # fmt: skip
            if len(pr) >= 100:
                calib[cyc] = _platt([x for x, _ in pr], [y for _, y in pr])
    res["calibration"] = {"log_loss_raw": round(ll_raw, 4), "log_loss_platt": round(ll_cal, 4),
                          "applied": use_cal,
                          "platt": {k: [round(v[0], 4), round(v[1], 4)] for k, v in (calib or {}).items()},
                          "reliability_2020_2024": {
                              cyc: _reliability([x for x, r in zip(raw_p, [r for s in FOLDS for r in data[s]], strict=True) if r["cycle"] == cyc],
                                                [r["kept"] for s in FOLDS for r in data[s] if r["cycle"] == cyc])
                              for cyc in ("mega", "mini")}}  # fmt: skip
    typer.echo(f"calibration: raw {ll_raw:.4f} platt {ll_cal:.4f} -> applied {use_cal}")

    # validation, once: fitted on 2018-2024, scored on 2025 (mega) and 2026 (mini)
    train = [r for s in early for r in data[s]]
    res["validation"] = {}
    ref = next(iter(CANDIDATES))
    cands = dict([BASELINE, *CANDIDATES.items()])
    for name in dict.fromkeys([chosen, ref, BASELINE[0]]):
        kind, arg = cands[name]
        c = chosen_c if name == chosen else None
        v: dict = {}
        dis = []
        for s in TEST:
            k, sc, _ = _predict(kind, arg, train, data[s], c)
            if name == chosen and calib and data[s][0]["cycle"] in calib:
                sc = _recal(sc, calib[data[s][0]["cycle"]])
                k = _apply_caps(data[s], [x >= 0.5 for x in sc], sc)
            v[str(s)] = _cycle_report(data[s], k, sc if kind == "logit" else None, train)
            # where the call and the franchise disagree, stars first (the honest list)
            for r, kk, x in zip(data[s], k, sc, strict=True):
                if kk != r["kept"] and _tier(r) == "star":
                    dis.append({"season": r["season"], "team": r["team"], "name": r["name"],
                                "kept": r["kept"], "call": "keep" if kk else "release",
                                "score": round(float(x), 3), "cost": r["cost"],
                                "market": round(r["market"], 2),
                                "age": r.get("age") and round(r["age"], 1),
                                "matches_last": r.get("matches_last"),
                                "captain_here": r.get("captain_here"),
                                "seasons_here": r.get("seasons_here"),
                                "home_grown": r.get("home_grown")})  # fmt: skip
        v["star_disagreements"] = dis
        res["validation"][name] = v
        for s in TEST:
            q = v[str(s)]
            typer.echo(f"VALIDATION {s} {name[:50]}: acc {q['accuracy']} vs {q['majority_call']} "
                       f"{q['majority_accuracy']} CI {q['acc_minus_majority']['ci95']}"
                       + (f" LL {q['log_loss']} vs {q['const_log_loss']} CI {q['ll_minus_const']['ci95']}"
                          if "log_loss" in q else ""))  # fmt: skip

    # the shipped rule: the chosen candidate refitted on every deadline 2018-2026
    kind, arg = CANDIDATES[chosen]
    every = [r for s in SEASONS for r in data[s]]
    if kind == "logit":
        m = _fit_logit(every, arg, chosen_c)
        sc_, est = m[0], m[-1]
        names = list(arg)
        scale = np.where(sc_.scale_ == 0, 1.0, sc_.scale_)
        raw = est.coef_.ravel() / scale
        icpt = float(est.intercept_[0]) - float(np.sum(raw * sc_.mean_))
        res["model"] = {"kind": "logit", "C": chosen_c, "intercept": round(icpt, 6),
                        "coef": {k: round(float(v), 6) for k, v in zip(names, raw, strict=True)},
                        "trained_on": [SEASONS[0], SEASONS[-1]], "rows": len(every)}  # fmt: skip
        if calib:
            res["model"]["calibration"] = {k: {"a": round(v[0], 6), "b": round(v[1], 6)}
                                           for k, v in calib.items()}  # fmt: skip
    elif kind == "rule":
        res["model"] = {"kind": "rule", "index": arg,
                        "threshold": {cyc: _fit_rule([r for r in every if r["cycle"] == cyc], arg)
                                      for cyc in ("mega", "mini")}}  # fmt: skip
    else:
        res["model"] = {"kind": "current"}
    # what these numbers were computed from
    res["provenance"] = {"git": _git_sha(), "rows": _rows_key(),
                         "market": _market_key(_rows_key()), "recipe": recipe or "shipped"}  # fmt: skip
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    typer.echo(f"wrote {out}")
    if res["model"]["kind"] == "logit":
        import datetime as _dt

        shipped = {
            "schema": 1,
            "league": "ipl",
            "fitted": _dt.date.today().isoformat(),
            "method": "P(a franchise keeps him at the retention deadline) = logistic regression on "
                      "web_parity/keep.py keep_features (L2, standardised, refolded to raw units), "
                      f"recipe '{res['chosen']}', chosen by forward-chaining folds on 2020-2024 "
                      "(scripts/keep_backtest.py)",
            "data": "the published retained lists of every deadline 2018-2026 "
                    "(data/curated/ipl_auction_history.json, Wikipedia, CC BY-SA 4.0) against each "
                    "franchise's squad before it",
            "intercept": res["model"]["intercept"],
            "coef": res["model"]["coef"],
            "trained_on": res["model"]["trained_on"],
            "rows": res["model"]["rows"],
            "evaluation": {"protocol": res["protocol"], "chosen": res["chosen"],
                           "calibration": res["calibration"],
                           "validation": {k: {y: {q: v[y][q] for q in ("n", "kept_rate",
                                                   "majority_call", "accuracy", "majority_accuracy",
                                                   "acc_minus_majority", "log_loss", "const_log_loss",
                                                   "ll_minus_const") if q in v[y]}
                                              for y in ("2025", "2026")}
                                          for k, v in res["validation"].items()}},
        }  # fmt: skip
        if res["model"].get("calibration"):
            shipped["calibration"] = res["model"]["calibration"]
        model_out.write_text(
            json.dumps(shipped, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        typer.echo(f"wrote {model_out}")


def _forecast_market(work: Path, data: dict, letter: str | None) -> dict:
    """(season, team, cid) → his market price with the 3-season forecast average as his value (what
    a buyer pays for over a contract; None without a forecast)."""
    spec_name = letter or "shipped"
    f = work / f"fcmarket_{spec_name}_{_market_key(_rows_key())}.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    price_rows, _risk, hist, ret_rows = ipm.build_rows()
    spec = (
        ipm.shipped_spec()
        if not letter
        else next(v for k, v in ipm.CANDIDATES.items() if k.split()[0] == letter)
    )
    out: dict = {}
    for s, rows in data.items():
        a = hist["auctions"][str(s)]
        model = {
            "floor_cr": 0.2 if s < 2025 else 0.3,
            "competition": {"cycle": a["kind"], "purse": float(a["purse_cr"])},
            "price": ipm.fit_price_part(price_rows, ret_rows, spec, 2018 if s > 2019 else 2011, s),
            "bought": (pricing.load_price_model() or {}).get("bought"),
        }
        for r in rows:
            if r.get("forecast_avg3") is None:
                continue
            # the forecast is the value itself (no cautious discount: its range is already in it)
            row = {**ipm._valued(r), "price_value": float(r["forecast_avg3"]), "value_sd": 0.0}
            out[(s, r["team"], r["cricsheet_id"])] = pricing.market_price(
                row, model["competition"], model
            )["price"]
    f.write_bytes(pickle.dumps(out))
    return out


if __name__ == "__main__":
    app()
