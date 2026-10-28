"""A player's public following: the monthly views of his English Wikipedia article.

The market price (docs/METHODOLOGY.md §6b) takes it as the brand feature: how many people read about a
player in the twelve complete months before an auction, a dated, public measure of fame that the
auction rooms of 2018-2026 could see too. The data are the Wikimedia Pageviews API's monthly human
views (CC0), fetched by `scripts/wiki_pageviews.py` into `data/curated/wiki_pageviews.json`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from cricdex.config import DATA_DIR

PATH = DATA_DIR / "curated" / "wiki_pageviews.json"
WINDOW_MONTHS = 12  # the months before the auction month that are averaged
MIN_MONTHS = 6  # fewer months of data before the auction than this: no reading


@lru_cache(maxsize=2)
def load(path: str | None = None) -> dict:
    """{"first_month", "last_month", "views": {title: [monthly views]}}; empty when not fetched."""
    p = Path(path) if path else PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _index(month: str, first: str) -> int:
    return (int(month[:4]) - int(first[:4])) * 12 + int(month[5:7]) - int(first[5:7])


def views_asof(title: str | None, date: str, data: dict | None = None) -> float | None:
    """Mean monthly views of `title`'s article over the WINDOW_MONTHS complete months before the
    month of `date` (YYYY-MM-DD), or before the data's last month when that is earlier (an auction
    that hasn't happened yet). None without a title, without data for it, or with fewer than
    MIN_MONTHS months before `date` (the API starts in July 2015)."""
    d = load() if data is None else data
    if not title or not d:
        return None
    series = (d.get("views") or {}).get(title)
    if series is None:
        return None
    first = d["first_month"]
    end = min(_index(date[:7], first), _index(d["last_month"], first) + 1)  # exclusive
    start = max(0, end - WINDOW_MONTHS)
    window = series[start:end]
    if len(window) < MIN_MONTHS:
        return None
    return sum(window) / len(window)
