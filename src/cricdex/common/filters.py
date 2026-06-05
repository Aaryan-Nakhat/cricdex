"""Shared player-row filtering + windowed-leaderboard loading.

A 1:1 Python port of `site/src/lib/filters.ts` (the web FilterBar) plus the
windowed-leaderboard / cohort loaders that mirror `site/src/lib/data.ts`. The
Streamlit dashboard and the Textual TUI both import this so the desktop
surfaces filter and window leaderboards *exactly* like the React app — one
implementation, no drift. `test_scripts/test_filters_parity.py` locks
`apply_filters` against the TS `applyFilters`.

Rows carry the Gemini taxonomy fields (`primary_role` / `bowling_category` /
`batting_position` / `country`), an `active` flag, a `matches` count, and
`first_match_date` / `last_match_date` — injected at export time, so any
player-keyed table filters on them with one helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cricdex.web_parity.loader import _base, _read

# ---- filter model (mirrors the `Filters` interface in filters.ts) -----------


@dataclass(frozen=True)
class Filters:
    min_matches: int = 0
    role: str = ""  # primary_role | ""
    bowling: str = ""  # bowling_category | ""
    position: str = ""  # batting_position | ""
    country: str = ""  # ISO-3 | ""
    activity: str = "all"  # "all" | "active" | "retired"
    year_from: int = 0  # 0 = unset
    year_to: int = 0  # 0 = unset


# ---- option lists (mirror filters.ts `*_OPTS`) ------------------------------

ACTIVITY_OPTS = [
    ("active", "Active only"),
    ("retired", "Retired only"),
    ("all", "Active + retired"),
]

ROLE_OPTS = [
    ("", "Any role"),
    ("batter", "Batter"),
    ("bowler", "Bowler"),
    ("allrounder", "All-rounder"),
    ("wk_batter", "Wicket-keeper"),
]

BOWLING_OPTS = [
    ("", "Any bowling"),
    ("seam", "Seam / pace"),
    ("spin", "Spin"),
]

POSITION_OPTS = [
    ("", "Any position"),
    ("opener", "Opener (1–2)"),
    ("no3", "No. 3"),
    ("middle", "Middle (4–5)"),
    ("finisher", "Finisher (6–7)"),
    ("lower", "Lower (8)"),
    ("tailender", "Tailender (9–11)"),
]

FILTER_HELP: dict[str, str] = {
    "min_matches": "Drops small samples — players below this many matches are hidden. Default 20.",
    "activity": (
        "Active = appeared in this format within ~18 months of the latest match; retired = not. "
        "It's per-format, so a player retired from internationals can still be Active in IPL."
    ),
    "role": "Primary role (Gemini-classified): batter, bowler, all-rounder or wicket-keeper.",
    "bowling": "Seam/pace vs spin — Gemini-classified bowling type (pure batters carry none).",
    "position": (
        "Usual batting slot bucket: opener, No.3, middle (4–5), finisher (6–7), lower (8), "
        "tailender (9–11)."
    ),
    "country": "Player's country (Gemini-classified).",
    "years": (
        "Keeps players whose career in this format overlaps the chosen years. Note: the metric "
        "values stay career totals — this filters who's shown, it doesn't recompute per year."
    ),
}


def _yr(v: Any) -> int | None:
    """First 4 chars of an ISO date → year, mirroring filters.ts `yr`."""
    if not isinstance(v, str):
        return None
    try:
        return int(v[:4])
    except ValueError:
        return None


def apply_filters(rows: list[dict], f: Filters) -> list[dict]:
    """Port of filters.ts `applyFilters` — same gates, same order."""
    lo = f.year_from or float("-inf")
    hi = f.year_to or float("inf")
    year_gate = f.year_from > 0 or f.year_to > 0
    out = []
    for r in rows:
        if float(r.get("matches") or 0) < f.min_matches:
            continue
        if f.activity == "active" and not r.get("active"):
            continue
        if f.activity == "retired" and r.get("active"):
            continue
        if f.role and r.get("primary_role") != f.role:
            continue
        if f.bowling and r.get("bowling_category") != f.bowling:
            continue
        if f.position and r.get("batting_position") != f.position:
            continue
        if f.country and r.get("country") != f.country:
            continue
        if year_gate:
            ly = _yr(r.get("last_match_date"))
            fy = _yr(r.get("first_match_date"))
            # keep if the player's [first,last] span overlaps [lo,hi]
            if ly is not None and fy is not None and (ly < lo or fy > hi):
                continue
        out.append(r)
    return out


def countries_in(rows: list[dict]) -> list[tuple[str, str]]:
    """Distinct countries present in the rows, for the country dropdown."""
    seen = sorted({str(r["country"]) for r in rows if r.get("country")})
    return [("", "Any country"), *[(c, c) for c in seen]]


# ---- windowed leaderboard + cohort loaders (mirror data.ts) -----------------

WINDOWS = ["all", "last3y", "last1y"]
WINDOW_LABELS = {"all": "All-time", "last3y": "Last 3 yrs", "last1y": "Last 1 yr"}


def window_suffix(window: str) -> str:
    """`.last1y` / `.last3y`, or "" for all-time — mirrors getLeaderboard()."""
    return f".{window}" if window and window != "all" else ""


def load_leaderboard(
    collection: str, slug: str, window: str = "all", base: Path | str | None = None
) -> list[dict]:
    """Exported leaderboard rows for a metric + time window.

    `site/public/data/<col>/leaderboards/<slug>[.<window>].json` — the exact
    file the React `getLeaderboard(c, slug, window)` fetches.
    """
    path = _base(base) / collection / "leaderboards" / f"{slug}{window_suffix(window)}.json"
    return _read(path)


def load_cohorts(collection: str, cid: str, base: Path | str | None = None) -> dict:
    """Graph cohort for a player — the `co_faced` list (who faced the same
    bowlers / bowled to the same batters).

    Reads `site/public/data/<col>/cohorts/<cid>.json` (computed offline by
    `export_site.py` straight from ball-by-ball; no Neo4j). Mirrors the web
    `getCohorts(c, cid)`.
    """
    return _read(_base(base) / collection / "cohorts" / f"{cid}.json")


__all__ = [
    "ACTIVITY_OPTS",
    "BOWLING_OPTS",
    "FILTER_HELP",
    "Filters",
    "POSITION_OPTS",
    "ROLE_OPTS",
    "WINDOWS",
    "WINDOW_LABELS",
    "apply_filters",
    "countries_in",
    "load_cohorts",
    "load_leaderboard",
    "window_suffix",
]
