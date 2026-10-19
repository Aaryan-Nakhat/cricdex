"""Shared player-row filtering + windowed-leaderboard loading.

A 1:1 Python port of `site/src/lib/filters.ts` (the web FilterBar) plus the
windowed-leaderboard / cohort loaders that mirror `site/src/lib/data.ts`. The
Streamlit dashboard and the Textual TUI both import this so the desktop
surfaces filter and window leaderboards *exactly* like the React app — one
implementation, no drift. `test_scripts/test_filters_parity.py` locks
`apply_filters` against the TS `applyFilters`.

Rows carry the LLM taxonomy fields (`primary_role` / `bowling_category` /
`batting_position` / `country`), an `active` flag and a `matches` count —
injected at export time, so any
player-keyed table filters on them with one helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
    "role": "Primary role (AI-classified): batter, bowler, all-rounder or wicket-keeper.",
    "bowling": "Seam/pace vs spin — AI-classified bowling type (pure batters carry none).",
    "position": (
        "Usual batting slot bucket: opener, No.3, middle (4–5), finisher (6–7), lower (8), "
        "tailender (9–11)."
    ),
    "country": "Player's country (AI-classified).",
}


def apply_filters(rows: list[dict], f: Filters) -> list[dict]:
    """Port of filters.ts `applyFilters` — same gates, same order."""
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
        out.append(r)
    return out


def countries_in(rows: list[dict]) -> list[tuple[str, str]]:
    """Distinct countries present in the rows, for the country dropdown."""
    seen = sorted({str(r["country"]) for r in rows if r.get("country")})
    return [("", "Any country"), *[(c, c) for c in seen]]


# ---- windowed leaderboard + cohort loaders (mirror data.ts) -----------------

WINDOWS = ["all", "last3y", "last1y"]
WINDOW_LABELS = {"all": "All-time", "last3y": "Last 3 yrs", "last1y": "Last 1 yr"}


def _meta(collection: str, base: Path | str | None) -> dict:
    try:
        return _read(_base(base) / collection / "meta.json") or {}
    except (FileNotFoundError, ValueError):
        return {}


def windows_for(collection: str, base: Path | str | None = None) -> list[str]:
    """The periods a collection's leaderboards were cooked for: all-time, the time windows and any
    era of the league (`meta.json` `windows`, e.g. "era_impact"); the fixed list for an older export."""
    meta = _meta(collection, base)
    cooked = [w for w in meta.get("windows") or [] if w not in WINDOWS]
    return [*WINDOWS, *cooked]


def window_label(window: str, collection: str | None = None, base: Path | str | None = None) -> str:
    """ "All-time" / "Last 3 yrs" / an era's name ("Impact Player era", from `meta.window_labels`)."""
    if window in WINDOW_LABELS:
        return WINDOW_LABELS[window]
    if collection:
        meta = _meta(collection, base)
        label = (meta.get("window_labels") or {}).get(window)
        if label:
            return label
    return window


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
    "window_label",
    "window_suffix",
    "windows_for",
]
