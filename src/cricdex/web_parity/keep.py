"""Keep or release: the franchise retention calculator. EXACT mirror of `site/src/lib/keep.ts`.

For every player in a franchise's squad it sets our estimated auction price (the auction pool's
price curve: cautious estimate, IPL-evidence ceiling) against his salary, and recommends Keep,
Release or Borderline with a one-line reason. For the squad it adds up the purse left after the
kept salaries, the open slots, the role gaps (keepers, openers, death bowlers, spinners, overseas)
and what filling each gap from the current auction pool would cost.

Inputs are the exported `keep.json` (squads, salaries, values, tags, rules) and `auction_pool.json`
(the free agents); the rules (purse, squad size, overseas cap) come from `config/competitions.toml`
through that export. `test_scripts/test_keep_parity.py` runs the TypeScript on the same inputs and
fails if any number or sentence differs. The method in plain words: docs/METHODOLOGY.md §10.
"""

from __future__ import annotations

import math
from typing import Any

from cricdex.web_parity.pricing import PRICE_TIERS, est_value, has_market_inputs, market_price

# A recommendation needs a gap of at least this much between price and salary (cr): the larger of
# KEEP_MARGIN_MIN and KEEP_MARGIN_SHARE × salary. Inside it the player is fairly paid (Borderline).
KEEP_MARGIN_MIN = 0.5
KEEP_MARGIN_SHARE = 0.15
# A value sd at least this wide (runs per 100 balls) counts as a thin record in the reason.
THIN_SD = 6.0
# From this age a Keep becomes Borderline unless the surplus is at least twice the margin.
AGE_DECLINE = 35
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


def margin(salary: float) -> float:
    return max(KEEP_MARGIN_MIN, KEEP_MARGIN_SHARE * salary)


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


def outlook(age: float | None) -> str:
    if age is None:
        return "Age unknown."
    if age < 24:
        return "Young: likely to improve."
    if age < 30:
        return "Prime years."
    if age < 33:
        return "Holding: most players hold their level to about 33."
    if age < AGE_DECLINE:
        return "Past 32: values usually start to slip."
    return f"{AGE_DECLINE}+: expect decline; a short-term keep at best."


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


def assess(p: dict, form: dict | None = None) -> dict[str, Any]:
    """One player's numbers and recommendation. `p` is a keep.json squad row."""
    salary = float(p["salary"])
    value = p.get("value")
    out: dict[str, Any] = {
        "price": None,
        "price_central": None,
        "onfield": None,
        "p_bought": None,
        "surplus": None,
        "outlook": outlook(p.get("age")),
        "form_note": form_note(p, form),
        "forecast_note": forecast_note(p),
        "forecast_avg3": (p.get("forecast") or {}).get("avg3"),
        "captain": captain_label(p),
    }
    if value is None:
        out["rec"] = "borderline"
        out["reason"] = (
            f"Not enough balls in our data to rate him: decide on scouting (he costs {cr_exact(salary)} cr)."
        )
        return out
    role, sd, balls = p["role"], p.get("value_sd"), p.get("target_balls")
    # the market price (fitted to real auctions) when the model and its inputs are there; the
    # on-field curve's price is kept alongside ("on-field worth")
    onfield = est_value(value, role, "ipl", sd, balls)
    price = onfield
    central = est_value(value, role, "ipl", 0.0, balls)
    p_bought = None
    mkt = has_market_inputs(p)
    if mkt:
        # median market price on the cautious estimate; the upper figure is the upper quartile of
        # what players like him fetch, on his central value
        mk = market_price(p)
        price, p_bought = mk["price"], mk["p_bought"]
        central = market_price({**p, "value_sd": 0})["high"]
    surplus = price - salary
    m = margin(salary)
    age = p.get("age")
    if surplus >= m:
        if age is not None and age >= AGE_DECLINE and surplus < 2 * m:
            rec = "borderline"
            reason = (
                f"Worth about {cr(price)} cr against {cr_exact(salary)}, but at {math.floor(age)} his "
                f"value usually falls from here."
            )
        else:
            rec = "keep"
            reason = (
                f"Worth about {cr(price)} cr at auction, paid {cr_exact(salary)}: "
                f"{cr(surplus)} cr of surplus."
            )
    elif central - salary <= -m:
        rec = "release"
        reason = (
            (
                f"Paid {cr_exact(salary)} cr but players like him fetch about {cr(price)} "
                f"({cr(central)} in the top quarter): releasing frees {cr_exact(salary)} cr."
            )
            if mkt
            else (
                f"Paid {cr_exact(salary)} cr but worth about {cr(central)} even on his central "
                f"estimate: releasing frees {cr_exact(salary)} cr."
            )
        )
    elif central - salary >= m:
        rec = "borderline"
        if (sd or 0.0) >= THIN_SD:
            reason = (
                f"Thin record: worth {cr(price)} to {cr(central)} cr against {cr_exact(salary)}; "
                f"keep if you trust the upside."
            )
        else:
            reason = (
                f"Close call: worth {cr(price)} ({'median' if mkt else 'cautious'}) to "
                f"{cr(central)} cr{' (top quarter)' if mkt else ''} against "
                f"{cr_exact(salary)}; a keep if you back the higher figure."
            )
    else:
        rec = "borderline"
        reason = (
            f"Fairly paid: players like him fetch {cr(price)} to {cr(central)} cr (top quarter) "
            f"against {cr_exact(salary)}."
            if mkt
            else f"Fairly paid: worth about {cr(price)} cr against {cr_exact(salary)}."
        )
    if mkt and out["captain"]:
        reason += f" Captained {out['captain']} last season: the market pays captains a premium."
    out.update(
        price=price,
        price_central=central,
        onfield=onfield,
        p_bought=p_bought,
        surplus=surplus,
        rec=rec,
        reason=reason,
    )
    return out


