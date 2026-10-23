"""Fit the Auction room's bidding: a demand model estimated on real IPL auctions (audit item 7).

Each franchise bids for a lot at all with probability

    P_ij = logistic(p0 + p1 * ln(market price_i) + p2 * ln(base price_i) [+ i_* × its needs, D7])

and, when it does, up to

    ln bid_ij = mu_ij + u_i + sigma * e_ij,   e_ij ~ Gumbel(0, 1),   u_i ~ Normal(0, tau^2)

    mu_ij = a + c * ln(market price_i) + b_base * ln(base price_i) + b_anchor * ln(last price_i / market price_i)
          + b_money * mean over the bidding teams of ln(purse per open place)
          + b_stage * share of the league's open places already filled
          + b_need * ln(1 + places the team is short in his role)
          + b_os * (overseas lot) * the team's open overseas places / its open places
          + b_pps * (ln(the team's purse per open place) - that mean)
          + b_up * (his expected contribution - the team's best in his role so far)

`u_i` is how hot the lot is on the day (shared by every team), `e_ij` the team's own view. The bid is
held to the team's spendable purse (the purse less the minimum base price for each place it still
needs to reach the squad minimum), a team bids only with a squad place (and an overseas place) left,
and the lot sells to the highest bid at the next step of the IPL ladder above the second-highest bid
(at the base price when nobody else reaches it): an English (open-outcry) auction with increments.

The likelihood of each real sale (who bought him, at what price) is exact under that model: the
winner's bid is at least the price, the best of the others' lies in the ladder step below it (below
the base price for a sale at base), conditional on the lot selling (the history lists only sold
lots), with u integrated out by Gauss-Hermite quadrature. Team states (squad by role, overseas,
purse, best contribution per role) are rebuilt lot by lot from the real retentions and the sold lots
in the order the history lists them (the auction's set order; the order inside a set is the page's,
not necessarily the hammer's).

Frozen protocol: candidates declared below before any test number; chosen by leave-one-auction-out
log-likelihood over the 2019-2024 auctions; the chosen one fitted on 2019-2024 and scored once on the
2025 mega and the 2026 mini auctions; then refitted on 2019-2026 and shipped (config/auction_demand.json,
the constants of web_parity/auction.py ⇄ site/src/lib/auction.ts).

Each lot's market price for the selection seasons comes from the price recipe fitted on the OTHER
2018-2024 auctions (`mk`), for the test from the auctions before only, for the shipped refit from every
other auction.

    uv run python scripts/auction_demand_fit.py inputs --work <dir>     # the replay inputs (cached)
    uv run python scripts/auction_demand_fit.py mk --work <dir>         # the lots' market prices (cached)
    uv run python scripts/auction_demand_fit.py fit --work <dir>        # round 1: selection, test, ship
    uv run python scripts/auction_demand_fit.py round2 --work <dir> [--ship]   # round 2 (the shipped R4)
"""

from __future__ import annotations

import json
import math
import pickle
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import typer
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cricdex.web_parity.auction import ladder_next, ladder_step  # noqa: E402

app = typer.Typer(add_completion=False)
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "auction_demand.json"
SELECT = (2019, 2020, 2021, 2022, 2023, 2024)  # the auctions the candidates are chosen on (LOAO)
TEST = (2025, 2026)
SEASONS = SELECT + TEST
SQUAD_MIN, SQUAD_MAX, OS_MAX = 18, 25, 8
ROLES = ("batter", "bowler", "all_rounder", "keeper")
GH_N = 24
UP_CLIP = 15.0  # runs a match: the upgrade feature is held to ±15 (a few unrated outliers)
VAL_CLIP = 15.0  # runs a match: his expected contribution as a lot feature, held to ±15
CONDITION_ON_SALE = True  # the history lists sold lots only
TOP_BASE = 2.0  # cr: the highest base price; "hinge" = the market price above it (ln), where the base says nothing

# the features each candidate adds (declared before any test number)
LOT_FEATS = ("base", "anchor", "money", "stage", "mega", "val", "hinge")
TEAM_FEATS = ("need", "os", "pps", "up")
CANDIDATES: dict[str, dict] = {
    "D0 market price only (symmetric bidders)": {"feats": ("base", "anchor",)},
    "D1 + role and overseas need": {"feats": ("base", "anchor", "need", "os")},
    "D2 + purse per open place": {"feats": ("base", "anchor", "need", "os", "pps", "money")},
    "D3 + upgrade on the team's best in his role": {"feats": ("base", "anchor", "need", "os", "pps", "money", "up")},
    "D4 + auction stage": {"feats": ("base", "anchor", "need", "os", "pps", "money", "up", "stage")},
    "D5 D4 + a mega-auction level": {"feats": ("base", "anchor", "need", "os", "pps", "money", "up", "stage", "mega")},
    "D6 D4 + team effects (estimated personalities)": {
        "feats": ("base", "anchor", "need", "os", "pps", "money", "up", "stage"), "teams": True},
    "D7 D4 + team needs in whether a team bids at all": {
        "feats": ("base", "anchor", "need", "os", "pps", "money", "up", "stage"), "interest_team": True},
    # declared 2026-10-23 after the validation replays of 2022-23 showed mini-auction stars the market
    # price misses (Green, Brook: sold at base in every run), before any test number
    "D8 D7 + his expected contribution (in the bid and in whether a team bids)": {
        "feats": ("base", "anchor", "need", "os", "pps", "money", "up", "stage", "val"),
        "interest_team": True},
}  # fmt: skip
TEAM_SD = 0.3  # the team effects' prior sd (ln bid): a ridge penalty, D6 only


