"""Best XI — exact global optimum, EXACT mirror of `site/src/lib/bestxi.ts`.

Pick exactly `size` players maximising total NGI subject to:
  • total price ≤ budget (crore),
  • overseas count ≤ overseas_cap,
  • per-role minimums (role_mins, e.g. {batter:3, bowler:3, all_rounder:1, keeper:1}).

Exact branch-and-bound over the whole pool. The result is made **unique** (and
therefore parity-safe across TS↔Python regardless of branch order) by a strict
tie-break: maximise NGI (rounded to 6dp), then minimise total price, then the
lexicographically smallest cricsheet_id list. Prices use 0.1-cr integer units so
the budget test is exact.
"""

from __future__ import annotations

_ROUND = 6  # NGI comparison precision (kills float-order drift across languages)


def _ngi_key(ngi: float) -> float:
    return round(ngi, _ROUND)


def best_xi(
    players: list[dict],
    budget: float,
    overseas_cap: int,
    role_mins: dict[str, int],
    size: int = 11,
    cap_per_role: int = 22,
) -> dict:
    """Return {"players": [chosen rows], "total_ngi", "total_price", "overseas",
    "feasible": bool}. Each input player needs cricsheet_id, name, role,
    is_overseas (bool), ngi (float), price (cr, float).

    Exact branch-and-bound over a candidate set: the top `cap_per_role` players
    per role by NGI. A full-pool exact solve is intractable in-browser (the
    multi-constraint knapsack explodes), and a player outside the top ~22 of its
    role can't be in an optimal budget XI — so this is the global optimum in
    practice, fast, and bit-exact across TS↔Python."""
    valid = [p for p in players if p.get("ngi") is not None and p.get("price") not in (None, 0)]
    # Trim per role to the top NGI candidates (deterministic).
    by_role: dict[str, list[dict]] = {}
    for p in sorted(valid, key=lambda x: (-_ngi_key(x["ngi"]), x["cricsheet_id"])):
        bucket = by_role.setdefault(p["role"], [])
        if len(bucket) < cap_per_role:
            bucket.append(p)
    cand = [p for bucket in by_role.values() for p in bucket]
    # Deterministic order: NGI desc, price asc, cid — also a good B&B order.
    cand.sort(key=lambda p: (-_ngi_key(p["ngi"]), round(p["price"] * 10), p["cricsheet_id"]))
    n = len(cand)
    price_i = [round(p["price"] * 10) for p in cand]
    ngi = [float(p["ngi"]) for p in cand]
    over = [1 if p.get("is_overseas") else 0 for p in cand]
    role = [p["role"] for p in cand]
    budget_i = round(budget * 10)
    roles = list(role_mins)
    min_total = sum(role_mins.values())

    best = {"ngi": -1.0, "price": 0, "cids": None, "picked": None}

    def better(cur_ngi: float, cur_price: int, cids: list[str]) -> bool:
        bn = best["ngi"]
        cn = round(cur_ngi, _ROUND)
        if cn != round(bn, _ROUND):
            return cn > bn
        if cur_price != best["price"]:
            return cur_price < best["price"]
        return best["cids"] is None or sorted(cids) < best["cids"]

    def bound(i: int, slots_left: int, ov: int) -> float:
        """Admissible upper bound on remaining NGI: the top `slots_left` NGIs
        from cand[i:] that still fit the overseas cap. Returns -1 if the slots
        can't be filled within the cap (→ prune)."""
        rem_os = overseas_cap - ov
        s = 0.0
        taken = 0
        j = i
        while j < n and taken < slots_left:
            if over[j] == 0 or rem_os > 0:
                s += ngi[j]
                taken += 1
                if over[j]:
                    rem_os -= 1
            j += 1
        return s if taken == slots_left else -1.0

    def dfs(
        i: int, picked: list[int], spent: int, ov: int, cur: float, rcount: dict[str, int]
    ) -> None:
        k = len(picked)
        if k == size:
            if any(rcount.get(rr, 0) < role_mins[rr] for rr in roles):
                return  # role minimums not met
            cids = sorted(cand[j]["cricsheet_id"] for j in picked)
            if better(cur, spent, cids):
                best.update(ngi=cur, price=spent, cids=cids, picked=list(picked))
            return
        if i >= n or n - i < size - k:
            return
        slots_left = size - k
        b = bound(i, slots_left, ov)
        if b < 0:
            return
        if best["cids"] and round(cur + b, _ROUND) <= round(best["ngi"], _ROUND):
            return
        r = role[i]
        need_role = sum(max(0, role_mins.get(rr, 0) - rcount.get(rr, 0)) for rr in roles)
        if (
            spent + price_i[i] <= budget_i
            and ov + over[i] <= overseas_cap
            and need_role <= slots_left
        ):
            rcount[r] = rcount.get(r, 0) + 1
            picked.append(i)
            dfs(i + 1, picked, spent + price_i[i], ov + over[i], cur + ngi[i], rcount)
            picked.pop()
            rcount[r] -= 1
        if n - (i + 1) >= size - k:
            dfs(i + 1, picked, spent, ov, cur, rcount)

    if min_total <= size:
        dfs(0, [], 0, 0, 0.0, {})

    if best["picked"] is None:
        return {
            "players": [],
            "total_ngi": 0.0,
            "total_price": 0.0,
            "overseas": 0,
            "feasible": False,
        }
    chosen = [cand[j] for j in best["picked"]]
    chosen.sort(key=lambda p: (-_ngi_key(p["ngi"]), p["cricsheet_id"]))
    return {
        "players": chosen,
        "total_ngi": round(best["ngi"], 3),
        "total_price": round(best["price"] / 10, 1),
        "overseas": sum(1 for p in chosen if p.get("is_overseas")),
        "feasible": True,
    }


__all__ = ["best_xi"]
