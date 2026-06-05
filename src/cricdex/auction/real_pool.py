"""Real IPL franchise configs + bidding-personality defaults.

The canonical, web-identical auction Monte-Carlo lives in `cricdex.web_parity`
(shared by the web app + CLI + TUI + Streamlit, parity-locked). This module
only supplies the franchise/personality defaults the desktop Auction reads:

- `IPL_TEAMS_DEFAULT` — the 10 real teams keyed to a bidding archetype.
- `FRANCHISE_ARCHETYPES` / `PERSONALITY_IDS` — the archetype catalog + their ids
  (so UI dropdowns can list them).
- `load_team_overrides` — optional `~/.cricdex/teams.yaml` per-team overrides.
"""

from __future__ import annotations

from pathlib import Path

FRANCHISE_ARCHETYPES: list[dict] = [
    # id, purse, aggression, risk-jitter, per-role minimums, overseas appetite
    {
        "id": "MarqueeChaser",
        "purse": 90.0,
        "aggression": 1.35,
        "risk": 0.20,
        "role_mins": {"batter": 6, "bowler": 4, "all_rounder": 4, "keeper": 2},
    },
    {
        "id": "ValueHunter",
        "purse": 90.0,
        "aggression": 0.85,
        "risk": 0.30,
        "role_mins": {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2},
    },
    {
        "id": "OverseasHeavy",
        "purse": 90.0,
        "aggression": 1.15,
        "risk": 0.18,
        "role_mins": {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2},
        "overseas_left": 8,
    },
    {
        "id": "IndianFocus",
        "purse": 90.0,
        "aggression": 1.05,
        "risk": 0.15,
        "role_mins": {"batter": 7, "bowler": 5, "all_rounder": 3, "keeper": 2},
        "overseas_left": 3,
    },
    {
        "id": "AllRounderStack",
        "purse": 90.0,
        "aggression": 1.10,
        "risk": 0.22,
        "role_mins": {"batter": 4, "bowler": 4, "all_rounder": 6, "keeper": 2},
    },
    {
        "id": "Balanced",
        "purse": 90.0,
        "aggression": 1.00,
        "risk": 0.15,
        "role_mins": {"batter": 5, "bowler": 5, "all_rounder": 3, "keeper": 2},
    },
]


# IPL 2024+ franchise roster keyed to bidding archetypes. The defaults
# are hand-picked from broad historical patterns (CSK = disciplined /
# balanced under Dhoni; MI + RCB = marquee-buyer-heavy; KKR = all-
# rounder stack with Russell/Narine; SRH + LSG = overseas-heavy in
# their respective eras; DC = Indian-talent focus; PBKS + RR = value-
# hunters; GT = balanced cap management). They're opinions, not facts
# — override per-team via `~/.cricdex/teams.yaml` or via the TUI /
# Streamlit per-team selectors.
IPL_TEAMS_DEFAULT: list[tuple[str, str]] = [
    ("CSK", "Balanced"),
    ("MI", "MarqueeChaser"),
    ("RCB", "MarqueeChaser"),
    ("KKR", "AllRounderStack"),
    ("DC", "IndianFocus"),
    ("PBKS", "ValueHunter"),
    ("SRH", "OverseasHeavy"),
    ("GT", "Balanced"),
    ("RR", "ValueHunter"),
    ("LSG", "OverseasHeavy"),
]

# All personality ids, exposed so UI code can populate dropdowns
# without re-deriving them from FRANCHISE_ARCHETYPES.
PERSONALITY_IDS: tuple[str, ...] = tuple(a["id"] for a in FRANCHISE_ARCHETYPES)
_PERSONALITY_BY_ID: dict[str, dict] = {a["id"]: a for a in FRANCHISE_ARCHETYPES}


def load_team_overrides(
    path: Path | None = None,
) -> list[tuple[str, str]] | None:
    """Read a YAML file mapping team → personality so power users can
    customise without touching code. File shape:

        teams:
          - {name: CSK,  personality: Balanced}
          - {name: MI,   personality: MarqueeChaser}
          ...

    Returns None if the file is missing / unreadable / malformed, so
    the caller falls back to `IPL_TEAMS_DEFAULT`. PyYAML is optional;
    we soft-fail if it's not installed.
    """
    if path is None:
        path = Path.home() / ".cricdex" / "teams.yaml"
    if not path.exists():
        return None
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return None
    teams = data.get("teams")
    if not isinstance(teams, list):
        return None
    out: list[tuple[str, str]] = []
    for row in teams:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        personality = row.get("personality")
        if name and personality in _PERSONALITY_BY_ID:
            out.append((str(name), str(personality)))
    return out or None