# ---- inputs ----------------------------------------------------------------------------------------


@app.command()
def inputs(work: Path = typer.Option(..., "--work")) -> None:
    """Each auction's replay inputs (bidplan_backtest._season_inputs: as-of contributions, P(plays),
    a price model fitted on the auctions before, the real retentions and purses, the sold lots and
    the unsold alternatives, next-season values), one cached pickle per season. Resumable."""
    import bidplan_backtest as bt
    import ipl_price_model as ipm

    from cricdex.scout.identity import master

    work.mkdir(parents=True, exist_ok=True)
    todo = [s for s in SEASONS if not (work / f"season_{s}.pkl").exists()]
    if not todo:
        print("all cached")
        return
    t0 = time.time()
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    price_rows, risk_rows, hist, ret_rows = ipm.build_rows()
    pm = master.load()
    apps = ipm.ipl_appearances()
    tags = bt._tags_fn()
    print(f"features in {time.time() - t0:.0f}s", flush=True)
    for s in todo:
        si = bt._season_inputs(s, (price_rows, ret_rows, risk_rows), hist, pm, apps, tags)
        si.pop("model", None)
        (work / f"season_{s}.pkl").write_bytes(pickle.dumps(si))
        print(f"{s}: {sum(1 for r in si['avail'] if r['_price'])} sold + "
              f"{sum(1 for r in si['avail'] if not r['_price'])} alternatives, {len(si['teams'])} teams "
              f"({time.time() - t0:.0f}s)", flush=True)  # fmt: skip


def _price_part_without(price_rows, ret_rows, spec, keep) -> dict:
    """ipl_price_model.fit_price_part on the auctions `keep(season)` selects (2018 on)."""
    import ipl_price_model as ipm

    names, kind = spec[0], spec[1]
    rows = [r for r in ipm._rows_for(price_rows, ret_rows, 2018, spec) if keep(r["season"])]
    ipm._use_form(spec, rows)
    y = np.array([r["y"] for r in rows])
    alpha = ipm._choose_alpha(kind, rows, names)
    m = ipm._fit_reg(kind, ipm._matrix(rows, names), y, alpha, ipm._cens(rows))
    cal = ipm._calibration_for(kind, rows, alpha, names, ipm._FORM["cal"], ipm.CAL_GROUPS)
    icpt, coef = ipm._raw_coef(m, names)
    out = {"intercept": icpt, "coef": coef, "link": ipm._link(m), **cal}
    if ipm._FORM["pv_max"] is not None:
        out["pv_max"] = ipm._FORM["pv_max"]
    return out


@app.command()
def mk(work: Path = typer.Option(..., "--work")) -> None:
    """Each lot's market price from a price model fitted on the OTHER auctions: `mk24` on 2018-2024
    without his auction (the selection seasons' input: the walk-forward models of 2019-2021 had only
    three auctions to learn from and price the top 3-9 cr, which no bidding model can map to 15-25 cr
    sales), `mk26` on 2018-2026 without it (the shipped refit's input). The test seasons keep their
    walk-forward price (`projected_value`: auctions before only). Cached per season."""
    import ipl_price_model as ipm

    from cricdex.web_parity.pricing import load_price_model, market_price

    todo = [s for s in SEASONS if not (work / f"mk_{s}.json").exists()]
    if not todo:
        print("all cached")
        return
    ipm.AUCTIONS_DATES.update(ipm.auction_dates())
    price_rows, risk_rows, hist, ret_rows = ipm.build_rows()
    spec = ipm.shipped_spec()
    bought = (load_price_model() or {}).get("bought")
    for s in todo:
        si = load_season(work, s)
        feats = {r["cricsheet_id"]: r for r in risk_rows if r["season"] == s}
        feats.update({r["cricsheet_id"]: r for r in price_rows if r["season"] == s})
        comp = {"cycle": si["cycle"], "purse": float(si["purse"])}
        out: dict[str, dict] = {r["cricsheet_id"]: {} for r in si["avail"]}
        for tag, keep in (("mk24", lambda y, s=s: y != s and y <= 2024),
                          ("mk26", lambda y, s=s: y != s)):  # fmt: skip
            if tag == "mk24" and s > 2024:
                continue
            model = {"floor_cr": 0.3, "competition": comp, "bought": bought,
                     "price": _price_part_without(price_rows, ret_rows, spec, keep)}  # fmt: skip
            for r in si["avail"]:
                f = feats.get(r["cricsheet_id"])
                if f is not None:
                    out[r["cricsheet_id"]][tag] = market_price(f, comp, model)["price"]
        (work / f"mk_{s}.json").write_text(json.dumps(out), encoding="utf-8")
        print(f"{s}: done", flush=True)


