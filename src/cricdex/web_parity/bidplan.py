"""Bid plan: the auction bidding-plan optimiser. EXACT mirror of `site/src/lib/bidplan.ts`.

Given a franchise's kept squad and purse left (Keep or release's plan, with the user's own keep /
release calls), the competition rules and the auction pool (free agents plus every player the ten
plans release, each with his value, role, tags and market price), it works out whom to bid for and
how high:

1. **Rivals.** The Auction room's simulator (`auction.one_trial`) runs the other nine franchises,
   each with its own Keep-or-release plan, bidding by the room's fitted demand model, `trials`
   times. For every player that gives the price a rival would have paid in each run: the price we
   would have to beat (the next ladder step above the winning rival's bid; his base price when no
   rival bid).
2. **Squad strength.** A squad's strength is its best XI's expected contribution in runs per match
   above replacement (each player's batting and bowling at the balls he gets a match × his P(plays),
   scout/playing_time.py; the XI's balls held to a side's balls per innings; at most 4 overseas, at
   least 1 keeper, 5 bowling and 6 batting options, a replacement-level player filling any place the
   squad can't), plus the bench filling the matches the XI misses (Σ (1 − P(plays)) appearances, best
   bench contribution first). Role needs are reported, not scored.
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

import bisect
import math
from collections.abc import Callable
from typing import Any

from cricdex.web_parity.auction import (
    auction_lots,
    ladder_next,
    one_trial,
    open_squad_places,
)
from cricdex.web_parity.keep import (
    cr,
    evaluate,
    fmt_num,
    fsum,
    player_key,
    purse_charged,
    squad_of,
)
from cricdex.web_parity.pricing import price_tier

# ---- the squad-strength model ---------------------------------------------------------------------

# The best XI: 11 players, at most XI_OVERSEAS overseas, at least one keeper, five bowling options
# (bowlers + all-rounders) and six batting options (batters + keepers + all-rounders).
XI_SIZE = 11
XI_OVERSEAS = 4
XI_MIN_KEEPERS = 1
XI_MIN_BOWLING = 5
XI_MIN_BATTING = 6
# Strength is in runs per match above replacement (since 2026-10-22; audit items 4, 6): each player's
# `contrib` = (batting value − replacement for his slot) × balls faced a match / 100 + (bowling value −
# replacement for his group) × balls bowled a match / 100 (scout/playing_time.py, METHODOLOGY §6c).
# A place the squad can't fill is filled at replacement level (0), and a player at or below it never
# plays. Until then strength added per-100-ball values across the XI (a No. 7 weighted like an
# opener, a four-over bowler like a 25-ball batter) with a replacement level of −15.
REPLACEMENT = 0.0
# A side's legal balls per innings (config/playing_time_model.json `balls_per_innings`, the IPL
# 2023-2026): an XI whose expected balls faced (or bowled) add up to more is scaled down to it, every
# member alike, so eight openers can't each face 25 balls.
TEAM_BALLS = 115.0
# Depth (since 2026-10-23, audit item 8): an XI member counts P(plays) × his contribution, so his side
# misses him in (1 − P) of its matches; those appearances, Σ over the XI of (1 − P), go to the bench in
# order of the contribution a match each makes when he plays (at most one appearance a match each, never
# below replacement). The depth weight is the playing-time model's P(plays) (section 6c), not a hand-set
# 0.25 on the next four. Role needs (keepers, openers, death, spin, pace) are targets the plan reports
# against (`need_met`, `missing`); they no longer cost strength (the hand-set 0.63 a place is gone): the
# XI's rules (a keeper, five bowling and six batting options, four overseas) carry the balance.
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
# The exchange rates tried (runs per match of strength per crore): 0.05 × 2^(k/4), k = 0 … 24
# (0.05 … 3.2; the earlier per-100-ball grid 0.25 … 16 at the same 0.209 conversion), written out so
# Python and the browser use the same numbers to the last digit.
LAMBDA_GRID = [
    0.05, 0.05946, 0.070711, 0.08409, 0.1, 0.118921, 0.141421, 0.168179, 0.2, 0.237841,
    0.282843, 0.336359, 0.4, 0.475683, 0.565685, 0.672717, 0.8, 0.951366, 1.13137, 1.34543,
    1.6, 1.90273, 2.26274, 2.69087, 3.2,
]  # fmt: skip
MIN_SLOT_PRICE = 0.3
# How a crore left unspent is valued (ROADMAP I17b; METHODOLOGY §12 step 4):
# - "auction": what it can still buy from the later lots at their expected prices (`_MoneyValue`); 0
#   at the end of the auction (no carry-over into the season, replacement fees outside the cap);
# - "market": the rivals' runs per crore in the same runs (`rival_runs`), the rule of 2026-10-26;
# - "none": nothing, one λ for the whole auction (the rule until 2026-10-26).
MONEY_RULES = ("auction", "market", "none")
MONEY = "auction"
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


def contrib_parts(r: dict) -> tuple[float, float, float, float, float] | None:
    """(batting part, bowling part, balls faced, balls bowled, P(plays)) of a row's contribution per
    match (`contrib_bat`, `contrib_bowl`, `balls_faced`, `balls_bowled`, `p_play`; a missing P(plays)
    counts as 1); None when any of the first four is missing."""
    ks = ("contrib_bat", "contrib_bowl", "balls_faced", "balls_bowled")
    if any(r.get(k) is None for k in ks):
        return None
    p = r.get("p_play")
    return (float(r["contrib_bat"]), float(r["contrib_bowl"]), float(r["balls_faced"]),
            float(r["balls_bowled"]), 1.0 if p is None else float(p))  # fmt: skip


def piece(
    pid: str,
    name: str,
    contrib: float | None,
    role: str,
    overseas: bool,
    tags: str,
    parts: tuple | None = None,
) -> dict[str, Any]:
    """A squad member or candidate for the strength model: `contrib` = runs per match above
    replacement; `parts` = (batting part, bowling part, balls faced, balls bowled[, P(plays)]) of it.
    He counts at his **expected** contribution: each part and each ball count × P(plays) (section 6c:
    a squad player's chance in his squad, a free agent's chance of playing an IPL match at all), so a
    40-year-old free agent franchises stopped picking, or a player who sat out last season, adds what
    players like him have actually added. Without `parts` the contribution counts whole and outside
    the XI's balls. An unrated player (no contribution) counts at replacement level."""
    v = REPLACEMENT if contrib is None else float(contrib)
    pp = 1.0
    if parts is not None and contrib is not None:
        cb, cw, fb, wb = parts[:4]
        pp = float(parts[4]) if len(parts) > 4 else 1.0
        cb, cw, fb, wb = pp * cb, pp * cw, pp * fb, pp * wb
        v = cb + cw
    else:
        cb, cw, fb, wb = v, 0.0, 0.0, 0.0
    tags = tags or ""
    keeper = role == "keeper" or "k" in tags
    bowl = role in ("bowler", "all_rounder")
    return {
        "id": pid,
        "name": name,
        "v": v,
        # P(plays) and the contribution a match he plays (v ÷ P): the bench fill (`strength`)
        "pp": pp,
        "c": v / pp if pp > 0 else 0.0,
        # the most bench appearances a match he can give (`bench_fill`): 1 for a squad player (his
        # P(plays) is the chance he's picked ahead of the others, so he plays when one is missing);
        # an auction candidate's is set to his P(plays) in `_cands`
        "cap": 1.0,
        "cb": cb,
        "cw": cw,
        "fb": fb,
        "wb": wb,
        "rated": contrib is not None,
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
    """The best XI, picked greedily: highest contribution first, skipping a player who would break
    the overseas limit or leave too few places for a keeper, five bowling and six batting options
    (replacement-level players fill any place the squad can't). Its value is the members' batting
    parts × min(1, TEAM_BALLS ÷ their balls faced) plus their bowling parts × min(1, TEAM_BALLS ÷
    their balls bowled): an XI can't face or bowl more than a side's innings. {xi, ids, fillers,
    bench}."""
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
    faced = fsum([p["fb"] for p in chosen])
    bowled = fsum([p["wb"] for p in chosen])
    sb = TEAM_BALLS / faced if faced > TEAM_BALLS else 1.0
    sw = TEAM_BALLS / bowled if bowled > TEAM_BALLS else 1.0
    xi = sb * fsum([p["cb"] for p in chosen]) + sw * fsum([p["cw"] for p in chosen])
    xi += fillers * REPLACEMENT
    return {"xi": xi, "ids": [p["id"] for p in chosen], "fillers": fillers, "bench": bench}


def need_counts(pieces: list[dict]) -> dict[str, int]:
    out = dict.fromkeys(NEED_ORDER, 0)
    for p in pieces:
        for n in p["needs"]:
            out[n] += 1
    return out


def bench_fill(xi_ids: list[str], pieces: list[dict], bench: list[dict]) -> float:
    """The bench's expected runs a match: the XI's missed appearances, Σ (1 − P(plays)) over its
    members, filled by the bench in order of the contribution a match each makes when he plays (ties
    by id), at most `cap` appearances a match each (1 for a squad player, an auction candidate's
    P(plays): a free agent players like him rarely play for adds what they actually add, on the bench
    as in the XI), players above replacement only. Until 2026-10-23 every bench player gave a whole
    appearance, so a 40-year-old free agent with P(plays) 0.04 filled the XI's absences at his full
    contribution and topped the targets (audit item 8, follow-up)."""
    ids = set(xi_ids)
    miss = fsum([1.0 - min(1.0, max(0.0, p["pp"])) for p in pieces if p["id"] in ids])
    out = 0.0
    for p in sorted((q for q in bench if q["c"] > REPLACEMENT), key=lambda q: (-q["c"], q["id"])):
        if miss <= 0.0:
            break
        cap = min(1.0, max(0.0, p.get("cap", 1.0)))  # a piece without one is a squad player
        a = miss if miss < cap else cap
        out += a * p["c"]
        miss -= a
    return out


def strength(pieces: list[dict], needs: dict[str, int]) -> dict[str, Any]:
    """{total, xi, depth, short, counts, ids, fillers}: total = XI (each at P(plays) × contribution) +
    the bench filling the XI's missed appearances (`bench_fill`). `short` = role places short of
    `needs`, reported, not scored."""
    b = best_xi(pieces)
    depth = bench_fill(b["ids"], pieces, b["bench"])
    counts = need_counts(pieces)
    short = 0
    for n in NEED_ORDER:
        short += max(0, needs.get(n, 0) - counts[n])
    total = b["xi"] + depth
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
    2 × (his contribution a match he plays − replacement level)."""
    return 2 * max(0.0, p["c"] - REPLACEMENT)


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
        "tags": t,
        "from_team": from_team,
        **{k: r.get(k) for k in CONTRIB_KEYS},
    }
    if r.get("anchor_price"):
        out["anchor_price"] = r["anchor_price"]
    if r.get("capped") is not None:
        out["capped"] = r["capped"]
    if r.get("prior_share"):
        out["prior_share"] = r["prior_share"]
    return out


def _squad_row_as_lot(p: dict) -> dict:
    """A released squad player who isn't in the exported pool: priced as Keep or release priced
    him (market price), base-price band from that."""
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
        **{k: p.get(k) for k in CONTRIB_KEYS},
    }


# the playing-time fields a lot carries for the strength model (export_site PT_KEYS)
CONTRIB_KEYS = ("contrib", "contrib_bat", "contrib_bowl", "balls_faced", "balls_bowled", "p_play")


def _lot_order(r: dict) -> tuple:
    return (-r["projected_value"], r["cricsheet_id"])


NO_GAPS = {"keeper": 0, "opener": 0, "death": 0, "spinner": 0, "overseas": 0}


def open_places(players: list[dict], limit: int) -> None:
    """Open squad places the way franchises do before a mini auction: while more than `limit`
    players are kept, release the kept player with the lowest contribution per match the user hasn't
    decided on (an unrated one first). Each gets `auto_release` = "open". In place, after Keep or
    release's `evaluate`."""
    kept = [p for p in players if p["kept"]]
    extra = len(kept) - max(0, limit)
    if extra <= 0:
        return
    movable = sorted(
        (p for p in kept if not p["overridden"]),
        key=lambda p: (p.get("contrib") is not None, p.get("contrib") or 0.0, p["key"]),
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
            piece(p["key"], p["name"], p.get("contrib"), p["role"], bool(p.get("overseas")),
                  p.get("tags") or "", contrib_parts(p))
            for p in kept
        ]  # fmt: skip
        # what the kept players cost the purse (salaries; 2025 retentions by the retention slabs)
        purse_left = float(comp_rules["purse"]) - purse_charged(kept, comp_rules)
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
    # a squad player in the auction is a free agent there: his chance of playing is the free-agent
    # model's (`p_play_free`), not his chance in the squad that let him go
    free_p = {p["id"]: p.get("p_play_free") for p in data["players"] if p.get("id")}
    for row in avail:
        pid = row["cricsheet_id"]
        if free_p.get(pid) is not None:
            row["p_play"] = free_p[pid]
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
    """The price we would have to beat, per available player and run (`rival_runs`'s "prices")."""
    return rival_runs(ctx, trials)["prices"]


def rival_runs(ctx: dict, trials: int = TRIALS) -> dict[str, Any]:
    """The rivals' auction, `trials` times. {"prices", "rate", "rival_gain", "rival_spend"}:

    - prices: for each available player (ctx["available"] order) and each run, the price we would
      have to beat, i.e. the next ladder step above the winning rival's bid (a rival bids at most his
      spendable purse), at least his base price; his base price when no rival bid (or he wasn't among
      the simulator's lots).
    - rate: the **market's runs per crore**, what the rivals' crores bought in these runs: Σ over
      rivals and runs of the strength their buys added to their own squad (`strength`, each lot at
      his free-agent P(plays), as ours are counted) ÷ Σ what they paid. It is the value of a crore we
      leave unspent (`plan`): the rate at which this market turns money into squad strength, from
      the fitted demand model's own buys, not a set number (ROADMAP I17b).

    The rivals bid by the Auction room's fitted demand model. Runs t = 0 … trials − 1 use the
    Auction room's seeds (1000 + 7919 t). `ctx["demand"]` (optional) overrides the demand model
    (the replays' out-of-time fit)."""
    rules = ctx["rules"]
    purse = float(rules["purse"])
    sq_max = int(rules["squad_max"])
    bases = []
    for r in ctx["rivals"]:
        retained = [
            {"cricsheet_id": p["id"], "role": p["role"], "is_overseas": p["os"], "v": p["v"]}
            for p in r["kept"]
        ]
        bases.append(
            {
                "team": r["team"],
                "retained": retained,
                "retain_spend": purse - r["purse_left"],
                "retain_overseas": sum(1 for p in r["kept"] if p["os"]),
            }
        )
    avail = ctx["available"]
    index = {p["cricsheet_id"]: i for i, p in enumerate(avail)}
    cycle = ctx.get("cycle") or "mini"
    # the lots: as many as real shortlists hold for the auction's open places (ours included)
    places = open_squad_places(bases, sq_max) + max(0, sq_max - len(ctx["kept"]))
    lots = avail if ctx.get("all_lots") else auction_lots(avail, places, cycle)
    opts = {
        "purse": purse,
        "squad_size": sq_max,
        "squad_min": int(rules.get("squad_min", 18)),
        "overseas_cap": int(rules["overseas_max"]),
        "mode": cycle,
    }
    if ctx.get("demand"):
        opts["demand"] = ctx["demand"]
    if ctx.get("min_base"):
        opts["min_base"] = float(ctx["min_base"])
    out = [[float(p["base_price"])] * trials for p in avail]
    lot_pieces = _cands(ctx)
    base_total = [strength(r["kept"], DEFAULT_NEEDS)["total"] for r in ctx["rivals"]]
    gain_sum = 0.0
    spend_sum = 0.0
    for t in range(trials):
        buys: list[list[int]] = [[] for _ in bases]
        paid: list[list[float]] = [[] for _ in bases]

        def on_sale(
            player: dict,
            team_i: int,
            best_bid: float,
            price: float,
            _t: int = t,
            _buys: list[list[int]] = buys,
            _paid: list[list[float]] = paid,
        ) -> None:
            i = index[player["cricsheet_id"]]
            beat = ladder_next(best_bid)
            out[i][_t] = max(float(player["base_price"]), beat)
            _buys[team_i].append(i)
            _paid[team_i].append(float(price))

        one_trial(bases, lots, opts, 1000 + t * 7919, on_sale)
        for k, r in enumerate(ctx["rivals"]):
            if not buys[k]:
                continue
            after = strength(r["kept"] + [lot_pieces[i] for i in buys[k]], DEFAULT_NEEDS)["total"]
            gain_sum += after - base_total[k]
            spend_sum += fsum(paid[k])
    rate = gain_sum / spend_sum if spend_sum > 0 else 0.0
    return {"prices": out, "rate": rate, "rival_gain": gain_sum, "rival_spend": spend_sum}


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


class _MoneyValue:
    """What a crore and a squad place are still worth at each lot (since 2026-10-27, ROADMAP I17b):
    what they can buy from the lots still to come, at their expected prices.

    Money left after an IPL auction buys nothing for the season being planned. A replacement
    player's fee can't exceed the fee of the player he replaces, and it sits outside the salary
    cap. Unspent purse only carries into the next auction through the cap (purse = cap − contracts),
    and only within a cycle. So the later lots are ranked by gain ÷ expected price: each lot's gain
    is measured on the plan's likely squad, which gives diminishing returns, and the expected price
    is the rivals' median price to beat, from the demand model. The money and the places left are
    filled down that ranking.
    - If the **money** runs out first, a crore is worth the ratio of the first lot it no longer
      covers (λ), and a place costs nothing.
    - If the **places** run out first, a crore is worth 0, and a place is worth the smallest gain
      among the lots that fill them: the one a buy now would push out (`slot`).
    - If neither runs out, both are worth 0. That is always so at the last lot.
    A lot is worth buying when gain − slot > 0, and up to (gain − slot) ÷ λ, or up to the purse when
    λ = 0. Overseas places are not tracked in the ranking."""

    def __init__(self, cands: list[dict], gains: _Gains, future: list[int],
                 expected: list[float]):  # fmt: skip
        base = gains.state(future)
        fut = set(future)
        items = []
        for j, c in enumerate(cands):
            if c["own"] or c["ub"] <= 0 or expected[j] <= 0:
                continue
            if j in fut:
                g = gains.gain(gains.state([k for k in future if k != j]), j)
            else:
                g = gains.gain(base, j)
            if g > 0:
                items.append((g / expected[j], j, expected[j], g))
        items.sort(key=lambda x: (-x[0], x[1]))
        self.items = items
        # suffix lists: for lot i, the ranked lots after it (cumulative cost, ratio, running min gain)
        self._suffix: dict[int, tuple[list[float], list[float], list[float]]] = {}

    def _suf(self, i: int) -> tuple[list[float], list[float], list[float]]:
        got = self._suffix.get(i)
        if got is None:
            cum, rat, gmin = [], [], []
            t = 0.0
            m = math.inf
            for r, j, e, g in self.items:
                if j > i:
                    t += e
                    m = m if m < g else g
                    cum.append(t)
                    rat.append(r)
                    gmin.append(m)
            got = (cum, rat, gmin)
            self._suffix[i] = got
        return got

    def value(self, i: int, money: float, room: int,
              skip: set[int] | None = None) -> tuple[float, float]:  # fmt: skip
        """(λ, slot): what a crore and a squad place are worth after lot i (`i` = −1: before every
        lot) given `money` crores and `room` places for the later lots; `skip` = lots not counted
        (already planned)."""
        if skip:
            return self._value_skip(i, money, room, skip)
        if room <= 0:
            return 0.0, 0.0
        cum, rat, gmin = self._suf(i)
        k = bisect.bisect_right(cum, money + 1e-9)  # lots the money covers, in rank order
        if k >= room and room <= len(cum):
            return 0.0, gmin[room - 1]
        if k < len(cum):
            return rat[k], 0.0
        return 0.0, 0.0

    def _value_skip(self, i: int, money: float, room: int, skip: set[int]) -> tuple[float, float]:
        if room <= 0:
            return 0.0, 0.0
        t = 0.0
        k = 0
        m = math.inf
        for r, j, e, g in self.items:
            if j <= i or j in skip:
                continue
            if t + e > money + 1e-9:
                return r, 0.0
            t += e
            k += 1
            m = m if m < g else g
            if k >= room:
                return 0.0, m
        return 0.0, 0.0


def _cap(g: float, lam: float, slot: float) -> float:
    """The most a lot is worth paying: (gain − the place's worth) ÷ a crore's worth; the purse when a
    crore is worth nothing; 0 when the place is worth more than he adds."""
    net = g - slot
    if net <= 0:
        return 0.0
    return net / lam if lam > 0 else math.inf


def _replay(
    ctx: dict,
    cands: list[dict],
    prices: list[float],
    lam: float,
    overrides: dict[str, float],
    gains: _Gains,
    future: list[int],
    mv: _MoneyValue | None = None,
) -> dict:
    """One run of the bidding rule: lots in pool order; for each, bid up to (his gain / λ) or the
    user's max bid; buy when that reaches the price to beat and the purse, squad and overseas room
    allow. His gain is measured on the squad so far plus the likely buys still to come (`future`,
    the plan's likely buys in lot order), so an early lot isn't overpaid while a cheaper substitute
    is due later; a likely buy that was lost leaves the squad, so its substitutes bid higher.
    `prices[i]` = that run's price to beat for candidate i. With `mv` (the shipped rule since
    2026-10-27), λ at each lot is what a crore can still buy from the lots after it (`_MoneyValue`),
    given the money and places left in this run; 0 (bid up to what the purse allows) when the money
    covers every later lot worth buying."""
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
            lam_i, slot_i = (
                (lam, 0.0) if mv is None else mv.value(i, left - reserve, sq_max - n - 1)
            )
            if c["ub"] <= slot_i or c["ub"] < lam_i * r + slot_i:
                continue
            ahead = bought + [j for j in future if j > i]
            cap = _cap(gains.gain(gains.state(ahead), i), lam_i, slot_i)
        if cap >= r and cap > 0:
            bought.append(i)
            paid.append(r)
            left -= r
            n += 1
            if c["os"]:
                os_n += 1
    st = gains.state(bought)
    return {"bought": bought, "paid": paid, "spend": fsum(paid), "total": st["total"], "st": st}


def _search(ctx, cands, by_run, over, gains, future, rate: float) -> tuple[float, list[dict]]:
    """The exchange rate whose bidding rule gives the highest mean **value** over the runs: squad
    strength plus the purse left unspent at the market's runs per crore (`rate`, `rival_runs`), so
    a crore kept is worth what the market turns a crore into (ties: the higher rate, i.e. the
    cheaper plan). Until 2026-10-26 an unspent crore counted for nothing, so where few targets were
    left λ fell to the bottom of its grid and the max bids ran far above what rivals pay (ROADMAP
    I17b). Returns λ and the curve of mean strength and value by rate."""
    trials = len(by_run)
    best_lam = LAMBDA_GRID[-1]
    best_mean = -math.inf
    curve = []
    left = float(ctx["purse_left"])
    for lam in reversed(LAMBDA_GRID):
        runs = [_replay(ctx, cands, by_run[t], lam, over, gains, future) for t in range(trials)]
        tot = fsum([r["total"] for r in runs])
        val = fsum([r["total"] + rate * (left - r["spend"]) for r in runs])
        mean = tot / trials if trials else 0.0
        mval = val / trials if trials else 0.0
        curve.append({"lam": lam, "strength": mean, "value": mval})
        if mval > best_mean:
            best_mean = mval
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
        p = piece(r["cricsheet_id"], r["name"], r.get("contrib"), r["role"], r["is_overseas"],
                  r["tags"], contrib_parts(r))  # fmt: skip
        # a candidate gives the bench at most his P(plays) appearances a match (`bench_fill`)
        p["cap"] = p["pp"]
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
    rate: float | None = None,
    money: str = MONEY,
) -> dict[str, Any]:
    """The bidding plan for ctx["team"]. `needs` overrides DEFAULT_NEEDS; `overrides` =
    {player id: max bid in cr} (0 = never bid); `prices` / `rate` = rival_runs(ctx, trials)'s
    "prices" and "rate" if already computed (a missing rate is worked out from the same runs).
    `money` = how an unspent crore is valued (MONEY_RULES; the replays compare them)."""
    tgt = dict(DEFAULT_NEEDS)
    for k, v in (needs or {}).items():
        if k in tgt and isinstance(v, int | float) and v >= 0:
            tgt[k] = int(v)
    over = {k: float(v) for k, v in (overrides or {}).items() if v is not None and v >= 0}
    if prices is None:
        rr0 = rival_runs(ctx, trials)
        prices, rate = rr0["prices"], rr0["rate"]
    trials = len(prices[0]) if prices else trials
    if money == "none":
        rate = 0.0
    elif money == "market" and rate is None:
        rate = rival_runs(ctx, trials)["rate"]
    cands = _cands(ctx)
    expected = [_median(ps) for ps in prices]
    rules = ctx["rules"]
    sq_max = int(rules["squad_max"])
    sq_min = int(rules["squad_min"])
    reserve0 = max(0, sq_min - len(ctx["kept"])) * MIN_SLOT_PRICE
    gains = _Gains(ctx["kept"], cands, tgt)
    by_run = [[prices[i][t] for i in range(len(cands))] for t in range(trials)]

    # round 1 bids on the squad so far; each later round also counts the previous round's likely
    # buys still to come, until the likely buys stop changing (LOOKAHEAD_ROUNDS at most)
    future: list[int] = []
    rounds = 0
    while True:
        rounds += 1
        mv = None
        if money == "auction":
            mv = _MoneyValue(cands, gains, future, expected)
            lam = mv.value(-1, float(ctx["purse_left"]) - reserve0, sq_max - len(ctx["kept"]))[0]
            curve = []
        else:
            lam, curve = _search(ctx, cands, by_run, over, gains, future, rate)
        land = [0] * len(cands)
        price_sum = [0.0] * len(cands)
        runs = []
        for t in range(trials):
            rr = _replay(ctx, cands, by_run[t], lam, over, gains, future, mv)
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

    os_max = int(rules["overseas_max"])
    likely_set = set(likely)
    # the money value on the final likely squad (it differs from the last round's when the lookahead
    # stopped before converging)
    mv_final = _MoneyValue(cands, gains, likely, expected) if money == "auction" else None
    likely_pieces = ctx["kept"] + [cands[i] for i in likely]

    exp_paid = {i: price_sum[i] / land[i] for i in likely}

    def gain_without(drop: set[int], i: int) -> float:
        base = ctx["kept"] + [cands[j] for j in likely if j not in drop]
        return strength(base + [cands[i]], tgt)["total"] - strength(base, tgt)["total"]

    def lam_at(drop: set[int], i: int) -> tuple[float, float]:
        """(λ, slot) for lot i: the global rate, or (money rule "auction") what a crore and a place
        left after the rest of the likely buys could still buy from the lots after him."""
        if mv_final is None:
            return lam, 0.0
        rest = [j for j in likely if j not in drop]
        reserve = max(0, sq_min - len(ctx["kept"]) - len(rest) - 1) * MIN_SLOT_PRICE
        budget = float(ctx["purse_left"]) - fsum([exp_paid[j] for j in rest]) - reserve
        room = sq_max - len(ctx["kept"]) - len(rest) - 1
        return mv_final.value(i, budget, room, set(rest) | drop)

    def max_bid(drop: set[int], i: int) -> tuple[float, float, bool]:
        """(max bid, gain, purse-bound): his gain on the likely squad without `drop`, over λ (λ = 0:
        nothing later is worth the money, so the purse is the limit); at most what the purse leaves
        after the rest of the likely buys at their average prices (keeping 0.3 cr a place to reach
        the squad minimum)."""
        g = gain_without(drop, i)
        rest = [j for j in likely if j not in drop]
        reserve = max(0, sq_min - len(ctx["kept"]) - len(rest) - 1) * MIN_SLOT_PRICE
        budget = float(ctx["purse_left"]) - fsum([exp_paid[j] for j in rest]) - reserve
        li, slot = lam_at(drop, i)
        by_value = _cap(g, li, slot)
        mb = min(max(0.0, budget), by_value)
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
                "net": p_le * (g - lam_at({i}, i)[1] - lam_at({i}, i)[0] * mean_under),
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
        worth, g, _b = max_bid({i}, i)
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
        # what a crore left unspent is worth at the start (runs a match per crore)
        "purse_rate": lam if money == "auction" else rate,
        "money": money,
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
