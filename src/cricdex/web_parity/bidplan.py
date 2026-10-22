"""Bid plan: the auction bidding-plan optimiser. EXACT mirror of `site/src/lib/bidplan.ts`.

Given a franchise's kept squad and purse left (Keep or release's plan, with the user's own keep /
release calls), the competition rules and the auction pool (free agents plus every player the ten
plans release, each with his value, role, tags and market price), it works out whom to bid for and
how high:

1. **Rivals.** The Auction room's simulator (`auction.one_trial`) runs the other nine franchises,
   each with its own Keep-or-release plan and bidding personality, `trials` times. For every
   player that gives the price a rival would have paid in each run: the price we would have to
   beat (his base price when no rival bid).
2. **Squad strength.** A squad's strength is its best XI's value (runs per 100 balls, summed; at
   most 4 overseas, at least 1 keeper, 5 bowling and 6 batting options, a replacement-level player
   filling any place the squad can't), plus a smaller weight on the next four players (depth),
   minus a penalty for each role need it misses (keepers, openers, death bowlers, spinners, pace).
3. **The bidding rule.** In lot order, bid for a player up to his gain in strength divided by an
   exchange rate λ (runs per crore), within the purse (keeping 0.3 cr for each place still needed
   to reach the squad minimum), the squad maximum and the overseas cap. λ is chosen to maximise the
   expected strength over the rival runs (a sample-average optimisation over a grid of rates).
4. **The plan.** Each target's max bid is his gain to the likely squad (every player landed in at
   least half the runs) divided by λ: the price above which a crore spent on him buys less strength
   than the next-best use of the purse. Per role, a fallback chain gives the next name and his max
   bid if the earlier ones go for more.

Inputs are the exported `keep.json` + `auction_pool.json` (`build_context`), or a context built
from history (`scripts/bidplan_backtest.py`). `test_scripts/test_bidplan_parity.py` runs the
TypeScript on the same inputs and fails if any number differs. The method in plain words:
docs/METHODOLOGY.md §12.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from cricdex.web_parity.auction import (
    IPL_TEAMS_DEFAULT,
    PRICE_CAP,
    auction_lots,
    one_trial,
)
from cricdex.web_parity.keep import cr, evaluate, fmt_num, fsum, player_key, squad_of
from cricdex.web_parity.pricing import price_ceiling, price_tier

# ---- the squad-strength model ---------------------------------------------------------------------

# The best XI: 11 players, at most XI_OVERSEAS overseas, at least one keeper, five bowling options
# (bowlers + all-rounders) and six batting options (batters + keepers + all-rounders).
XI_SIZE = 11
XI_OVERSEAS = 4
XI_MIN_KEEPERS = 1
XI_MIN_BOWLING = 5
XI_MIN_BATTING = 6
# Replacement level (runs per 100 balls above the average IPL ball): what a base-price buy is
# worth, about the median value of the auction pool's players priced at 2 cr or less. A place the
# squad can't fill is filled at this level, and a player below it adds nothing.
REPLACEMENT = -15.0
# Depth: the next DEPTH_N players after the XI count DEPTH_WEIGHT × (value − replacement level).
DEPTH_N = 4
DEPTH_WEIGHT = 0.25
# Each role need missed costs NEED_PENALTY runs per 100 balls of strength.
NEED_PENALTY = 3.0
NEED_ORDER = ["keeper", "opener", "death", "spinner", "pace"]
DEFAULT_NEEDS: dict[str, int] = {"keeper": 2, "opener": 3, "death": 3, "spinner": 3, "pace": 4}
NEED_LABEL = {
    "keeper": "Wicketkeepers",
    "opener": "Openers",
    "death": "Death bowlers",
    "spinner": "Spinners",
    "pace": "Pace bowlers",
}

# ---- the auction assumptions ------------------------------------------------------------------------

# Every franchise's default plan opens at least this many squad places (releasing its lowest-surplus
# Borderline players, Keep or release's `fit_to_rules` order): the median number of players a
# team bought at the 2023, 2024 and 2026 mini auctions (data/curated/ipl_auction_history.json).
# 0 = Keep or release's plan exactly. A player the user decided on is never moved.
OPEN_SLOTS = 8
TRIALS = 200
# The exchange rates tried (runs per 100 balls of strength per crore): 0.25 × 2^(k/4), k = 0 … 24
# (0.25 … 16), written out so Python and the browser use the same numbers to the last digit.
LAMBDA_GRID = [
    0.25, 0.297302, 0.353553, 0.420448, 0.5, 0.594604, 0.707107, 0.840896, 1.0, 1.189207,
    1.414214, 1.681793, 2.0, 2.378414, 2.828427, 3.363586, 4.0, 4.756828, 5.656854, 6.727171,
    8.0, 9.513657, 11.313708, 13.454343, 16.0,
]  # fmt: skip
MIN_SLOT_PRICE = 0.3
# A player is a target when the plan lands him in at least this share of the runs (or you set his
# max bid); "likely" when it lands him in at least half of them.
TARGET_MIN_SHARE = 0.05
LIKELY_SHARE = 0.5
# Rounds of the likely-buys lookahead (the bidding rule's fixed point; usually 2-3 suffice).
LOOKAHEAD_ROUNDS = 4
SLOT_ORDER = ["keeper", "opener", "death", "spinner", "pace", "batter", "all_rounder"]
SLOT_LABEL = {
    "keeper": "Wicketkeeper",
    "opener": "Opener",
    "death": "Death bowler",
    "spinner": "Spinner",
    "pace": "Pace bowler",
    "batter": "Middle-order batter",
    "all_rounder": "All-rounder",
}


# ---- pieces: a player as the strength model sees him ------------------------------------------------


def piece(
    pid: str,
    name: str,
    value: float | None,
    role: str,
    overseas: bool,
    tags: str,
) -> dict[str, Any]:
    """A squad member or candidate for the strength model. An unrated player (no value) counts at
    replacement level."""
    v = REPLACEMENT if value is None else float(value)
    tags = tags or ""
    keeper = role == "keeper" or "k" in tags
    bowl = role in ("bowler", "all_rounder")
    return {
        "id": pid,
        "name": name,
        "v": v,
        "rated": value is not None,
        "role": role,
        "os": bool(overseas),
        "tags": tags,
        "k": keeper,
        "bowl": bowl,
        "bat": role in ("batter", "keeper", "all_rounder"),
        "needs": [
            n
            for n, ok in (
                ("keeper", keeper),
                ("opener", "o" in tags),
                ("death", "d" in tags),
                ("spinner", "s" in tags),
                ("pace", bowl and "s" not in tags),
            )
            if ok
        ],
    }


def _by_value(p: dict) -> tuple:
    return (-p["v"], p["id"])


def best_xi(pieces: list[dict]) -> dict[str, Any]:
    """The best XI, picked greedily: highest value first, skipping a player who would break the
    overseas limit or leave too few places for a keeper, five bowling and six batting options
    (replacement-level players fill any place the squad can't). {xi, ids, fillers, bench}."""
    cands = sorted((p for p in pieces if p["v"] > REPLACEMENT), key=_by_value)
    chosen: list[dict] = []
    bench: list[dict] = []
    k = bw = bt = os_n = 0
    for p in cands:
        if len(chosen) >= XI_SIZE:
            bench.append(p)
            continue
        if p["os"] and os_n >= XI_OVERSEAS:
            bench.append(p)
            continue
        nk = k + (1 if p["k"] else 0)
        nbw = bw + (1 if p["bowl"] else 0)
        nbt = bt + (1 if p["bat"] else 0)
        room = XI_SIZE - len(chosen) - 1
        need_k = max(0, XI_MIN_KEEPERS - nk)
        need_bw = max(0, XI_MIN_BOWLING - nbw)
        need_bt = max(0, XI_MIN_BATTING - nbt)
        # replacement keepers count as batting options too
        if need_bw + max(need_k, need_bt) > room:
            bench.append(p)
            continue
        chosen.append(p)
        k, bw, bt = nk, nbw, nbt
        if p["os"]:
            os_n += 1
    fillers = XI_SIZE - len(chosen)
    xi = fsum([p["v"] for p in chosen]) + fillers * REPLACEMENT
    return {"xi": xi, "ids": [p["id"] for p in chosen], "fillers": fillers, "bench": bench}


def need_counts(pieces: list[dict]) -> dict[str, int]:
    out = dict.fromkeys(NEED_ORDER, 0)
    for p in pieces:
        for n in p["needs"]:
            out[n] += 1
    return out


def strength(pieces: list[dict], needs: dict[str, int]) -> dict[str, Any]:
    """{total, xi, depth, short, counts, ids, fillers}: total = XI + DEPTH_WEIGHT × depth −
    NEED_PENALTY × the role places short of `needs`."""
    b = best_xi(pieces)
    depth = fsum([p["v"] - REPLACEMENT for p in b["bench"][:DEPTH_N]])
    counts = need_counts(pieces)
    short = 0
    for n in NEED_ORDER:
        short += max(0, needs.get(n, 0) - counts[n])
    total = b["xi"] + DEPTH_WEIGHT * depth - NEED_PENALTY * short
    return {
        "total": total,
        "xi": b["xi"],
        "depth": depth,
        "short": short,
        "counts": counts,
        "ids": b["ids"],
        "fillers": b["fillers"],
    }


def upper_gain(p: dict) -> float:
    """A quick ceiling on what one player can add (used only to skip hopeless bids fast):
    2 × (value − replacement level), plus the penalty for every need he could fill."""
    return 2 * max(0.0, p["v"] - REPLACEMENT) + NEED_PENALTY * len(p["needs"])


# ---- the context: our squad, the rivals, the pool -----------------------------------------------------


def _avail_row(r: dict, tags: str, from_team: str | None) -> dict:
    """An auction-pool row (auction.build_pool shape) as a lot: the fields one_trial reads plus
    tags and where he comes from."""
    t = tags or ""
    if r.get("is_overseas") and "x" not in t:
        t += "x"
    out = {
        "cricsheet_id": r["cricsheet_id"],
        "name": r["name"],
        "role": r["role"],
        "is_overseas": bool(r["is_overseas"]),
        "value": r["value"],
        "projected_value": r["projected_value"],
        "p_bought": r.get("p_bought"),
        "base_price": r["base_price"],
        "price_cap": r["price_cap"],
        "tags": t,
        "from_team": from_team,
    }
    if r.get("anchor_price"):
        out["anchor_price"] = r["anchor_price"]
    return out


def _squad_row_as_lot(p: dict) -> dict:
    """A released squad player who isn't in the exported pool: priced as Keep or release priced
    him (market price), base-price band and ceiling from that."""
    price = float(p["price"])
    return {
        "cricsheet_id": p["id"],
        "name": p["name"],
        "role": p["role"],
        "is_overseas": bool(p.get("overseas")),
        "value": p["value"],
        "projected_value": price,
        "p_bought": p.get("p_bought"),
        "base_price": price_tier(price),
        "price_cap": price_ceiling(p.get("target_balls")),
    }


def _lot_order(r: dict) -> tuple:
    return (-r["projected_value"], r["cricsheet_id"])


NO_GAPS = {"keeper": 0, "opener": 0, "death": 0, "spinner": 0, "overseas": 0}


def open_places(players: list[dict], limit: int) -> None:
    """Open squad places the way franchises do before a mini auction: while more than `limit`
    players are kept, release the lowest-valued kept player the user hasn't decided on (an unrated
    one first). Each gets `auto_release` = "open". In place, after Keep or release's `evaluate`."""
    kept = [p for p in players if p["kept"]]
    extra = len(kept) - max(0, limit)
    if extra <= 0:
        return
    movable = sorted(
        (p for p in kept if not p["overridden"]),
        key=lambda p: (p.get("value") is not None, p.get("value") or 0.0, p["key"]),
    )
    for p in movable[:extra]:
        p["kept"] = False
        p["auto_release"] = "open"


def build_context(
    data: dict,
    pool: list[dict],
    team: str,
    decisions: dict[str, str] | None = None,
    purse: float | None = None,
    open_slots: int = OPEN_SLOTS,
    rules: dict | None = None,
    register: list[dict] | None = None,
    personalities: list[dict] | None = None,
    display: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Everything the plan needs, from Keep or release's data.

    `data` = keep.json; `pool` = auction.build_pool(auction_pool.json); `decisions` = our keep /
    release overrides (Keep or release's URL state); `purse` overrides the competition's purse for
    every team; `rules` overrides squad_min / squad_max / overseas_max; `open_slots` = the fewest
    open places each team's plan leaves (OPEN_SLOTS; `open_places`). `register` = the official auction list when
    published: [{"id", "base_price"?}], replacing the pool we infer (free agents + every plan's
    releases) with exactly those players. `display` = {cricsheet id: the name fans use} (the raw
    pool rows' `display_name`); a released squad player keeps his squad name."""
    comp_rules = dict(data["competition"]["rules"])
    if rules:
        comp_rules.update({k: v for k, v in rules.items() if v is not None})
    if purse is not None:
        comp_rules["purse"] = float(purse)
    form = data.get("form")
    pers = {c["team"]: c["personality"] for c in (personalities or IPL_TEAMS_DEFAULT)}
    pool_by_id = {r["cricsheet_id"]: r for r in pool}
    tags_of = data.get("pool_tags") or {}
    shown = display or {}

    ours: dict[str, Any] = {}
    rivals: list[dict] = []
    released: list[dict] = []
    for t in data["teams"]:
        squad = squad_of(data, t)
        # no role targets here: Bid plan has its own needs, so Keep's gap warnings stay out
        res = evaluate(squad, [], comp_rules, decisions if t == team else {}, NO_GAPS, form)
        open_places(res["players"], int(comp_rules["squad_max"]) - int(open_slots))
        kept = [p for p in res["players"] if p["kept"]]
        salary_kept = fsum([float(p["salary"]) for p in kept])
        pieces = [
            piece(p["key"], p["name"], p.get("value"), p["role"], bool(p.get("overseas")),
                  p.get("tags") or "")
            for p in kept
        ]  # fmt: skip
        purse_left = float(comp_rules["purse"]) - salary_kept
        for p in res["players"]:
            if not p["kept"] and p.get("id") and p.get("value") is not None:
                released.append(p)
        if t == team:
            ours = {
                "players": res["players"],
                "kept": pieces,
                "purse_left": purse_left,
                "salary_kept": salary_kept,
                "warnings": res["warnings"],
            }
        else:
            rivals.append(
                {
                    "team": t,
                    "personality": pers.get(t, "Balanced"),
                    "kept": pieces,
                    "purse_left": purse_left,
                }
            )
    if not ours:
        raise ValueError(f"unknown team {team!r}")

    avail: list[dict] = []
    seen: set[str] = set()
    if register is not None:
        rel_by_id = {p["id"]: p for p in released}
        squad_by_id = {p["id"]: p for p in data["players"] if p.get("id")}
        for e in register:
            pid = e["id"]
            if pid in seen:
                continue
            row = None
            if pid in pool_by_id:
                src = squad_by_id.get(pid)
                row = _avail_row(
                    pool_by_id[pid],
                    (src.get("tags") if src else tags_of.get(pid, "")) or "",
                    src["team"] if src else None,
                )
            elif pid in rel_by_id:
                p = rel_by_id[pid]
                row = _avail_row(_squad_row_as_lot(p), p.get("tags") or "", p["team"])
            if row is not None and pid in squad_by_id and squad_by_id[pid].get("salary"):
                row["anchor_price"] = float(squad_by_id[pid]["salary"])
            if row is None:
                continue
            if e.get("base_price") is not None:
                row["base_price"] = float(e["base_price"])
            seen.add(pid)
            avail.append(row)
    else:
        for r in pool:
            if r.get("team"):
                continue
            seen.add(r["cricsheet_id"])
            avail.append(_avail_row(r, tags_of.get(r["cricsheet_id"], ""), None))
        for p in released:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            src = pool_by_id.get(p["id"])
            row = _avail_row(src if src else _squad_row_as_lot(p), p.get("tags") or "", p["team"])
            row["anchor_price"] = float(p["salary"])  # rivals remember what he was paid
            avail.append(row)
    squad_names = {p["id"]: p["name"] for p in data["players"] if p.get("id")}
    for row in avail:
        pid = row["cricsheet_id"]
        row["name"] = shown.get(pid) or squad_names.get(pid) or row["name"]
    avail.sort(key=_lot_order)
    return {
        "team": team,
        "rules": comp_rules,
        "cycle": data["competition"].get("cycle") or "mini",
        "open_slots": int(open_slots),
        "squad": ours["players"],
        "kept": ours["kept"],
        "purse_left": ours["purse_left"],
        "salary_kept": ours["salary_kept"],
        "warnings": ours["warnings"],
        "rivals": rivals,
        "available": avail,
        "register": register is not None,
    }


# ---- step 1: what a rival would pay ------------------------------------------------------------------


def rival_prices(ctx: dict, trials: int = TRIALS) -> list[list[float]]:
    """For each available player (ctx["available"] order) and each run: the price we would have to
    beat, i.e. the highest rival's bid × 1.02 (the simulator's clearing step), clamped to the
    27 cr record and his price ceiling, at least his base price; his base price when no rival bid
    (or he wasn't among the simulator's lots). Runs t = 0 … trials − 1 use the Auction room's
    seeds (1000 + 7919 t)."""
    rules = ctx["rules"]
    purse = float(rules["purse"])
    bases = []
    for r in ctx["rivals"]:
        retained = [
            {"cricsheet_id": p["id"], "role": p["role"], "is_overseas": p["os"]} for p in r["kept"]
        ]
        bases.append(
            {
                "team": r["team"],
                "personality": r["personality"],
                "retained": retained,
                "retain_spend": purse - r["purse_left"],
                "retain_overseas": sum(1 for p in r["kept"] if p["os"]),
            }
        )
    avail = ctx["available"]
    index = {p["cricsheet_id"]: i for i, p in enumerate(avail)}
    lots = auction_lots(avail)
    opts = {
        "purse": purse,
        "squad_size": int(rules["squad_max"]),
        "overseas_cap": int(rules["overseas_max"]),
        "mode": ctx.get("cycle") or "mini",  # the calibrated bid level for this auction type
    }
    out = [[float(p["base_price"])] * trials for p in avail]
    for t in range(trials):

        def on_sale(player: dict, team_i: int, best_bid: float, price: float, _t: int = t) -> None:
            i = index[player["cricsheet_id"]]
            beat = min(PRICE_CAP, player["price_cap"], best_bid * 1.02)
            out[i][_t] = max(float(player["base_price"]), beat)

        one_trial(bases, lots, opts, 1000 + t * 7919, on_sale)
    return out


# ---- step 2: the bidding rule over the rival runs ---------------------------------------------------


class _Gains:
    """Strength of a squad (our kept players + a set of candidate indices) and each candidate's
    gain on it, cached: many runs share their states."""

    def __init__(self, kept: list[dict], cands: list[dict], needs: dict[str, int]):
        self.kept = kept
        self.cands = cands
        self.needs = needs
        self.memo: dict[str, dict] = {}

    def state(self, idx: list[int]) -> dict:
        key = ",".join(str(i) for i in sorted(idx))
        st = self.memo.get(key)
        if st is None:
            pieces = self.kept + [self.cands[i] for i in sorted(idx)]
            st = {"pieces": pieces, "total": strength(pieces, self.needs)["total"], "g": {}}
            self.memo[key] = st
        return st

    def gain(self, st: dict, i: int) -> float:
        g = st["g"].get(i)
        if g is None:
            g = strength(st["pieces"] + [self.cands[i]], self.needs)["total"] - st["total"]
            st["g"][i] = g
        return g


def _replay(
    ctx: dict,
    cands: list[dict],
    prices: list[float],
    lam: float,
    overrides: dict[str, float],
    gains: _Gains,
    future: list[int],
) -> dict:
    """One run of the bidding rule: lots in pool order; for each, bid up to (his gain / λ) or the
    user's max bid; buy when that reaches the price to beat and the purse, squad and overseas room
    allow. His gain is measured on the squad so far plus the likely buys still to come (`future`,
    the plan's likely buys in lot order), so an early lot isn't overpaid while a cheaper substitute
    is due later; a likely buy that was lost leaves the squad, so its substitutes bid higher.
    `prices[i]` = that run's price to beat for candidate i."""
    rules = ctx["rules"]
    sq_max = int(rules["squad_max"])
    sq_min = int(rules["squad_min"])
    os_max = int(rules["overseas_max"])
    kept = ctx["kept"]
    n = len(kept)
    os_n = sum(1 for p in kept if p["os"])
    left = float(ctx["purse_left"])
    bought: list[int] = []
    paid: list[float] = []
    for i, c in enumerate(cands):
        if n >= sq_max:
            break
        if c["os"] and os_n >= os_max:
            continue
        if c["own"] and c["id"] not in overrides:
            continue  # a player we release isn't bought back (see `reconsider`)
        r = prices[i]
        reserve = max(0, sq_min - n - 1) * MIN_SLOT_PRICE
        if r > left - reserve:
            continue
        if c["id"] in overrides:
            cap = overrides[c["id"]]
        else:
            if c["ub"] < lam * r:
                continue
            ahead = bought + [j for j in future if j > i]
            cap = gains.gain(gains.state(ahead), i) / lam
        if cap >= r and cap > 0:
            bought.append(i)
            paid.append(r)
            left -= r
            n += 1
            if c["os"]:
                os_n += 1
    st = gains.state(bought)
    return {"bought": bought, "paid": paid, "spend": fsum(paid), "total": st["total"], "st": st}


def _search(ctx, cands, by_run, over, gains, future) -> tuple[float, list[dict]]:
    """The exchange rate whose bidding rule gives the highest mean strength over the runs (ties:
    the higher rate, i.e. the cheaper plan), and the curve of mean strength by rate."""
    trials = len(by_run)
    best_lam = LAMBDA_GRID[-1]
    best_mean = -math.inf
    curve = []
    for lam in reversed(LAMBDA_GRID):
        tot = fsum([_replay(ctx, cands, by_run[t], lam, over, gains, future)["total"]
                    for t in range(trials)])  # fmt: skip
        mean = tot / trials if trials else 0.0
        curve.append({"lam": lam, "strength": mean})
        if mean > best_mean:
            best_mean = mean
            best_lam = lam
    curve.reverse()
    return best_lam, curve


def _likely(ctx: dict, cands: list[dict], land: list[int], price_sum: list[float],
            trials: int) -> list[int]:  # fmt: skip
    """The likely buys: every player landed in at least half the runs, in lot order, while there's
    squad and overseas room and purse at his average price."""
    rules = ctx["rules"]
    out: list[int] = []
    n_sq = len(ctx["kept"])
    os_n = sum(1 for p in ctx["kept"] if p["os"])
    left = float(ctx["purse_left"])
    for i, c in enumerate(cands):
        if trials == 0 or land[i] / trials < LIKELY_SHARE:
            continue
        exp_paid = price_sum[i] / land[i]
        if n_sq >= int(rules["squad_max"]) or (c["os"] and os_n >= int(rules["overseas_max"])):
            continue
        if exp_paid > left:
            continue
        out.append(i)
        n_sq += 1
        left -= exp_paid
        if c["os"]:
            os_n += 1
    return out


def _cands(ctx: dict) -> list[dict]:
    out = []
    for r in ctx["available"]:
        p = piece(r["cricsheet_id"], r["name"], r["value"], r["role"], r["is_overseas"], r["tags"])
        p["ub"] = upper_gain(p)
        p["own"] = r.get("from_team") is not None and r.get("from_team") == ctx["team"]
        out.append(p)
    return out


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    return s[(len(s) - 1) // 2]


def _q90(xs: list[float]) -> float:
    """The price that is enough in 9 runs of 10 (the 90th percentile, nearest rank)."""
    s = sorted(xs)
    return s[max(0, math.ceil(0.9 * len(s)) - 1)]


def _slot_of(p: dict) -> str:
    for n in ("keeper", "opener", "death", "spinner"):
        if n in p["needs"]:
            return n
    if p["role"] == "bowler":
        return "pace"
    if p["role"] == "all_rounder":
        return "all_rounder"
    return "batter"


def plan(
    ctx: dict,
    needs: dict[str, int] | None = None,
    overrides: dict[str, float] | None = None,
    trials: int = TRIALS,
    prices: list[list[float]] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """The bidding plan for ctx["team"]. `needs` overrides DEFAULT_NEEDS; `overrides` =
    {player id: max bid in cr} (0 = never bid); `prices` = rival_prices(ctx, trials) if already
    computed."""
    tgt = dict(DEFAULT_NEEDS)
    for k, v in (needs or {}).items():
        if k in tgt and isinstance(v, int | float) and v >= 0:
            tgt[k] = int(v)
    over = {k: float(v) for k, v in (overrides or {}).items() if v is not None and v >= 0}
    if prices is None:
        prices = rival_prices(ctx, trials)
    trials = len(prices[0]) if prices else trials
    cands = _cands(ctx)
    gains = _Gains(ctx["kept"], cands, tgt)
    by_run = [[prices[i][t] for i in range(len(cands))] for t in range(trials)]

    # round 1 bids on the squad so far; each later round also counts the previous round's likely
    # buys still to come, until the likely buys stop changing (LOOKAHEAD_ROUNDS at most)
    future: list[int] = []
    rounds = 0
    while True:
        rounds += 1
        lam, curve = _search(ctx, cands, by_run, over, gains, future)
        land = [0] * len(cands)
        price_sum = [0.0] * len(cands)
        runs = []
        for t in range(trials):
            rr = _replay(ctx, cands, by_run[t], lam, over, gains, future)
            runs.append(rr)
            for i, pr in zip(rr["bought"], rr["paid"], strict=True):
                land[i] += 1
                price_sum[i] += pr
        likely = _likely(ctx, cands, land, price_sum, trials)
        if likely == future or rounds >= LOOKAHEAD_ROUNDS:
            break
        future = likely
        if progress:
            progress(rounds, LOOKAHEAD_ROUNDS)
    converged = likely == future

    spends: list[float] = []
    totals: list[float] = []
    xis: list[float] = []
    sizes: list[int] = []
    need_met = dict.fromkeys(NEED_ORDER, 0)
    for rr in runs:
        spends.append(rr["spend"])
        totals.append(rr["total"])
        s = strength(rr["st"]["pieces"], tgt)
        xis.append(s["xi"])
        sizes.append(len(rr["st"]["pieces"]))
        for n in NEED_ORDER:
            if s["counts"][n] >= tgt[n]:
                need_met[n] += 1

    rules = ctx["rules"]
    sq_max = int(rules["squad_max"])
    os_max = int(rules["overseas_max"])
    likely_set = set(likely)
    likely_pieces = ctx["kept"] + [cands[i] for i in likely]

    exp_paid = {i: price_sum[i] / land[i] for i in likely}
    sq_min = int(rules["squad_min"])

    def gain_without(drop: set[int], i: int) -> float:
        base = ctx["kept"] + [cands[j] for j in likely if j not in drop]
        return strength(base + [cands[i]], tgt)["total"] - strength(base, tgt)["total"]

    def max_bid(drop: set[int], i: int) -> tuple[float, float, bool]:
        """(max bid, gain, purse-bound): his gain on the likely squad without `drop`, over λ;
        at most the 27 cr record and what the purse leaves after the rest of the likely buys
        at their average prices (keeping 0.3 cr a place to reach the squad minimum)."""
        g = gain_without(drop, i)
        rest = [j for j in likely if j not in drop]
        reserve = max(0, sq_min - len(ctx["kept"]) - len(rest) - 1) * MIN_SLOT_PRICE
        budget = float(ctx["purse_left"]) - fsum([exp_paid[j] for j in rest]) - reserve
        by_value = max(0.0, g / lam)
        mb = min(PRICE_CAP, max(0.0, budget), by_value)
        return mb, g, mb < by_value

    targets = []
    for i, c in enumerate(cands):
        share = land[i] / trials if trials else 0.0
        if share < TARGET_MIN_SHARE and not (c["id"] in over and over[c["id"]] > 0):
            continue
        mb, g, bound = max_bid({i}, i)
        if c["id"] in over:
            mb, bound = over[c["id"]], False
        ps = prices[i]
        under = [x for x in ps if x <= mb]
        p_le = len(under) / trials if trials else 0.0
        mean_under = fsum(under) / len(under) if under else 0.0
        row = cands[i]
        a = ctx["available"][i]
        targets.append(
            {
                "i": i,
                "id": c["id"],
                "name": c["name"],
                "role": c["role"],
                "overseas": c["os"],
                "tags": c["tags"],
                "value": a["value"],
                "price": a["projected_value"],
                "p_bought": a.get("p_bought"),
                "base_price": a["base_price"],
                "from_team": a.get("from_team"),
                "slot": _slot_of(row),
                "gain": g,
                "max_bid": mb,
                "purse_bound": bound,
                "override": c["id"] in over,
                "expected_price": _median(ps),
                "enough_90": _q90(ps),
                "p_le_max": p_le,
                "p_land": share,
                "avg_paid": price_sum[i] / land[i] if land[i] else 0.0,
                "likely": i in likely_set,
                "net": p_le * (g - lam * mean_under),
            }
        )
    targets.sort(key=lambda x: (-x["net"], x["id"]))
    for k, x in enumerate(targets):
        x["priority"] = k + 1

    # fallback chains: per slot, its targets in priority order; each one's max bid if every
    # earlier name in the chain has gone for more than his
    chains = []
    for slot in SLOT_ORDER:
        members = [x for x in targets if x["slot"] == slot]
        if not members:
            continue
        steps = []
        lost: set[int] = set()
        for x in members:
            lost.add(x["i"])
            cap = x["max_bid"] if x["override"] else max_bid(lost, x["i"])[0]
            steps.append({"id": x["id"], "name": x["name"], "max_bid": cap,
                          "p_le_max": _share_le(prices[x["i"]], cap)})  # fmt: skip
        chains.append({"slot": slot, "label": SLOT_LABEL[slot], "steps": steps})

    # our own releases are never bought back; one worth more to the likely squad than his salary is
    # flagged instead: keeping him beats buying a replacement
    salary_of = {p.get("id"): p for p in ctx.get("squad") or [] if p.get("id")}
    reconsider = []
    for i, c in enumerate(cands):
        if not c["own"] or c["id"] not in salary_of or not c["rated"]:
            continue
        g = gain_without({i}, i)
        worth = min(PRICE_CAP, max(0.0, g / lam))
        sq = salary_of[c["id"]]
        sal = float(sq["salary"])
        if worth >= sal:
            reconsider.append({"id": c["id"], "name": sq["name"], "salary": sal, "worth": worth,
                               "gain": g, "auto_release": sq.get("auto_release")})  # fmt: skip
    reconsider.sort(key=lambda x: (-(x["worth"] - x["salary"]), x["id"]))

    before = strength(ctx["kept"], tgt)
    after = strength(likely_pieces, tgt)
    missing = []
    for n in NEED_ORDER:
        have = after["counts"][n]
        if have < tgt[n]:
            missing.append({"need": n, "label": NEED_LABEL[n], "target": tgt[n], "have": have})
    for x in targets:
        del x["i"]
    return {
        "team": ctx["team"],
        "lam": lam,
        "curve": curve,
        "rounds": rounds,
        "converged": converged,
        "trials": trials,
        "needs": tgt,
        "purse_left": ctx["purse_left"],
        "slots_open": sq_max - len(ctx["kept"]),
        "overseas_open": os_max - sum(1 for p in ctx["kept"] if p["os"]),
        "targets": targets,
        "chains": chains,
        "likely": [
            {"id": cands[i]["id"], "name": cands[i]["name"], "price": price_sum[i] / land[i]}
            for i in likely
        ],
        "likely_spend": fsum([price_sum[i] / land[i] for i in likely]),
        "before": _summary(before),
        "after_likely": _summary(after),
        "mean_strength": fsum(totals) / trials if trials else before["total"],
        "mean_xi": fsum(xis) / trials if trials else before["xi"],
        "mean_spend": fsum(spends) / trials if trials else 0.0,
        "mean_squad": fsum([float(s) for s in sizes]) / trials
        if trials
        else float(len(ctx["kept"])),
        "need_met": {n: (need_met[n] / trials if trials else 0.0) for n in NEED_ORDER},
        "missing": missing,
        "reconsider": reconsider,
    }


def _share_le(xs: list[float], cap: float) -> float:
    return sum(1 for x in xs if x <= cap) / len(xs) if xs else 0.0


def _summary(s: dict) -> dict:
    return {
        "total": s["total"],
        "xi": s["xi"],
        "depth": s["depth"],
        "short": s["short"],
        "counts": s["counts"],
        "xi_ids": s["ids"],
        "fillers": s["fillers"],
    }


# ---- output helpers --------------------------------------------------------------------------------


def chain_text(chain: dict) -> str:
    """'Phil Salt up to 14 cr → if he goes above that: Ryan Rickelton up to 8 cr → …'."""
    parts = []
    for k, s in enumerate(chain["steps"]):
        if k == 0:
            parts.append(f"{s['name']} up to {cr(s['max_bid'])} cr")
        else:
            parts.append(
                f"if {chain['steps'][k - 1]['name']} goes above that: {s['name']} up to {cr(s['max_bid'])} cr"
            )
    return " → ".join(parts)


def to_csv_rows(res: dict) -> list[list[str]]:
    """The targets table as CSV rows (the page's "Export CSV" writes the same columns)."""
    head = [
        "priority", "player", "role", "slot", "overseas", "from_team", "value", "market_price_cr",
        "p_bought", "expected_price_cr", "enough_90_cr", "max_bid_cr", "your_max_bid", "p_land_at_max_bid",
        "p_land_in_plan", "gain_runs", "likely",
    ]  # fmt: skip
    rows = [head]
    for x in res["targets"]:
        rows.append(
            [
                str(x["priority"]),
                x["name"],
                x["role"],
                SLOT_LABEL[x["slot"]],
                "yes" if x["overseas"] else "no",
                x.get("from_team") or "",
                fmt_num(x["value"], 1),
                fmt_num(x["price"], 2),
                "" if x.get("p_bought") is None else fmt_num(x["p_bought"], 2),
                fmt_num(x["expected_price"], 2),
                fmt_num(x["enough_90"], 2),
                fmt_num(x["max_bid"], 2),
                "yes" if x["override"] else "no",
                fmt_num(x["p_le_max"], 2),
                fmt_num(x["p_land"], 2),
                fmt_num(x["gain"], 1),
                "yes" if x["likely"] else "no",
            ]
        )
    return rows


def keys_of(data: dict, team: str) -> dict[str, str]:
    """{player key: name} for a team's squad (the keep / release overrides use these keys)."""
    return {player_key(p): p["name"] for p in squad_of(data, team)}


def follow_plan(
    ctx: dict, res: dict, prices: list[float], overrides: dict[str, float] | None = None
) -> dict[str, Any]:
    """Play a finished plan's bidding rule (its λ, its likely buys as the lookahead) against one
    set of prices, e.g. what each player really sold for. {bought: [ids], paid, spend, strength}.
    Python only: `scripts/bidplan_backtest.py` uses it to replay real auctions (the page and the
    CLI never need it, so there is no TS twin)."""
    cands = _cands(ctx)
    at = {c["id"]: i for i, c in enumerate(cands)}
    future = [at[x["id"]] for x in res["likely"] if x["id"] in at]
    over = {k: float(v) for k, v in (overrides or {}).items() if v is not None and v >= 0}
    gains = _Gains(ctx["kept"], cands, res["needs"])
    rr = _replay(ctx, cands, prices, res["lam"], over, gains, future)
    return {
        "bought": [cands[i]["id"] for i in rr["bought"]],
        "paid": rr["paid"],
        "spend": rr["spend"],
        "strength": strength(rr["st"]["pieces"], res["needs"]),
    }
