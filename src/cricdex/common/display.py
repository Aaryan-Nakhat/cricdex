"""Player display names and data-freshness markers, shared by the CLI, TUI and Streamlit.

The site export gives every player row a fan-facing `display_name` (and, on multi-name rows such
as records and partnerships, a `<field>_display` per name field), plus `full_name` and `aliases`.
Collections whose data stops early carry `stale: true` and `data_as_of` in collections.json /
meta.json. Everything here falls back gracefully when an older export lacks those fields.
"""

from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from pathlib import Path

from cricdex.config import SITE_DATA


def display_name(row: dict | None, field: str = "name") -> str:
    """The name a fan would use for `row[field]`: `<field>_display`, else (for the row's own
    name field) `display_name`, else the scorecard name. "" when there is none."""
    if not row:
        return ""
    own = row.get(f"{field}_display")
    if own:
        return str(own)
    if field in ("name", "unique_name") and row.get("display_name"):
        return str(row["display_name"])
    v = row.get(field)
    return "" if v is None else str(v)


def apply_display(rows: list[dict], drop_ids: bool = True) -> list[dict]:
    """Rows with every name field swapped for its fan-facing `<field>_display` (records:
    batter / bowler; partnerships: a / b), the helper columns (`*_display`, `display_name` and,
    with `drop_ids`, `cricsheet_id` / `*_cid`) dropped. Rows without those fields pass through."""
    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            if k.endswith("_display") or k == "display_name":
                continue
            if drop_ids and (k == "cricsheet_id" or k.endswith("_cid")):
                continue
            disp = r.get(f"{k}_display")
            d[k] = disp if disp else v
        out.append(d)
    return out


def search_names(row: dict) -> list[str]:
    """Every name a player can be found by: display, scorecard, full name and aliases."""
    out: list[str] = []
    for n in (
        row.get("display_name"),
        row.get("name"),
        row.get("full_name"),
        *(row.get("aliases") or []),
    ):
        if n and str(n) not in out:
            out.append(str(n))
    return out


def player_label(row: dict) -> str:
    """'Virat Kohli (V Kohli)' — the display name plus the scorecard name when different, and any
    other alias, so a type-ahead finds the player by any of them."""
    names = search_names(row)
    if not names:
        return ""
    head, rest = names[0], [n for n in names[1:] if n.lower() != names[0].lower()]
    return f"{head} ({' · '.join(rest)})" if rest else head


def _read(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=64)
def _freshness(collection: str, base: str) -> tuple[bool, str | None]:
    root = Path(base)
    meta = _read(root / collection / "meta.json")
    if not isinstance(meta, dict):
        cols = _read(root / "collections.json")
        meta = (
            next(
                (c for c in cols if isinstance(c, dict) and c.get("collection") == collection),
                None,
            )
            if isinstance(cols, list)
            else None
        )
    if not isinstance(meta, dict):
        return (False, None)
    return (bool(meta.get("stale")), meta.get("data_as_of"))


def freshness(collection: str, base: Path | str | None = None) -> tuple[bool, str | None]:
    """(stale?, data_as_of) for a collection, from its meta.json (or collections.json)."""
    return _freshness(collection, str(base or SITE_DATA))


def pretty_date(iso: str | None) -> str:
    """'2024-12-15' -> '15 Dec 2024' (the input back unchanged when it isn't a date)."""
    if not iso:
        return "—"
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def stale_note(data_as_of: str | None) -> str:
    """'data to 15 Dec 2024 — stale'."""
    return f"data to {pretty_date(data_as_of)} — stale"


def stale_marker(collection: str, base: Path | str | None = None) -> str:
    """'data to 15 Dec 2024 — stale' for a stale collection, else ''."""
    stale, as_of = freshness(collection, base)
    return stale_note(as_of) if stale else ""


def league_label(collection: str) -> str:
    """A league picker label: the registry name, plus the stale marker when its data stops early."""
    from cricdex import leagues

    mark = stale_marker(collection)
    return f"{leagues.label(collection)} · {mark}" if mark else leagues.label(collection)


def profile_collection(row: dict | None, default: str = "ipl") -> str:
    """The league whose profile file a Scout / Auction row's player has (non-IPL players have no
    IPL profile). Falls back to `default` on exports without the field."""
    return str((row or {}).get("profile_collection") or default)


__all__ = [
    "apply_display",
    "display_name",
    "freshness",
    "league_label",
    "player_label",
    "pretty_date",
    "profile_collection",
    "search_names",
    "stale_marker",
    "stale_note",
]