MK_SOURCE = {"mode": "walk"}  # "walk" (projected_value) | "mk24" | "mk26": the lots' market price


def load_season(work: Path, s: int) -> dict:
    si = pickle.loads((work / f"season_{s}.pkl").read_bytes())
    tag = MK_SOURCE["mode"]
    if tag != "walk":
        f = work / f"mk_{s}.json"
        mk = json.loads(f.read_text(encoding="utf-8"))
        for r in si["avail"]:
            v = (mk.get(r["cricsheet_id"]) or {}).get(tag)
            if v is not None:
                r["projected_value"] = v
    return si


# ---- team states, lot by lot -------------------------------------------------------------------------

ROLE_TEXT = (
    ("keep", "keeper"), ("all", "all_rounder"), ("bowl", "bowler"), ("spin", "bowler"),
    ("bat", "batter"),
)  # fmt: skip


def role_of_text(t: str | None) -> str:
    t = (t or "").lower()
    for k, r in ROLE_TEXT:
        if k in t:
            return r
    return "batter"


def piece_value(p: dict) -> float:
    return float(p.get("v") or 0.0)


def lot_value(r: dict) -> float | None:
    """A lot's expected contribution a match: P(plays as a free agent) × contribution (None unrated)."""
    c = r.get("contrib")
    if c is None:
        return None
    pp = r.get("p_play")
    return float(c) * (1.0 if pp is None else float(pp))


def role_targets(work: Path) -> dict[str, float]:
    """The squad's usual make-up: the median end-of-auction count per role over the 2019-2024 squads
    (kept + bought), so 'short in his role' is measured against what real squads hold."""
    counts: dict[str, list[int]] = {r: [] for r in ROLES}
    for s in SELECT:
        si = load_season(work, s)
        for t, v in si["teams"].items():
            n = dict.fromkeys(ROLES, 0)
            for p in v["kept"]:
                n[p["role"]] += 1
            for lot in si["lots"]:
                if lot["team"] == t:
                    n[_lot_role(si, lot)] += 1
            for r in ROLES:
                counts[r].append(n[r])
    return {r: float(statistics.median(v)) for r, v in counts.items()}


def _lot_role(si: dict, lot: dict) -> str:
    by = si.setdefault("_by_id", {r["cricsheet_id"]: r for r in si["avail"]})
    r = by.get(lot.get("cricsheet_id") or "")
    return r["role"] if r else role_of_text(lot.get("role_text"))


def rows_of(si: dict, targets: dict[str, float]) -> dict:
    """The likelihood rows of one auction: for every sold lot with a market price, each team's
    features just before it, who won and the price; team states updated by every sold lot."""
    purse = float(si["purse"])
    min_base = min(float(lot.get("base_price_cr") or 99) for lot in si["lots"])
    min_base = min(min_base, 0.3) if min_base < 99 else 0.3
    teams = sorted(si["teams"])
    by = {r["cricsheet_id"]: r for r in si["avail"]}
    st = {}
    for t in teams:
        v = si["teams"][t]
        n = dict.fromkeys(ROLES, 0)
        best = dict.fromkeys(ROLES, 0.0)
        for p in v["kept"]:
            n[p["role"]] += 1
            best[p["role"]] = max(best[p["role"]], piece_value(p))
        st[t] = {"n": len(v["kept"]), "os": sum(1 for p in v["kept"] if p["os"]), "role": n,
                 "best": best, "left": purse - float(v["cost"])}  # fmt: skip
    open0 = sum(max(0, SQUAD_MAX - st[t]["n"]) for t in teams)
    filled = 0
    out = []
    for lot in si["lots"]:
        cid = lot.get("cricsheet_id")
        r = by.get(cid or "")
        role = r["role"] if r else role_of_text(lot.get("role_text"))
        os_ = bool(r["is_overseas"]) if r else (lot.get("country") or "IND") != "IND"
        price = float(lot["price_cr"])
        base = float(lot.get("base_price_cr") or min_base)
        base = min(base, price)
        win = lot["team"]
        if r is not None and r.get("projected_value") and win in st:
            v_i = lot_value(r)
            elig, feats = [], []
            pps_all = []
            for t in teams:
                s = st[t]
                open_ = SQUAD_MAX - s["n"]
                spend = s["left"] - max(0, SQUAD_MIN - s["n"] - 1) * min_base
                ok = open_ > 0 and (not os_ or s["os"] < OS_MAX) and spend >= base - 1e-9
                if not ok and t != win:
                    continue
                open_ = max(open_, 1)
                pps = max(s["left"], min_base) / open_
                pps_all.append(math.log(pps))
                short = max(0.0, targets[role] - s["role"][role])
                os_open = max(0, OS_MAX - s["os"])
                elig.append(t)
                feats.append({
                    "need": math.log1p(short),
                    "os": (min(os_open, open_) / open_) if os_ else 0.0,
                    "lnpps": math.log(pps),
                    "up": 0.0 if v_i is None else max(-UP_CLIP, min(UP_CLIP, v_i - s["best"][role])),
                    "lnS": math.log(max(spend, 1e-6)),
                })  # fmt: skip
            money = sum(pps_all) / len(pps_all)
            for f in feats:
                f["pps"] = f.pop("lnpps") - money
            anchor = r.get("anchor_price")
            mk = float(r["projected_value"])
            out.append({
                "season": si["season"], "cid": cid, "name": lot["name"], "price": price, "base": base,
                "mk": mk, "teams": elig, "win": elig.index(win), "feats": feats,
                "lot": {"base": math.log(base), "anchor": math.log(anchor / mk) if anchor else 0.0, "money": money,
                        "stage": filled / max(open0, 1), "mega": 1.0 if si["cycle"] == "mega" else 0.0,
                        "val": 0.0 if v_i is None else max(-VAL_CLIP, min(VAL_CLIP, v_i)),
                        "hinge": max(0.0, math.log(mk / TOP_BASE))},
            })  # fmt: skip
        # the sale updates the buyer
        if win in st:
            s = st[win]
            s["n"] += 1
            s["os"] += 1 if os_ else 0
            s["role"][role] += 1
            s["left"] -= price
            if r is not None:
                lv = lot_value(r)
                if lv is not None:
                    s["best"][role] = max(s["best"][role], lv)
        filled += 1
    return {"rows": out, "teams": teams, "min_base": min_base}


