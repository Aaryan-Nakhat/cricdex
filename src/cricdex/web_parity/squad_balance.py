"""Squad-balance analyzer — EXACT mirror of `site/src/lib/squad.ts`.

Given a chosen set of players, report role mix, overseas count, batting-slot
coverage, and gaps vs the role minimums + overseas cap. Pure deterministic
aggregation (no RNG), so TS↔Python match trivially.
"""

from __future__ import annotations

DEFAULT_ROLE_MINS = {"batter": 3, "bowler": 3, "all_rounder": 1, "keeper": 1}
SLOTS = ("opener", "no3", "middle", "finisher", "lower", "tailender")


def analyze_squad(
    players: list[dict],
    role_mins: dict[str, int] | None = None,
    overseas_cap: int = 8,
) -> dict:
    """`players` rows need role, is_overseas, batting_position. Returns role/slot
    counts, overseas count, and human-readable gaps + a `balanced` flag."""
    mins = role_mins or DEFAULT_ROLE_MINS
    roles: dict[str, int] = {}
    slots: dict[str, int] = {}
    overseas = 0
    for p in players:
        roles[p.get("role") or "?"] = roles.get(p.get("role") or "?", 0) + 1
        bp = p.get("batting_position")
        if bp:
            slots[bp] = slots.get(bp, 0) + 1
        if p.get("is_overseas"):
            overseas += 1

    gaps: list[str] = []
    for r, m in mins.items():
        have = roles.get(r, 0)
        if have < m:
            gaps.append(f"need {m - have} more {r.replace('_', '-')} (have {have}/{m})")
    if overseas > overseas_cap:
        gaps.append(f"{overseas - overseas_cap} over the overseas cap ({overseas}/{overseas_cap})")
    if not any(slots.get(s, 0) for s in ("opener",)):
        gaps.append("no recognised opener")
    if not slots.get("finisher", 0):
        gaps.append("no death-overs finisher")

    return {
        "size": len(players),
        "roles": roles,
        "slots": slots,
        "overseas": overseas,
        "overseas_cap": overseas_cap,
        "gaps": gaps,
        "balanced": not gaps,
    }


__all__ = ["DEFAULT_ROLE_MINS", "SLOTS", "analyze_squad"]
