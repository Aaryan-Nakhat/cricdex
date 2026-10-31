"""Keep or release: the franchise retention calculator. EXACT mirror of `site/src/lib/keep.ts`.

For every player in a franchise's squad it gives the chance a franchise keeps a player like him at
the retention deadline (`keep_probability`: a logistic model of what franchises actually did at every
deadline 2018-2026, fitted and backtested by scripts/keep_backtest.py, config/keep_model.json), from
his market price against what keeping him costs, his three-season Form forecast, his ties to the
franchise (captain, seasons there, home-grown) and his status (capped Indian, overseas, age, IPL
balls, a buy at the last auction), and recommends Keep, Release or Toss-up with a one-line
reason. For the squad it adds up the purse left after the
kept salaries, the open slots, the role gaps (keepers, openers, death bowlers, spinners, overseas)
and what filling each gap from the current auction pool would cost.

Inputs are the exported `keep.json` (squads, salaries, values, tags, rules) and `auction_pool.json`
(the free agents); the rules (purse, squad size, overseas cap) come from `config/competitions.toml`
through that export. `test_scripts/test_keep_parity.py` runs the TypeScript on the same inputs and
fails if any number or sentence differs. The method in plain words: docs/METHODOLOGY.md §10.
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from cricdesk.web_parity.pricing import PRICE_TIERS, est_value, has_market_inputs, market_price

# The default plan keeps a player when the chance a franchise keeps a player like him is at least
# KEEP_CALL (the backtest's decision rule: more likely kept than not). Within BORDER_BAND of it the
# call is shown as Toss-up (a close call either way); above, Keep; below, Release.
KEEP_CALL = 0.5
BORDER_BAND = 0.15
# The cheapest a squad slot can be filled for (the lowest base-price band, cr).
MIN_SLOT_PRICE = PRICE_TIERS[0]

# Role needs a squad is checked against (editable on the page and with --need on the CLI).
# Overseas defaults to the overseas players the squad has now (at most the overseas cap).
DEFAULT_NEEDS: dict[str, int] = {"keeper": 2, "opener": 3, "death": 3, "spinner": 3}
TAG_ORDER = ["keeper", "opener", "death", "spinner", "overseas"]
TAG_LETTER = {"keeper": "k", "opener": "o", "death": "d", "spinner": "s", "overseas": "x"}
TAG_LABEL = {
    "keeper": "Wicketkeepers",
    "opener": "Openers",
    "death": "Death bowlers",
    "spinner": "Spinners",
    "overseas": "Overseas",
}


# ---- formatting shared with keep.ts (identical rounding: half away from zero on the scaled value)


def fmt_num(x: float, d: int = 1) -> str:
    """`x` to `d` decimals, rounding half up on |x| (the TS does exactly the same arithmetic)."""
    n = math.floor(abs(x) * 10**d + 0.5 + 1e-9)
    s = str(n)
    if d > 0:
        s = s.rjust(d + 1, "0")
        s = s[:-d] + "." + s[-d:]
    return ("-" if x < 0 and n != 0 else "") + s


def cr(x: float) -> str:
    """A crore amount: two decimals below 1 cr (0.30, 0.75), one above (13.3), no trailing .0."""
    s = fmt_num(x, 2 if abs(x) < 1 else 1)
    if s.endswith(".0"):
        s = s[:-2]
    return "0" if s == "0.00" else s


def cr_exact(x: float) -> str:
    """A salary as written: up to two decimals, trailing zeros dropped (13.25, 0.3, 18)."""
    s = fmt_num(x, 2)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fsum(xs) -> float:
    """Left-to-right float sum, as JS `reduce` does (Python 3.12's `sum` compensates, which can
    differ in the last bit)."""
    t = 0.0
    for x in xs:
        t += x
    return t


# ---- per player ---------------------------------------------------------------------------------


def has_tag(p: dict, tag: str) -> bool:
    return TAG_LETTER[tag] in (p.get("tags") or "")


FORECAST_FLAG = {
    "hold": "holds",
    "improve": "improves",
    "hold_then_decline": "holds, then declines",
    "decline": "declines",
}


def signed(x: float) -> str:
    """ "+5" / "-3" / "0", rounded half up (as JavaScript's Math.round)."""
    r = math.floor(x + 0.5)
    return "0" if r == 0 else (f"+{r}" if r > 0 else str(r))


def forecast_note(p: dict) -> str:
    """The "3-season outlook" (Form forecast, METHODOLOGY §11): the three medians, the shape and
    the chance he is still a regular in the third season. Empty without a forecast."""
    f = p.get("forecast")
    if not f:
        return ""
    s = f["seasons"]
    meds = " / ".join(signed(m) for m in f["median"])
    pr = math.floor(100 * f["p_regular_last"] + 0.5)
    return (
        f"{meds} ({s[0]}-{str(s[-1])[2:]}) · {FORECAST_FLAG.get(f['flag'], f['flag'])} · "
        f"{pr}% a regular in {s[-1]}"
    )


def outlook(p: dict) -> str:
    """His age and the Form forecast's shape (METHODOLOGY §11), no rule of thumb."""
    age = p.get("age")
    a = "Age unknown" if age is None else f"{math.floor(age)} years old"
    f = p.get("forecast")
    if not f:
        return f"{a}; too few balls for a forecast."
    return f"{a}; the Form forecast {FORECAST_FLAG.get(f['flag'], f['flag'])}."


def form_note(p: dict, form: dict | None) -> str:
    """Last season in plain numbers: strike rate or economy against that season's league."""
    f = p.get("form")
    if not f or not form:
        return ""
    bits: list[str] = []
    bat, bowl = f.get("bat"), f.get("bowl")
    role = p.get("role")
    show_bat = bat and bat[0] >= 30 and role != "bowler"
    show_bowl = bowl and bowl[0] >= 30 and role != "batter" and role != "keeper"
    if show_bat:
        sr = 100 * bat[1] / bat[0]
        bits.append(f"SR {fmt_num(sr, 0)} v {fmt_num(form['bat_sr'], 0)} ({bat[0]} balls)")
    if show_bowl:
        econ = 6 * bowl[1] / bowl[0]
        bits.append(
            f"econ {fmt_num(econ, 1)} v {fmt_num(form['bowl_econ'], 1)}, "
            f"{bowl[2]} wkts ({bowl[0]} balls)"
        )
    if not bits:
        return ""
    return f"{form['season']}: " + "; ".join(bits)


def captain_label(p: dict) -> str | None:
    """The IPL sides he captained last season ("RCB"), from the export's `captain_teams`, or None
    (the "Captain" badge; captaincy is in the market price, scout/identity/captains.py)."""
    teams = p.get("captain_teams") or []
    return " / ".join(teams) if teams else None


# A rating that rests at least this much on a league whose data has stopped (SMAT on Cricsheet ends
# in Dec 2024) says so in the reason (issue I7).
STALE_REASON_MIN = 0.1


def stale_sentence(p: dict) -> str:
    """ " 85% of his rating rests on SMAT data to Dec 2024 (stale)." or "" (below STALE_REASON_MIN
    or no stale league). From the export's `stale_share` / `stale_note`. Mirror of keep.ts."""
    share = p.get("stale_share") or 0.0
    note = p.get("stale_note")
    if not note or share < STALE_REASON_MIN:
        return ""
    return f" {math.floor(100 * share + 0.5)}% of his rating rests on {note} (stale)."


# An uncapped Indian bought at the last auction for more than the upper quartile of players like him:
# franchises bid on domestic form our data doesn't cover (the auction follows the season's SMAT, which
# Cricsheet stops at Dec 2024, and state T20 leagues it never had), so his market price is no judgement
# of what he is worth and "should they?" is left open (the owner's reality check, 2026-10-29: Prashant
# Veer and Kartik Sharma, 14.2 cr each, priced about 2). Mirror of keep.ts `formUnseen`.
FORM_UNSEEN_SENTENCE = (
    " Bought for {paid} cr at the last auction, above anything players like him fetch: franchises bid "
    "on domestic form our data doesn't have (SMAT on Cricsheet ends Dec 2024), so the price is not a "
    "judgement of him."
)


def form_unseen(p: dict, upper: float | None) -> bool:
    """Bought at the last auction (a sale, not a retention) as an uncapped Indian, for more than the
    upper quartile of what players like him fetch."""
    return (
        upper is not None
        and not p.get("overseas")
        and not (p.get("intl_caps") or 0)
        and p.get("acquired") == "auction"
        and p.get("prior_years") == 1
        and not p.get("prior_retained")
        and float(p["salary"]) > upper
    )


# A squad player with no ball-by-ball record anywhere (no Cricsheet match): shown in place of his
# value, and his price is the market model's prior for a player like him (issue I6).
NO_DATA_LABEL = "no match data — priced from the market"


def no_data_kind(p: dict) -> str:
    """Who the market prior is for, in words: "an overseas player" / "a capped Indian" / "an
    uncapped Indian" (from the row's `overseas` and `intl_caps`)."""
    if p.get("overseas"):
        return "an overseas player"
    return "a capped Indian" if (p.get("intl_caps") or 0) > 0 else "an uncapped Indian"


# ---- what keeping a player costs the purse ----------------------------------------------------------
#
# `retained_cost = "salary"`: his contract salary. `retained_cost = "slabs"`: a player retained at the
# cycle's mega auction (`slab_holder` "capped" / "uncapped", from the squads file) is charged by the
# retention slabs instead: the team's slab holders together cost the first n capped slabs (18, 14, 11,
# 18, 14 cr in 2025-27) plus the uncapped slab (4 cr) per uncapped one, or their salaries if those
# add up to more (the KKR / RCB arithmetic of the 2025 retentions; it reproduces every team's
# published 2025 and 2026 purse). Everyone else costs his salary. METHODOLOGY §10.


def uses_slabs(rules: dict[str, Any]) -> bool:
    return rules.get("retained_cost") == "slabs"


def slab_charge(holders: list[dict], rules: dict[str, Any]) -> float:
    """What a team's kept slab holders cost the purse together: max(Σ the first n capped slabs + the
    uncapped slab × n uncapped, Σ their salaries). A capped holder past the end of the slab list costs
    his salary (can't happen under the 2025-27 rules: at most 5 capped). Mirror of `slabCharge`."""
    slabs = rules.get("retention_slabs") or []
    u = float(rules.get("uncapped_retention_slab") or 0.0)
    total = 0.0
    sal = 0.0
    i = 0
    for p in holders:
        if p.get("slab_holder") == "capped":
            total += float(slabs[i]) if i < len(slabs) else float(p["salary"])
            i += 1
    for p in holders:
        if p.get("slab_holder") == "uncapped":
            total += u
    for p in holders:
        sal += float(p["salary"])
    return max(total, sal)


def purse_charged(kept: list[dict], rules: dict[str, Any]) -> float:
    """What the kept players cost the purse: their salaries, with the slab holders charged together
    by `slab_charge` when the cycle charges slabs. Mirror of `purseCharged`."""
    if not uses_slabs(rules):
        return fsum(float(p["salary"]) for p in kept)
    holders = [p for p in kept if p.get("slab_holder")]
    rest = fsum(float(p["salary"]) for p in kept if not p.get("slab_holder"))
    return rest + (slab_charge(holders, rules) if holders else 0.0)


def retention_costs(squad: list[dict], rules: dict[str, Any]) -> dict[str, float]:
    """player_key → what keeping him costs the purse: his salary, or for a slab holder what releasing
    him alone would free (the team's slab charge with every holder kept, less the charge without
    him). With the slabs counted in order, releasing any capped holder frees the last capped slab in
    use (or his salary, when the salaries are what the purse counts). Mirror of `retentionCosts`."""
    out = {player_key(p): float(p["salary"]) for p in squad}
    if not uses_slabs(rules):
        return out
    holders = [p for p in squad if p.get("slab_holder")]
    if not holders:
        return out
    full = slab_charge(holders, rules)
    for p in holders:
        k = player_key(p)
        out[k] = full - slab_charge([q for q in holders if player_key(q) != k], rules)
    return out


def cost_sentence(p: dict, cost: float) -> str:
    """ " Keeping him costs 15 cr of purse, not his 21 cr salary: ..." for a slab holder whose cost
    differs from his salary, else ""."""
    salary = float(p["salary"])
    if not p.get("slab_holder") or abs(cost - salary) < 0.005:
        return ""
    return (
        f" One of {p.get('team')}'s 2025 retentions, charged to the purse at the retention slabs: "
        f"keeping him costs {cr(cost)} cr, not his {cr_exact(salary)} cr salary."
    )


# ---- the chance a franchise keeps him ----------------------------------------------------------------

_KEEP_MODEL_PATHS = (
    Path(__file__).resolve().parents[3] / "config" / "keep_model.json",
    Path(__file__).resolve().parents[1] / "keep_model.json",  # the copy shipped in the package
)


@lru_cache(maxsize=4)
def load_keep_model(path: str | None = None) -> dict | None:
    """The fitted retention model ($CRICDESK_KEEP_MODEL, else config/keep_model.json, else the package
    copy); None when there is none (every call is then Toss-up)."""
    cands = [Path(path)] if path else []
    env = os.environ.get("CRICDESK_KEEP_MODEL")
    if env:
        cands.append(Path(env))
    cands += list(_KEEP_MODEL_PATHS)
    for c in cands:
        if c.exists():
            return json.loads(c.read_text(encoding="utf-8"))
    return None


def keep_features(
    market: float,
    cost: float,
    mega: bool,
    forecast_avg3: float | None,
    forecast_p_regular: float | None,
    captain_here: bool,
    seasons_here: int,
    home_grown: bool,
    capped_indian: bool,
    overseas: bool,
    age: float | None,
    ipl_balls: float | None,
    bought_prev: bool,
    p_play: float | None = None,
    contrib: float | None = None,
    mega_retained: bool = False,
    matches_last: int | None = None,
) -> dict[str, float]:
    """The retention model's inputs (scripts/keep_backtest.py fits it on the same function):
    ln(market price / what keeping him costs), ln(cost), the mega-auction flag, the 3-season Form
    forecast (average / 10, the chance he is a regular in its third season, a no-forecast flag),
    captain of this franchise last season, ln(1 + IPL seasons played for it), home-grown (his first
    IPL side), capped Indian, overseas, age ((age − 28) / 5 and (age − 33)+ / 3), ln(1 + IPL balls)
    / 5, bought at the last auction, mega × the price ratio, his playing time (METHODOLOGY §6c):
    P(plays a match) in this squad, P × his contribution per match (runs above replacement) and a flag
    when either is missing, in a mini year whether this franchise retained him at the cycle's
    mega auction, and his IPL matches last season (/ 14, at most 1, and a flag for none; unknown counts
    as none). Mirror of `keepFeatures` in keep.ts."""
    ml = max(matches_last or 0, 0)
    c = cost if cost and cost > 0 else 1e-3
    lr = math.log(max(market, 1e-3) / c)
    mg = 1.0 if mega else 0.0
    return {
        "log_ratio": lr,
        "mega": mg,
        "forecast": (forecast_avg3 / 10.0) if forecast_avg3 is not None else 0.0,
        "forecast_regular": forecast_p_regular if forecast_p_regular is not None else 0.0,
        "no_forecast": 0.0 if forecast_avg3 is not None else 1.0,
        "captain_here": 1.0 if captain_here else 0.0,
        "seasons_here": math.log1p(max(seasons_here or 0, 0)),
        "home_grown": 1.0 if home_grown else 0.0,
        "capped_indian": 1.0 if capped_indian else 0.0,
        "overseas": 1.0 if overseas else 0.0,
        "age": ((age - 28.0) / 5.0) if age is not None else 0.0,
        "age_over_33": (max(0.0, age - 33.0) / 3.0) if age is not None else 0.0,
        "ipl_balls": math.log1p(max(ipl_balls or 0.0, 0.0)) / 5.0,
        "bought_prev": 1.0 if bought_prev else 0.0,
        "log_cost": math.log(c),
        "mega_x_log_ratio": mg * lr,
        "p_play": p_play if p_play is not None and contrib is not None else 0.0,
        "play_value": p_play * contrib if p_play is not None and contrib is not None else 0.0,
        "no_play": 0.0 if p_play is not None and contrib is not None else 1.0,
        "mega_retained": 1.0 if mega_retained and not mega else 0.0,
        "played_last": min(ml / 14.0, 1.0),
        "none_last": 1.0 if ml == 0 else 0.0,
    }


def keep_probability(f: dict[str, float], model: dict) -> float:
    """The chance a franchise keeps him: σ(intercept + Σ coef × feature), summed in the model's
    order, then, when the model carries one for the cycle, its recalibration σ(a + b × that sum)
    (keep_backtest.py: Platt, kept only if it lowers the held-out log loss). Mirror of
    `keepProbability` in keep.ts."""
    t = float(model["intercept"])
    for k, c in model["coef"].items():
        t += float(c) * f[k]
    cal = (model.get("calibration") or {}).get("mega" if f.get("mega") else "mini")
    if cal:
        t = float(cal["a"]) + float(cal["b"]) * t
    return 1.0 / (1.0 + math.exp(-t))


def call_of(p_keep: float) -> str:
    """Keep / Toss-up / Release from the chance he is kept (KEEP_CALL ± BORDER_BAND)."""
    if p_keep >= KEEP_CALL + BORDER_BAND:
        return "keep"
    if p_keep < KEEP_CALL - BORDER_BAND:
        return "release"
    return "borderline"


# ---- should they keep him? (cost-aware, separate from the fitted call) ------------------------------
#
# The call above is what franchises do (fitted on their real decisions). In a mini year it hardly
# weighs the cost: +0.141 on ln(price / cost) and +0.139 on ln(cost) nearly cancel, so a dear
# retention looks as likely as a cheap one (METHODOLOGY §10). This is the other question, read
# straight from the market price: is he worth what keeping him costs?
# "yes" when the median price of players like him at the auction is at least the cost (buying a
# player like him would cost as much); "no" when even the upper quartile (the dearer quarter of
# players like him) is below the cost; "close" in between (about the market price's typical error,
# a factor of 2). None when he has no price. Mirror of `shouldOf` in keep.ts.
SHOULD_LABEL = {"yes": "Yes", "close": "Close", "no": "No"}


def should_of(price: float | None, upper: float | None, cost: float) -> str | None:
    """ "yes" / "close" / "no": is he worth his retention cost at the auction's prices?"""
    if price is None:
        return None
    if price >= cost:
        return "yes"
    if upper is not None and upper < cost:
        return "no"
    return "close"


def _ties(p: dict) -> list[str]:
    team = p.get("team") or ""
    out = []
    if team and team in (p.get("captain_teams") or []):
        out.append(f"captained {team} last season")
    if p.get("home_grown"):
        out.append("home-grown")
    n = int(p.get("seasons_here") or 0)
    if n >= 1:
        out.append(f"{n} season{'' if n == 1 else 's'} with {team}")
    return out


def assess(p: dict, form: dict | None = None, cost: float | None = None) -> dict[str, Any]:
    """One player's numbers and recommendation. `p` is a keep.json squad row; `cost` is what keeping
    him costs the purse (`retention_costs`; his salary when not given)."""
    salary = float(p["salary"]) if cost is None else float(cost)
    value = p.get("value")
    out: dict[str, Any] = {
        "price": None,
        "price_central": None,
        "onfield": None,
        "p_bought": None,
        "surplus": None,
        "p_keep": None,
        "default_keep": True,
        "outlook": outlook(p),
        "form_note": form_note(p, form),
        "forecast_note": forecast_note(p),
        "forecast_avg3": (p.get("forecast") or {}).get("avg3"),
        "captain": captain_label(p),
        "cost": salary,
        "should": None,
        "form_unseen": False,
    }
    out["no_data"] = False
    mkt = has_market_inputs(p)
    lead = ""
    if value is None:
        if not mkt:
            out["rec"] = "borderline"
            out["reason"] = (
                f"Not enough balls in our data to rate him: decide on scouting (he costs {cr_exact(salary)} cr)."
            ) + cost_sentence(p, salary)
            return out
        # no ball-by-ball record at all: a sourced prior, never a made-up rating. The market model
        # prices "a player like him" from what is known without match data (overseas or not, caps,
        # age, no IPL record)
        mk = market_price(p)
        price, central, onfield, p_bought = mk["price"], mk["high"], None, None
        out["no_data"] = True
        # an auction price well above the prior is market evidence our data can't see: say so
        # instead of calling him overpaid
        above = p.get("acquired") == "auction" and float(p["salary"]) > central
        lead = (
            f"{NO_DATA_LABEL[0].upper()}{NO_DATA_LABEL[1:]}: {no_data_kind(p)} with no match record "
            f"fetches about {cr(price)} cr ({cr(central)} in the top quarter) against {cr_exact(salary)}"
            + (
                "; franchises bid him well above that at the auction, so they saw something our "
                "data can't."
                if above
                else "."
            )
        )
    else:
        role, sd, balls = p["role"], p.get("value_sd"), p.get("target_balls")
        # the market price (fitted to real auctions) when the model and its inputs are there; the
        # on-field curve's price is kept alongside ("on-field worth")
        onfield = est_value(value, role, sd, balls)
        price = onfield
        central = est_value(value, role, 0.0, balls)
        p_bought = None
        if mkt:
            # median market price; the upper figure is the upper quartile of what players like him
            # fetch, on his central value
            mk = market_price(p)
            price, p_bought = mk["price"], mk["p_bought"]
            central = market_price({**p, "value_sd": 0, "price_value_sd": 0})["high"]
    model = load_keep_model()
    fc = p.get("forecast") or {}
    ties = _ties(p)
    tie_text = f" ({', '.join(ties)})" if ties else ""
    if model is None:
        rec = "borderline"
        reason = (lead + " " if lead else "") + (
            f"Worth about {cr(price)} cr at auction against {cr_exact(salary)} to keep; no "
            f"retention model is loaded, so no call."
        )
        p_keep = None
    else:
        f = keep_features(
            price, salary, False, fc.get("avg3"), fc.get("p_regular_last"),
            (p.get("team") or "") in (p.get("captain_teams") or []), int(p.get("seasons_here") or 0),
            bool(p.get("home_grown")), (p.get("intl_caps") or 0) > 0 and not p.get("overseas"),
            bool(p.get("overseas")), p.get("age"), p.get("ipl_balls"), p.get("acquired") == "auction",
            p.get("p_play"), p.get("contrib"), bool(p.get("slab_holder")), p.get("matches_last"),
        )  # fmt: skip
        p_keep = keep_probability(f, model)
        rec = call_of(p_keep)
        pct = math.floor(100 * p_keep + 0.5)
        reason = (lead + " " if lead else "") + (
            f"Worth about {cr(price)} cr at auction against {cr_exact(salary)} to keep{tie_text}: "
            f"franchises kept {pct}% of players like him at their retention deadlines (2018-2026)."
        )
    unseen = not out["no_data"] and form_unseen(p, central)
    if unseen:
        reason += FORM_UNSEEN_SENTENCE.format(paid=cr_exact(float(p["salary"])))
    reason += stale_sentence(p)
    reason += cost_sentence(p, salary)
    out.update(
        form_unseen=unseen,
        price=price,
        price_central=central,
        onfield=onfield,
        p_bought=p_bought,
        surplus=price - salary,
        p_keep=p_keep,
        default_keep=True if p_keep is None else p_keep >= KEEP_CALL,
        rec=rec,
        reason=reason,
        should=None if unseen else should_of(price, central, salary),
    )
    return out


def player_key(p: dict) -> str:
    return p.get("id") or f"name:{p['team']}:{p['name']}"


# ---- squad ----------------------------------------------------------------------------------------


def level(p: dict) -> float | None:
    """How good a player is for a role gap: his contribution per match (runs above replacement, both
    roles at his balls; METHODOLOGY §6c), else (an export before it) his value. Mirror of `level` in
    keep.ts."""
    c = p.get("contrib")
    return float(c) if c is not None else p.get("value")


def free_agents(pool: list[dict], tags: dict[str, str]) -> list[dict]:
    """The replacement market: priced auction-pool players with no franchise, with their tags."""
    out = []
    for r in pool:
        if r.get("team"):
            continue
        t = tags.get(r["cricsheet_id"], "")
        if r.get("is_overseas") and "x" not in t:
            t += "x"
        out.append(
            {
                "id": r["cricsheet_id"],
                "name": r.get("name"),
                "value": r["value"],
                "contrib": r.get("contrib"),
                "price": r["projected_value"],
                "overseas": bool(r.get("is_overseas")),
                "tags": t,
                "from_team": None,
            }
        )
    return out


def market_for(
    team: str,
    players: list[dict],
    pool: list[dict],
    tags: dict[str, str],
    form: dict | None = None,
    rules: dict[str, Any] | None = None,
) -> list[dict]:
    """The auction pool a team will shop in: today's free agents plus the players our calls send
    back from the other squads (their Release recommendations), each at our estimated price.
    `rules` (the competition's) sets what keeping each of them costs (`retention_costs`)."""
    out = free_agents(pool, tags)
    costs: dict[str, float] = {}
    if rules is not None:
        teams: dict[str, list[dict]] = {}
        for p in players:
            teams.setdefault(p.get("team") or "", []).append(p)
        for t in sorted(teams):
            costs.update(retention_costs(teams[t], rules))
    for p in players:
        if p.get("team") == team or p.get("value") is None:
            continue
        a = assess(p, form, costs.get(player_key(p)))
        if a["default_keep"]:
            continue
        t = p.get("tags") or ""
        if p.get("overseas") and "x" not in t:
            t += "x"
        out.append(
            {
                "id": player_key(p),
                "name": p["name"],
                "value": p["value"],
                "contrib": p.get("contrib"),
                "price": a["price"],
                "overseas": bool(p.get("overseas")),
                "tags": t,
                "from_team": p["team"],
            }
        )
    return out


def _fit_order(p: dict) -> tuple:
    """Who goes first when the default plan is over a limit: Toss-up before Keep, then the
    lowest chance a franchise keeps him (an unpriced player first), then the key."""
    tier = 0 if p["rec"] == "borderline" else 1
    pk = p.get("p_keep")
    return (tier, -math.inf if pk is None else pk, p["key"])


def fit_to_rules(players: list[dict], rules: dict[str, Any]) -> None:
    """Make the default plan legal: while the kept overseas players are over the overseas cap (or the
    overseas retention limit), release kept overseas Toss-up players, lowest chance kept first
    (a Keep only once no Toss-up is left); then the same for the squad maximum (or the retention
    limit) over every kept player. A player the user decided on is never moved. Each one released here
    gets `auto_release` ("overseas" | "squad") and a sentence on his reason. In place.
    Mirror of `fitToRules` in keep.ts."""
    sq_max = int(rules["squad_max"])
    mr = int(rules.get("max_retained") or 0)
    if mr:
        sq_max = min(sq_max, mr)
    os_max = int(rules["overseas_max"])
    mo = int(rules.get("max_overseas_retained") or 0)
    if mo:
        os_max = min(os_max, mo)

    def movable(p: dict, overseas: bool) -> bool:
        return (
            p["kept"]
            and not p["overridden"]
            and p["rec"] in ("borderline", "keep")
            and (not overseas or bool(p.get("overseas")))
        )

    for kind, limit, os_only in (("overseas", os_max, True), ("squad", sq_max, False)):
        count = sum(1 for p in players if p["kept"] and (not os_only or p.get("overseas")))
        if count <= limit:
            continue
        for p in sorted((p for p in players if movable(p, os_only)), key=_fit_order):
            if count <= limit:
                break
            p["kept"] = False
            p["auto_release"] = kind
            p["reason"] += (
                f" Released to fit the {limit}-overseas cap."
                if kind == "overseas"
                else f" Released to fit the {limit}-player squad limit."
            )
            count -= 1


def evaluate(
    squad: list[dict],
    market: list[dict],
    rules: dict[str, Any],
    decisions: dict[str, str] | None = None,
    needs: dict[str, int] | None = None,
    form: dict | None = None,
) -> dict[str, Any]:
    """A franchise's whole retention picture.

    `squad` = its keep.json rows; `market` = `free_agents(...)` (already priced); `rules` = the
    competition's rules; `decisions` = {player_key: "keep" | "release"} overrides of the default
    (kept when the chance a franchise keeps a player like him is at least KEEP_CALL); `needs` overrides DEFAULT_NEEDS and the
    overseas target."""
    decisions = decisions or {}
    players = []
    costs = retention_costs(squad, rules)
    for p in squad:
        key = player_key(p)
        a = assess(p, form, costs[key])
        default_keep = a["default_keep"]
        d = decisions.get(key)
        kept = default_keep if d not in ("keep", "release") else d == "keep"
        players.append(
            {**p, **a, "key": key, "kept": kept, "overridden": d in ("keep", "release"),
             "auto_release": None}
        )  # fmt: skip
    fit_to_rules(players, rules)

    kept = [p for p in players if p["kept"]]
    released = [p for p in players if not p["kept"]]
    salary_kept = fsum(float(p["salary"]) for p in kept)
    charged = purse_charged(kept, rules)
    overseas_kept = sum(1 for p in kept if p.get("overseas"))
    purse = float(rules["purse"])
    purse_left = purse - charged
    slots_left = int(rules["squad_max"]) - len(kept)
    overseas_slots = int(rules["overseas_max"]) - overseas_kept

    overseas_now = sum(1 for p in players if p.get("overseas"))
    target = {**DEFAULT_NEEDS, "overseas": min(int(rules["overseas_max"]), overseas_now)}
    for k, v in (needs or {}).items():
        if k in target and isinstance(v, int | float) and v >= 0:
            target[k] = int(v)

    # role gaps, filled greedily in TAG_ORDER from the cheapest good-enough free agents; a pick
    # counts for every tag he carries and uses an overseas slot if he's overseas
    have = {t: sum(1 for p in kept if has_tag(p, t)) for t in TAG_ORDER}
    picked: set[str] = set()
    room = max(slots_left, 0)
    os_room = max(overseas_slots, 0)
    gaps = []
    for tag in TAG_ORDER:
        need = max(0, target[tag] - have[tag])
        # the bar: the best player the team released with this tag, by contribution per match
        rel_vals = [level(p) for p in released if has_tag(p, tag) and level(p) is not None]
        ref = max(rel_vals) if rel_vals else 0.0
        picks = []
        if need > 0:
            cands = [
                c
                for c in market
                if TAG_LETTER[tag] in c["tags"]
                and (level(c) if level(c) is not None else -math.inf) >= ref
                and c["id"] not in picked
            ]
            cands.sort(key=lambda c: (c["price"], -(level(c) or 0.0), c["id"]))
            for c in cands:
                if len(picks) >= need or room <= 0:
                    break
                if c["overseas"] and os_room <= 0:
                    continue
                picks.append(c)
                picked.add(c["id"])
                room -= 1
                if c["overseas"]:
                    os_room -= 1
                for t in TAG_ORDER:
                    if TAG_LETTER[t] in c["tags"]:
                        have[t] += 1
        gaps.append(
            {
                "tag": tag,
                "label": TAG_LABEL[tag],
                "target": target[tag],
                "kept": sum(1 for p in kept if has_tag(p, tag)),
                # short of the target on the kept players alone (target − kept); `to_buy` is what is
                # still needed after the buys for the roles above it (a pick counts for every tag he
                # carries), so a gap the earlier buys already fill shows to_buy 0
                "gap": max(0, target[tag] - sum(1 for p in kept if has_tag(p, tag))),
                "to_buy": need,
                "ref_value": ref,
                "ref_from_release": bool(rel_vals),
                "picks": [
                    {
                        "id": c["id"],
                        "name": c["name"],
                        "price": c["price"],
                        "value": c["value"],
                        "from_team": c["from_team"],
                    }
                    for c in picks
                ],
                "cost": fsum(c["price"] for c in picks),
                "short": need - len(picks),
            }
        )
    replacement_cost = fsum(g["cost"] for g in gaps)
    n_picks = sum(len(g["picks"]) for g in gaps)
    to_min = max(0, int(rules["squad_min"]) - len(kept) - n_picks)

    warnings: list[str] = []
    if len(kept) > int(rules["squad_max"]):
        warnings.append(f"Keeping {len(kept)}: over the {rules['squad_max']}-player squad limit.")
    if overseas_kept > int(rules["overseas_max"]):
        warnings.append(
            f"Keeping {overseas_kept} overseas players: over the cap of {rules['overseas_max']}."
        )
    mr = int(rules.get("max_retained") or 0)
    if mr and len(kept) > mr:
        warnings.append(f"Keeping {len(kept)}: the rules allow {mr}.")
    mo = int(rules.get("max_overseas_retained") or 0)
    if mo and overseas_kept > mo:
        warnings.append(f"Keeping {overseas_kept} overseas: the rules allow {mo}.")
    if purse_left < 0:
        warnings.append(
            f"Kept players cost more than the {cr(purse)} cr purse by {cr(-purse_left)} cr."
        )
    elif purse_left - replacement_cost < to_min * MIN_SLOT_PRICE:
        warnings.append(
            f"After the replacements there isn't enough purse to reach {rules['squad_min']} "
            f"players at {cr(MIN_SLOT_PRICE)} cr each."
        )
    for g in gaps:
        if g["short"] > 0:
            warnings.append(
                f"{g['label']}: only {len(g['picks'])} of {g['to_buy']} found in the pool at that "
                f"level (or no squad / overseas room left)."
            )

    return {
        "players": players,
        "kept": len(kept),
        "released": len(released),
        "overseas_kept": overseas_kept,
        "salary_kept": salary_kept,
        # what the kept players cost the purse (salaries, or retention slabs; `purse_charged`)
        "purse_charged": charged,
        "salary_released": fsum(float(p["salary"]) for p in released),
        "purse": purse,
        "purse_left": purse_left,
        "slots_left": slots_left,
        "overseas_slots_left": overseas_slots,
        "gaps": gaps,
        "replacement_cost": replacement_cost,
        "purse_after_replacements": purse_left - replacement_cost,
        "to_min_after_replacements": to_min,
        "warnings": warnings,
    }


def squad_of(data: dict, team: str) -> list[dict]:
    """A team's rows from keep.json."""
    return [p for p in data.get("players", []) if p.get("team") == team]


def to_csv_rows(res: dict) -> list[list[str]]:
    """The table as CSV rows (the page's "Export CSV" writes the same columns)."""
    head = [
        "player", "team", "role", "overseas", "age", "acquired", "salary_cr", "value",
        "value_sd", "value_next_season", "cost_cr", "price_cr", "priced_on_value", "onfield_cr", "p_bought", "surplus_cr", "p_keep",
        "recommendation", "should_keep",
        "decision", "auto_release", "reason", "outlook", "form", "outlook_3y_avg", "outlook_3y",
    ]  # fmt: skip
    rows = [head]
    for p in res["players"]:
        rows.append(
            [
                p["name"],
                p["team"],
                p["role"],
                "yes" if p.get("overseas") else "no",
                "" if p.get("age") is None else str(math.floor(p["age"])),
                p.get("acquired") or "",
                fmt_num(float(p["salary"]), 2),
                "" if p.get("value") is None else fmt_num(p["value"], 1),
                "" if p.get("value_sd") is None else fmt_num(p["value_sd"], 1),
                "" if p.get("value_now") is None else fmt_num(p["value_now"], 1),
                fmt_num(float(p["cost"]), 2),
                "" if p.get("price") is None else fmt_num(p["price"], 2),
                # the value the market price used (its own recipe input, METHODOLOGY §6b)
                ""
                if p.get("price") is None or p.get("price_value") is None
                else fmt_num(p["price_value"], 1),
                "" if p.get("onfield") is None else fmt_num(p["onfield"], 2),
                "" if p.get("p_bought") is None else fmt_num(p["p_bought"], 2),
                "" if p.get("surplus") is None else fmt_num(p["surplus"], 2),
                "" if p.get("p_keep") is None else fmt_num(p["p_keep"], 2),
                p["rec"],
                p.get("should") or "",
                "keep" if p["kept"] else "release",
                p.get("auto_release") or "",
                p["reason"],
                p["outlook"],
                p["form_note"],
                "" if p.get("forecast_avg3") is None else fmt_num(p["forecast_avg3"], 1),
                p.get("forecast_note") or "",
            ]
        )
    return rows