# ---- the likelihood -----------------------------------------------------------------------------------


class Design:
    """The rows of a set of auctions as padded arrays (lots × 10 teams)."""

    def __init__(self, rows: list[dict], feats: tuple[str, ...], team_ids: list[str] | None,
                 interest_team: bool = False, heavy: bool = False):  # fmt: skip
        self.rows = rows
        self.interest_team = interest_team
        # a heavy-tailed heat: most lots quiet (sd tau), a share q of them a bidding war (sd tau × (1 + e^h))
        self.heavy = heavy
        J = max(len(r["teams"]) for r in rows)
        n = len(rows)
        self.lot_names = [f for f in LOT_FEATS if f in feats]
        self.team_names = [f for f in TEAM_FEATS if f in feats]
        self.mask = np.zeros((n, J), bool)
        self.X = np.zeros((n, J, len(self.team_names)))
        self.Z = np.zeros((n, len(self.lot_names)))
        self.lnS = np.full((n, J), 50.0)
        self.tid = np.zeros((n, J), int)
        self.team_ids = team_ids or []
        tix = {t: k for k, t in enumerate(self.team_ids)}
        self.lnmk = np.array([math.log(r["mk"]) for r in rows])
        self.win = np.array([r["win"] for r in rows])
        self.base = np.array([r["base"] for r in rows])
        self.price = np.array([r["price"] for r in rows])
        for i, r in enumerate(rows):
            for j, (t, f) in enumerate(zip(r["teams"], r["feats"], strict=True)):
                self.mask[i, j] = True
                self.X[i, j] = [f[k] for k in self.team_names]
                self.lnS[i, j] = f["lnS"]
                self.tid[i, j] = tix.get(t, 0)
            self.Z[i] = [r["lot"][k] for k in self.lot_names]
        at_base = self.price <= self.base + 1e-9
        self.at_base = at_base
        # the second-best bid's interval (ln): below the base price for a sale at base, else the
        # ladder step below the price; the winner's bid is at least the price
        lo = np.array([p - ladder_step(p - 1e-9) for p in self.price])
        self.U = np.log(np.where(at_base, self.base, self.price))
        self.L = np.where(at_base, -np.inf, np.log(np.maximum(lo, 1e-6)))
        self.lnb = np.log(self.base)
        self.has_val = "val" in self.lot_names
        self.val = np.array([r["lot"]["val"] for r in rows])
        x, w = np.polynomial.hermite.hermgauss(GH_N)
        self.gh_x = x * math.sqrt(2.0)
        self.gh_w = w / math.sqrt(math.pi)

    # parameters: a, c, ln sigma, ln tau, the interest logit (p0, p1 on ln market price, p2 on ln base),
    # the lot features, the team features (in the bid), the team features in the interest (D7), the
    # team effects (D6)
    NB = 7

    def n_ix(self) -> int:
        return len(self.team_names) if self.interest_team else 0

    def n_par(self) -> int:
        return (
            self.NB
            + len(self.lot_names)
            + len(self.team_names)
            + self.n_ix()
            + int(self.has_val)
            + len(self.team_ids)
            + (2 if self.heavy else 0)
        )

    def unpack(self, th: np.ndarray) -> dict:
        out = {"a": th[0], "c": th[1], "ln_sigma": th[2], "ln_tau": th[3], "p0": th[4], "p1": th[5],
               "p2": th[6]}  # fmt: skip
        k = self.NB
        for nm in self.lot_names:
            out[nm] = th[k]
            k += 1
        for nm in self.team_names:
            out[nm] = th[k]
            k += 1
        for nm in self.team_names[: self.n_ix()]:
            out["i_" + nm] = th[k]
            k += 1
        if self.has_val:
            out["i_val"] = th[k]
            k += 1
        out["team"] = th[k : k + len(self.team_ids)]
        if self.heavy:
            out["heat_h"], out["heat_q"] = th[-2], th[-1]
        return out

    def mu(self, th: np.ndarray) -> np.ndarray:
        p = self.unpack(th)
        m = p["a"] + p["c"] * self.lnmk
        k = self.NB
        if self.lot_names:
            m = m + self.Z @ th[k : k + len(self.lot_names)]
        m = m[:, None] + np.zeros(self.mask.shape)
        k += len(self.lot_names)
        if self.team_names:
            m = m + self.X @ th[k : k + len(self.team_names)]
        if self.team_ids:
            m = m + p["team"][self.tid]
        return m

    def interest(self, th: np.ndarray) -> np.ndarray:
        """P(a team bids at all for the lot), lots × teams: logistic in ln(market price) and ln(base
        price), plus the team features when `interest_team`."""
        z = th[4] + th[5] * self.lnmk + th[6] * self.lnb
        z = z[:, None] + np.zeros(self.mask.shape)
        k = self.NB + len(self.lot_names) + len(self.team_names)
        if self.n_ix():
            z = z + self.X @ th[k : k + self.n_ix()]
        if self.has_val:
            z = z + th[k + self.n_ix()] * self.val[:, None]
        return 1.0 / (1.0 + np.exp(-z))

    def loglik(self, th: np.ndarray, per_lot: bool = False):
        """Sum (or per lot) of ln P(winner, price) (÷ P(sold) when CONDITION_ON_SALE)."""
        mu = self.mu(th)
        sig = math.exp(th[2])
        tau = math.exp(th[3])
        comps = [(1.0, tau)]
        if self.heavy:
            q = 1.0 / (1.0 + math.exp(-th[-1]))
            comps = [(1.0 - q, tau), (q, tau * (1.0 + math.exp(th[-2])))]
        pi = self.interest(th)
        n, J = self.mask.shape
        rows = np.arange(n)
        obs = np.zeros(n)
        sold = np.zeros(n)
        nodes = [
            (cw * w, sd * x) for cw, sd in comps for x, w in zip(self.gh_x, self.gh_w, strict=True)
        ]
        for w, ux in nodes:
            m = mu + ux

            def logG(
                v, m=m
            ):  # ln P(effective bid ≤ v): not interested, or a bid ≤ v; 0 at or above the cap
                v = v[:, None]
                f = np.exp(-np.exp(np.clip(-(v - m) / sig, -50, 50)))
                g = np.log(np.maximum((1.0 - pi) + pi * f, 1e-300))
                g = np.where(v >= self.lnS, 0.0, g)
                return np.where(self.mask, g, 0.0)

            gU = logG(self.U)
            gL = logG(self.L)
            gb = logG(self.lnb)
            wU, wL = gU[rows, self.win], gL[rows, self.win]
            others_U = gU.sum(1) - wU
            others_L = gL.sum(1) - wL
            p_win = 1.0 - np.exp(wU)  # winner's bid ≥ the price (≥ base at base)
            second = np.exp(others_U) - np.where(self.at_base, 0.0, np.exp(others_L))
            obs += w * p_win * np.maximum(second, 0.0)
            sold += w * (1.0 - np.exp(gb.sum(1)))
        ll = np.log(np.maximum(obs, 1e-300))
        if CONDITION_ON_SALE:
            ll = ll - np.log(np.maximum(sold, 1e-300))
        return ll if per_lot else float(ll.sum())

    def penalty(self, th: np.ndarray) -> float:
        if not self.team_ids:
            return 0.0
        t = self.unpack(th)["team"]
        return float(0.5 * np.sum(t**2) / TEAM_SD**2)