def player_key(p: dict) -> str:
    return p.get("id") or f"name:{p['team']}:{p['name']}"


# ---- squad ----------------------------------------------------------------------------------------


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
) -> list[dict]:
    """The auction pool a team will shop in: today's free agents plus the players our calls send
    back from the other squads (their Release recommendations), each at our estimated price."""
    out = free_agents(pool, tags)
    for p in players:
        if p.get("team") == team or p.get("value") is None:
            continue
        a = assess(p, form)
        if a["rec"] != "release":
            continue
        t = p.get("tags") or ""
        if p.get("overseas") and "x" not in t:
            t += "x"
        out.append(
            {
                "id": player_key(p),
                "name": p["name"],
                "value": p["value"],
                "price": a["price"],
                "overseas": bool(p.get("overseas")),
                "tags": t,
                "from_team": p["team"],
            }
        )
    return out


def _fit_order(p: dict) -> tuple:
    """Who goes first when the default plan is over a limit: Borderline before Keep, then the
    lowest surplus per crore of salary (an unrated player first), then the key."""
    tier = 0 if p["rec"] == "borderline" else 1
    s = p.get("surplus")
    sal = float(p["salary"])
    ratio = -math.inf if s is None else (s / sal if sal > 0 else s)
    return (tier, ratio, p["key"])


def fit_to_rules(players: list[dict], rules: dict[str, Any]) -> None:
    """Make the default plan legal: while the kept overseas players are over the overseas cap (or the
    overseas retention limit), release kept overseas Borderline players, lowest surplus per crore first
    (a Keep only once no Borderline is left); then the same for the squad maximum (or the retention
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
    (Keep and Borderline are kept, Release is released); `needs` overrides DEFAULT_NEEDS and the
    overseas target."""
    decisions = decisions or {}
    players = []
    for p in squad:
        a = assess(p, form)
        key = player_key(p)
        default_keep = a["rec"] != "release"
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
    overseas_kept = sum(1 for p in kept if p.get("overseas"))
    purse = float(rules["purse"])
    purse_left = purse - salary_kept
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
        rel_vals = [p["value"] for p in released if has_tag(p, tag) and p.get("value") is not None]
        ref = max(rel_vals) if rel_vals else 0.0
        picks = []
        if need > 0:
            cands = [
                c
                for c in market
                if TAG_LETTER[tag] in c["tags"] and c["value"] >= ref and c["id"] not in picked
            ]
            cands.sort(key=lambda c: (c["price"], -c["value"], c["id"]))
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
                "gap": need,
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
        warnings.append(f"Kept salaries exceed the {cr(purse)} cr purse by {cr(-purse_left)} cr.")
    elif purse_left - replacement_cost < to_min * MIN_SLOT_PRICE:
        warnings.append(
            f"After the replacements there isn't enough purse to reach {rules['squad_min']} "
            f"players at {cr(MIN_SLOT_PRICE)} cr each."
        )
    for g in gaps:
        if g["short"] > 0:
            warnings.append(
                f"{g['label']}: only {len(g['picks'])} of {g['gap']} found in the pool at that "
                f"level (or no squad / overseas room left)."
            )

    return {
        "players": players,
        "kept": len(kept),
        "released": len(released),
        "overseas_kept": overseas_kept,
        "salary_kept": salary_kept,
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
        "value_sd", "price_cr", "onfield_cr", "p_bought", "surplus_cr", "recommendation",
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
                "" if p.get("price") is None else fmt_num(p["price"], 2),
                "" if p.get("onfield") is None else fmt_num(p["onfield"], 2),
                "" if p.get("p_bought") is None else fmt_num(p["p_bought"], 2),
                "" if p.get("surplus") is None else fmt_num(p["surplus"], 2),
                p["rec"],
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