def fit_design(
    d: Design, start: np.ndarray | None = None, fixed: dict[int, float] | None = None
) -> np.ndarray:
    """Maximum likelihood; `fixed` = {parameter index: value} held fixed (e.g. {1: 1.0}: a bid in
    proportion to the market price)."""
    th0 = np.zeros(d.n_par()) if start is None else np.array(start, float)
    if start is None:
        th0[1] = 1.0
        th0[2] = math.log(0.5)
        th0[3] = math.log(0.5)
        if d.heavy:  # start from a rare, wide bidding-war component (sd ×3.7 on 12% of lots)
            th0[-2], th0[-1] = 1.0, -2.0
    fixed = fixed or {}
    for k, v in fixed.items():
        th0[k] = v
    free = [i for i in range(len(th0)) if i not in fixed]

    def f(x):
        th = th0.copy()
        th[free] = x
        return -(d.loglik(th) - d.penalty(th))

    res = minimize(f, th0[free], method="L-BFGS-B", options={"maxiter": 3000, "maxfun": 200000})
    th = th0.copy()
    th[free] = res.x
    return th


def _team_ids(rows: list[dict]) -> list[str]:
    return sorted({t for r in rows for t in r["teams"]})


def design(rows: list[dict], spec: dict) -> Design:
    return Design(
        rows,
        spec["feats"],
        _team_ids(rows) if spec.get("teams") else None,
        bool(spec.get("interest_team")),
        bool(spec.get("heavy")),
    )


# ---- the selection, the test and the ship ------------------------------------------------------------


def _rows(work: Path, s: int, targets: dict, source: str) -> list[dict]:
    MK_SOURCE["mode"] = source
    try:
        return rows_of(load_season(work, s), targets)["rows"]
    finally:
        MK_SOURCE["mode"] = "walk"


@app.command()
def fit(
    work: Path = typer.Option(..., "--work"), ship: bool = typer.Option(True, "--ship/--no-ship")
) -> None:
    t0 = time.time()
    targets = role_targets(work)
    print("role targets (median squad, 2019-2024):", targets, flush=True)
    # the lots' market price: from the other 2018-2024 auctions for the selection seasons,
    # walk-forward (auctions before only) for the test, from every other auction for the shipped
    # refit (`mk`)
    by_season = {s: _rows(work, s, targets, "mk24" if s in SELECT else "walk") for s in SEASONS}
    ship_rows = {s: _rows(work, s, targets, "mk26") for s in SEASONS}
    for s, rr in by_season.items():
        print(f"{s}: {len(rr)} lots in the likelihood", flush=True)
    report: dict = {"targets": targets, "candidates": {}, "protocol": (
        "candidates declared before any test number; chosen by leave-one-auction-out mean log-likelihood per "
        "lot over 2019-2024; the chosen one fitted on 2019-2024 and scored once on 2025 and 2026; refitted "
        "on 2019-2026 and shipped")}  # fmt: skip
    cache = work / "demand_loao.json"
    done = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    for name, spec in CANDIDATES.items():
        if name in done:
            report["candidates"][name] = done[name]
            continue
        per = {}
        for s in SELECT:
            train = [r for y in SELECT if y != s for r in by_season[y]]
            d = design(train, spec)
            th = fit_design(d)
            ids = d.team_ids
            test = Design(
                by_season[s],
                spec["feats"],
                ids if spec.get("teams") else None,
                bool(spec.get("interest_team")),
            )
            per[s] = float(np.mean(test.loglik(th, per_lot=True)))
        m = float(np.mean(list(per.values())))
        done[name] = {"loao": per, "mean": m}
        report["candidates"][name] = done[name]
        cache.write_text(json.dumps(done, indent=1), encoding="utf-8")
        print(f"{name}: LOAO {m:.4f}  {({k: round(v, 3) for k, v in per.items()})} ({time.time() - t0:.0f}s)",
              flush=True)  # fmt: skip
    chosen = max(report["candidates"], key=lambda k: report["candidates"][k]["mean"])
    report["chosen"] = chosen
    print("chosen:", chosen, flush=True)
    # the test, once: every candidate fitted on 2019-2024, scored on 2025 and 2026
    train = [r for y in SELECT for r in by_season[y]]
    test_tab = {}
    fitted = {}
    for name, spec in CANDIDATES.items():
        d = design(train, spec)
        th = fit_design(d)
        fitted[name] = (d, th)
        row = {}
        for s in TEST:
            t = Design(
                by_season[s],
                spec["feats"],
                d.team_ids if spec.get("teams") else None,
                bool(spec.get("interest_team")),
            )
            row[s] = float(np.mean(t.loglik(th, per_lot=True)))
        test_tab[name] = row
    report["test"] = test_tab
    d, th = fitted[chosen]
    report["params_le2024"] = params_of(d, th)
    print("test (mean log-lik per lot):", json.dumps(test_tab, indent=1), flush=True)
    print("params (2019-2024):", json.dumps(report["params_le2024"], indent=1), flush=True)
    # ship: refit on everything
    spec = CANDIDATES[chosen]
    allrows = [r for y in SEASONS for r in ship_rows[y]]
    d_all = design(allrows, spec)
    th_all = fit_design(d_all, start=th if not spec.get("teams") else None)
    report["params_shipped"] = params_of(d_all, th_all)
    print(
        "params (2019-2026, shipped):", json.dumps(report["params_shipped"], indent=1), flush=True
    )
    (work / "demand_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if ship:
        OUT.write_text(json.dumps({
            "_doc": "The Auction room's fitted bidding (scripts/auction_demand_fit.py; docs/METHODOLOGY.md §7). "
                    "Mirrored as constants in web_parity/auction.py and site/src/lib/auction.ts.",
            "chosen": chosen, "fitted_on": list(SEASONS), "role_targets": targets,
            "params": report["params_shipped"], "params_le2024": report["params_le2024"],
            "loao": report["candidates"], "test": test_tab,
        }, indent=1), encoding="utf-8")  # fmt: skip
        print("wrote", OUT)
    print(f"done in {time.time() - t0:.0f}s")


# ---- round 2 (2026-10-23, after the owner's review of round 1) ----------------------------------------
#
# Round 1 shipped D7; its 2025 stars came out at about a third of their real price (Pant 9.0 against 27,
# while the market price alone says 21.5). Round 2 tests the suspected causes as candidates, declared
# here before any round-2 test number (the round-1 test tables had been seen: this is a second look):
_D7 = ("base", "anchor", "need", "os", "pps", "money", "up", "stage")
CANDIDATES2: dict[str, dict] = {
    "R0 D7 (round 1)": {"feats": _D7, "interest_team": True},
    # (b) a team's bid scales with what the player is worth: bid ∝ market price
    "R1 D7, bid ∝ market price (C = 1)": {"feats": _D7, "interest_team": True, "fixed": {1: 1.0}},
    # (b) the base price, 0.87-correlated with the market price, out of the bid level (kept in whether a team bids)
    "R2 R1 without the base price in the bid level": {
        "feats": tuple(f for f in _D7 if f != "base"), "interest_team": True, "fixed": {1: 1.0}},
    # (c) price formation: a heavy-tailed heat (quiet lots and bidding wars)
    "R3 D7 + a heavy-tailed heat": {"feats": _D7, "interest_team": True, "heavy": True},
    # extrapolation: the market price above the top base price (2 cr) gets its own slope
    "R4 D7 + the market price above 2 cr": {"feats": (*_D7, "hinge"), "interest_team": True},
}  # fmt: skip
# The reality criterion, stated before the round-2 test (validation auctions 2019-2024, each candidate
# fitted on 2019-2024, 150 runs): (i) the real top 10 of each auction inside the simulated 10-90% at least
# as often as the candidate's own simulated top 10 are inside the other runs' range, less 0.15 (a calibrated
# room can't put an auction's dearest lots, picked by their outcome, inside 90% of the time); (ii) the median
# real ÷ simulated median of the real top 10 within 1.5× of the same benchmark; (iii) on the market's own top
# 10 (picked by the prediction), median real ÷ simulated median in 0.8-1.25. Among the candidates passing
# (i)-(iii), the best leave-one-auction-out log-likelihood; if none passes (i)-(ii), those passing (iii).


def reality(seasons: dict, demand: dict, trials: int = 150) -> dict:
    import auction_calibrate as ac

    ins, rat, bins, brat, mrat, allin, cin = [], [], [], [], [], [], []
    for si in seasons.values():
        rep = ac.replay(si, demand, trials)
        m = ac.metrics(si, rep)
        keep = [i for i, r in enumerate(si["avail"]) if r["_price"]]
        S = np.array([rep["price"][i] for i in keep])
        real = np.array(m["real"])
        mk = np.array([float(si["avail"][i]["projected_value"]) for i in keep])
        lo, hi, med = np.quantile(S, 0.1, 1), np.quantile(S, 0.9, 1), np.median(S, 1)
        top = np.argsort(-real)[:10]
        ins += list((real[top] >= lo[top] - 1e-9) & (real[top] <= hi[top] + 1e-9))
        rat += list(real[top] / med[top])
        topm = np.argsort(-mk, kind="stable")[:10]
        mrat += list(real[topm] / med[topm])
        for k in range(0, trials, 5):
            o = np.delete(S, k, 1)
            ps = S[:, k]
            tp = np.argsort(-ps)[:10]
            l2, h2, m2 = np.quantile(o, 0.1, 1), np.quantile(o, 0.9, 1), np.median(o, 1)
            bins += list((ps[tp] >= l2[tp] - 1e-9) & (ps[tp] <= h2[tp] + 1e-9))
            brat += list(ps[tp] / m2[tp])
        allin.append(m["inside_10_90"])
        cin.append(m["inside_10_90_c"])
    r = {
        "top10_inside": float(np.mean(ins)), "top10_ratio": float(np.median(rat)),
        "bench_inside": float(np.mean(bins)), "bench_ratio": float(np.median(brat)),
        "market_top10_ratio": float(np.median(mrat)),
        "inside": float(np.mean(allin)), "inside_contested": float(np.mean(cin)),
    }  # fmt: skip
    r["pass_outcome"] = bool(r["top10_inside"] >= r["bench_inside"] - 0.15
                             and r["top10_ratio"] <= 1.5 * r["bench_ratio"])  # fmt: skip
    r["pass_prediction"] = bool(0.8 <= r["market_top10_ratio"] <= 1.25)
    return r


@app.command()
def round2(
    work: Path = typer.Option(..., "--work"), ship: bool = typer.Option(False, "--ship/--no-ship")
) -> None:
    """Round 2: LOAO + the validation reality criterion → the choice; then the test, once."""
    t0 = time.time()
    targets = json.loads(OUT.read_text(encoding="utf-8"))["role_targets"]
    by = {s: _rows(work, s, targets, "mk24" if s in SELECT else "walk") for s in SEASONS}
    val_seasons = {}
    for s in SELECT:
        MK_SOURCE["mode"] = "mk24"
        val_seasons[s] = load_season(work, s)
    MK_SOURCE["mode"] = "walk"
    cache = work / "round2.json"
    done = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    for name, spec in CANDIDATES2.items():
        fx = {int(k): v for k, v in (spec.get("fixed") or {}).items()}
        res = done.get(name, {})
        if "loao" not in res:
            per = {}
            for s in SELECT:
                d = design([r for y in SELECT if y != s for r in by[y]], spec)
                th = fit_design(d, fixed=fx)
                per[s] = float(np.mean(design(by[s], spec).loglik(th, per_lot=True)))
            res["loao"] = per
            res["mean"] = float(np.mean(list(per.values())))
        if "reality" not in res:
            d = design([r for y in SELECT for r in by[y]], spec)
            th = fit_design(d, fixed=fx)
            res["params_le2024"] = params_of(d, th)
            dem = {k: v for k, v in res["params_le2024"].items() if not isinstance(v, dict)}
            res["reality"] = reality(val_seasons, dem)
        done[name] = res
        cache.write_text(json.dumps(done, indent=1), encoding="utf-8")
        print(name, round(res["mean"], 4), {k: (round(v, 3) if isinstance(v, float) else v)
                                           for k, v in res["reality"].items()}, f"({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
    ok = [
        n
        for n in CANDIDATES2
        if done[n]["reality"]["pass_outcome"] and done[n]["reality"]["pass_prediction"]
    ]
    rule = "(i)-(iii)"
    if not ok:
        ok = [n for n in CANDIDATES2 if done[n]["reality"]["pass_prediction"]]
        rule = "(iii) only: none passes (i)-(ii)"
    if not ok:
        ok = list(CANDIDATES2)
        rule = "none passes: LOAO alone"
    chosen = max(ok, key=lambda n: done[n]["mean"])
    print("passing", rule, ok, "→ chosen:", chosen, flush=True)
    summary = {"candidates": done, "rule": rule, "chosen": chosen}
    if "test" not in done.get("_test", {}):
        import auction_calibrate as ac

        test = {}
        for name, spec in CANDIDATES2.items():
            dem = {k: v for k, v in done[name]["params_le2024"].items() if not isinstance(v, dict)}
            d = design([r for y in SELECT for r in by[y]], spec)
            th = fit_design(d, fixed={int(k): v for k, v in (spec.get("fixed") or {}).items()})
            row = {}
            for s in TEST:
                ll = design(by[s], spec).loglik(th, per_lot=True)
                si = load_season(work, s)
                m = ac.metrics(si, ac.replay(si, dem, 300))
                real, md = np.array(m["real"]), np.array(m["sim_median"])
                lo, hi = np.array(m["sim_p10"]), np.array(m["sim_p90"])
                top = np.argsort(-real)[:10]
                row[s] = {"ll": float(ll.mean()), "ll_feasible": float(ll[ll > -50].mean()),
                          "top10_inside": int(np.sum((real[top] >= lo[top] - 1e-9) & (real[top] <= hi[top] + 1e-9))),
                          "top10_ratio": float(np.median(real[top] / md[top])),
                          **{k: m[k] for k in ("inside_10_90", "inside_10_90_c", "median_ratio_c", "mae_ln",
                                               "mae_ln_c", "top10_sim_ratio", "buyer_hit", "by_band")},
                          "top": [(m["names"][i], m["real"][i], m["sim_median"][i], m["sim_p10"][i], m["sim_p90"][i])
                                  for i in top]}  # fmt: skip
            test[name] = row
            print("TEST", name, {s: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()
                                     if k not in ("by_band", "top")} for s, r in row.items()}, flush=True)  # fmt: skip
        done["_test"] = {"test": test}
        cache.write_text(json.dumps(done, indent=1), encoding="utf-8")
    summary["test"] = done["_test"]["test"]
    (work / "round2_report.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if ship:
        spec = CANDIDATES2[chosen]
        allrows = [r for y in SEASONS for r in _rows(work, y, targets, "mk26")]
        d = design(allrows, spec)
        th = fit_design(d, fixed={int(k): v for k, v in (spec.get("fixed") or {}).items()})
        cfg = json.loads(OUT.read_text(encoding="utf-8"))
        cfg.update({"chosen": chosen, "round": 2, "params": params_of(d, th),
                    "params_le2024": done[chosen]["params_le2024"], "round2": summary})  # fmt: skip
        OUT.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        print("wrote", OUT)
    print(f"done in {time.time() - t0:.0f}s")


def params_of(d: Design, th: np.ndarray) -> dict:
    p = d.unpack(th)
    out = {
        "a": float(p["a"]), "c": float(p["c"]), "sigma": math.exp(float(p["ln_sigma"])),
        "tau": math.exp(float(p["ln_tau"])), "p0": float(p["p0"]), "p1": float(p["p1"]),
        "p2": float(p["p2"]),
    }  # fmt: skip
    for nm in LOT_FEATS + TEAM_FEATS:
        out[nm] = float(p[nm]) if nm in p else 0.0
    for nm in (*TEAM_FEATS, "val"):
        out["i_" + nm] = float(p["i_" + nm]) if "i_" + nm in p else 0.0
    if d.heavy:
        out["heat_q"] = 1.0 / (1.0 + math.exp(-float(p["heat_q"])))
        out["tau2"] = out["tau"] * (1.0 + math.exp(float(p["heat_h"])))
    if d.team_ids:
        out["team_effects"] = {t: float(x) for t, x in zip(d.team_ids, p["team"], strict=True)}
    return out


if __name__ == "__main__":
    _ = ladder_next  # re-exported for the sim scripts
    app()
